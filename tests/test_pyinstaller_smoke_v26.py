from __future__ import annotations

import json
import hashlib
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import medimager.qa.pyinstaller_smoke as smoke_module
from medimager.demo import DemoGenerationProfile, DemoStudyId, DemoStudyService
from medimager.qa.pyinstaller_smoke import (
    DEFAULT_TIMEOUT_SECONDS,
    EXECUTABLE_ENV,
    OPT_IN_ENV,
    DemoCaseObservation,
    ExecutableProbeObservation,
    SmokeCase,
    SmokeCaseSpec,
    SmokeStatus,
    _read_packaged_demo_observation,
    _terminate_process,
    default_demo_smoke_plan,
    main,
    run_demo_smoke_cases,
    run_opted_in_pyinstaller_smoke,
    run_packaged_demo_smoke_cases,
    smoke_opted_in,
)


SMALL_PROFILE = DemoGenerationProfile(
    ct_shape_zyx=(4, 16, 16),
    ct_coronal_slices=4,
    mr_shape_zyx=(4, 16, 16),
    geometry_shape_zyx=(4, 16, 16),
)


class FakeDemoPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[DemoStudyId, float]] = []
        self.counts: dict[DemoStudyId, int] = {}

    def __call__(
        self,
        study_id: DemoStudyId,
        cache_root: Path,
        _profile: DemoGenerationProfile,
        timeout_seconds: float,
    ) -> DemoCaseObservation:
        self.calls.append((study_id, timeout_seconds))
        count = self.counts.get(study_id, 0)
        self.counts[study_id] = count + 1
        root = cache_root / study_id.value
        root.mkdir(parents=True, exist_ok=True)
        return DemoCaseObservation(count == 0, root)


class FakePackagedDemoPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, SmokeCaseSpec]] = []
        self.counts: dict[DemoStudyId, int] = {}

    def __call__(self, executable, app_root, spec, _environ):
        self.calls.append((executable, app_root, spec))
        count = self.counts.get(spec.study_id, 0)
        self.counts[spec.study_id] = count + 1
        root = app_root / "demo_studies" / "v1" / spec.study_id.value
        root.mkdir(parents=True, exist_ok=True)
        return DemoCaseObservation(count == 0, root)


def test_default_plan_is_stable_and_has_30_second_case_budget():
    plan = default_demo_smoke_plan()

    assert [item.case for item in plan] == [
        SmokeCase.CT_FIRST_GENERATION,
        SmokeCase.CT_CACHE_REOPEN,
        SmokeCase.MR_FIRST_GENERATION,
        SmokeCase.GEOMETRY_FIRST_GENERATION,
    ]
    assert all(item.timeout_seconds == DEFAULT_TIMEOUT_SECONDS for item in plan)
    assert [item.expected_generated for item in plan] == [True, False, True, True]


def test_demo_contract_uses_one_fresh_cache_and_a_new_ct_cache_request(tmp_path):
    pipeline = FakeDemoPipeline()
    cache_root = tmp_path / "fresh-cache"

    results = run_demo_smoke_cases(
        cache_root,
        timeout_seconds=7.5,
        profile=SMALL_PROFILE,
        ensure_demo=pipeline,
    )

    assert [item.status for item in results] == [SmokeStatus.PASSED] * 4
    assert [study_id for study_id, _timeout in pipeline.calls] == [
        DemoStudyId.CT_MULTIPHASE,
        DemoStudyId.CT_MULTIPHASE,
        DemoStudyId.MR_BRAIN,
        DemoStudyId.GEOMETRY_LAB,
    ]
    assert all(timeout == 7.5 for _study_id, timeout in pipeline.calls)
    assert cache_root.is_dir()


def test_packaged_contract_launches_each_demo_against_one_isolated_root(tmp_path):
    executable = tmp_path / "MedImager.exe"
    executable.write_bytes(b"test double")
    pipeline = FakePackagedDemoPipeline()
    app_root = tmp_path / "isolated-app-data"
    app_root.mkdir()

    results = run_packaged_demo_smoke_cases(
        executable,
        app_root,
        timeout_seconds=8.0,
        environ={OPT_IN_ENV: "1"},
        packaged_demo_probe=pipeline,
    )

    assert [item.status for item in results] == [SmokeStatus.PASSED] * 4
    assert [call[2].case for call in pipeline.calls] == [
        SmokeCase.CT_FIRST_GENERATION,
        SmokeCase.CT_CACHE_REOPEN,
        SmokeCase.MR_FIRST_GENERATION,
        SmokeCase.GEOMETRY_FIRST_GENERATION,
    ]
    assert all(call[0] == executable.resolve() for call in pipeline.calls)
    assert all(call[1] == app_root.resolve() for call in pipeline.calls)


def test_failed_ct_generation_skips_reopen_but_runs_independent_cases(tmp_path):
    pipeline = FakeDemoPipeline()

    def fail_ct_first(*args):
        if args[0] is DemoStudyId.CT_MULTIPHASE:
            raise TimeoutError("synthetic timeout")
        return pipeline(*args)

    results = run_demo_smoke_cases(
        tmp_path / "fresh-cache",
        profile=SMALL_PROFILE,
        ensure_demo=fail_ct_first,
    )

    assert [item.status for item in results] == [
        SmokeStatus.FAILED,
        SmokeStatus.SKIPPED,
        SmokeStatus.PASSED,
        SmokeStatus.PASSED,
    ]
    assert "prerequisite failed" in results[1].detail


def test_non_empty_cache_root_is_rejected_before_any_demo_call(tmp_path):
    cache_root = tmp_path / "not-fresh"
    cache_root.mkdir()
    (cache_root / "existing.txt").write_text("occupied", encoding="utf-8")
    pipeline = FakeDemoPipeline()

    with pytest.raises(ValueError, match="must be empty"):
        run_demo_smoke_cases(cache_root, ensure_demo=pipeline)

    assert pipeline.calls == []


def test_opt_in_gate_never_launches_or_generates_by_default(tmp_path):
    called = False

    def unexpected(*_args):
        nonlocal called
        called = True
        raise AssertionError("integration work must stay gated")

    report = run_opted_in_pyinstaller_smoke(
        executable=tmp_path / "MedImager.exe",
        app_data_root=tmp_path / "app-data",
        environ={},
        executable_probe=unexpected,
        ensure_demo=unexpected,
    )

    assert not report.opted_in
    assert not report.passed
    assert all(item.status is SmokeStatus.SKIPPED for item in report.cases)
    assert not called
    assert not (tmp_path / "app-data").exists()


def test_opted_in_orchestration_combines_boot_probe_and_four_demo_cases(tmp_path):
    executable = tmp_path / "MedImager.exe"
    executable.write_bytes(b"test double")
    pipeline = FakeDemoPipeline()
    probe_calls = []

    def probe(path, app_root, timeout, environ):
        probe_calls.append((path, app_root, timeout, environ[OPT_IN_ENV]))
        return ExecutableProbeObservation(True, "test probe")

    report = run_opted_in_pyinstaller_smoke(
        executable=executable,
        app_data_root=tmp_path / "fresh-app-data",
        timeout_seconds=9,
        profile=SMALL_PROFILE,
        environ={OPT_IN_ENV: "1"},
        executable_probe=probe,
        ensure_demo=pipeline,
    )

    assert report.opted_in
    assert report.passed
    assert [item.case for item in report.cases] == [
        SmokeCase.EXECUTABLE_BOOT,
        SmokeCase.CT_FIRST_GENERATION,
        SmokeCase.CT_CACHE_REOPEN,
        SmokeCase.MR_FIRST_GENERATION,
        SmokeCase.GEOMETRY_FIRST_GENERATION,
    ]
    assert probe_calls == [
        (executable.resolve(), (tmp_path / "fresh-app-data").resolve(), 9.0, "1")
    ]


def test_default_opted_in_path_uses_packaged_demo_probes(tmp_path):
    executable = tmp_path / "MedImager.exe"
    executable.write_bytes(b"test double")
    packaged = FakePackagedDemoPipeline()

    report = run_opted_in_pyinstaller_smoke(
        executable=executable,
        app_data_root=tmp_path / "fresh-app-data",
        timeout_seconds=6,
        environ={OPT_IN_ENV: "1"},
        executable_probe=lambda *_args: ExecutableProbeObservation(True, "booted"),
        packaged_demo_probe=packaged,
    )

    assert report.passed
    assert len(packaged.calls) == 4
    assert [item.case for item in report.cases[1:]] == [
        spec.case for spec in default_demo_smoke_plan(6)
    ]


def test_demo_service_smoke_marker_is_atomic_non_phi_and_manifest_validated(
    monkeypatch,
    tmp_path,
):
    app_root = tmp_path / "smoke-app-data"
    token = "ct-first-test-token"
    monkeypatch.setenv("MEDIMAGER_SMOKE_APP_DATA_ROOT", str(app_root))
    monkeypatch.setenv("MEDIMAGER_SMOKE_REQUEST_TOKEN", token)
    executor = ThreadPoolExecutor(max_workers=1)
    service = DemoStudyService(executor=executor, profile=SMALL_PROFILE)
    try:
        result = service.ensure_ready(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        marker_name = hashlib.sha256(token.encode()).hexdigest()[:24]
        marker = app_root / "smoke_results" / f"{marker_name}.json"
        deadline = time.monotonic() + 2
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)

        assert service.cache_root == app_root.resolve() / "demo_studies" / "v1"
        assert marker.is_file()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert set(payload) == {
            "schema_version",
            "request_token",
            "study_id",
            "generated",
            "manifest_digest",
        }
        assert "PatientName" not in marker.read_text(encoding="utf-8")
        observation = _read_packaged_demo_observation(
            marker,
            token=token,
            spec=default_demo_smoke_plan()[0],
            target=result.root,
        )
        assert observation.valid
        assert observation.generated
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_cli_reports_a_machine_readable_skip_without_opt_in(capsys):
    assert main(["--json"], environ={}) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["opted_in"] is False
    assert payload["passed"] is False
    assert {item["status"] for item in payload["cases"]} == {"skipped"}


class _FakeSmokeProcess:
    def __init__(self, *, pid: int = 4242, wait_timeouts: int = 0) -> None:
        self.pid = pid
        self.alive = True
        self.wait_timeouts = wait_timeouts
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[float] = []

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1
        self.alive = False

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self.wait_timeouts:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("MedImager.exe", timeout)
        self.alive = False
        return 0


def test_windows_cleanup_targets_only_the_launched_pid_tree(monkeypatch):
    process = _FakeSmokeProcess(pid=8675309)
    taskkill_calls = []

    def fake_taskkill(command, **kwargs):
        taskkill_calls.append((command, kwargs))
        process.alive = False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(smoke_module.sys, "platform", "win32")
    monkeypatch.setattr(smoke_module.subprocess, "run", fake_taskkill)

    _terminate_process(process, time.perf_counter() + 3.0)

    assert len(taskkill_calls) == 1
    command, options = taskkill_calls[0]
    assert command == ["taskkill.exe", "/PID", "8675309", "/T", "/F"]
    assert options["shell"] is False
    assert options["check"] is False
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_windows_cleanup_falls_back_if_taskkill_fails(monkeypatch):
    process = _FakeSmokeProcess()

    def fail_taskkill(*_args, **_kwargs):
        raise OSError("taskkill unavailable")

    monkeypatch.setattr(smoke_module.sys, "platform", "win32")
    monkeypatch.setattr(smoke_module.subprocess, "run", fail_taskkill)

    _terminate_process(process, time.perf_counter() + 1.0)

    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert not process.alive


def test_windows_cleanup_never_targets_a_pid_after_parent_exit(monkeypatch):
    process = _FakeSmokeProcess(pid=31337)
    process.alive = False

    def unexpected_taskkill(*_args, **_kwargs):
        raise AssertionError("an exited process PID may already have been recycled")

    monkeypatch.setattr(smoke_module.sys, "platform", "win32")
    monkeypatch.setattr(smoke_module.subprocess, "run", unexpected_taskkill)

    _terminate_process(process, time.perf_counter())

    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_cleanup_escalates_to_kill_after_fallback_timeout(monkeypatch):
    process = _FakeSmokeProcess(wait_timeouts=1)
    monkeypatch.setattr(smoke_module.sys, "platform", "linux")

    _terminate_process(process, time.perf_counter() + 1.0)

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert not process.alive


@pytest.mark.skipif(
    not smoke_opted_in(),
    reason=f"set {OPT_IN_ENV}=1 to run the packaged release smoke",
)
def test_opt_in_packaged_release_smoke(tmp_path):
    executable = os.environ.get(EXECUTABLE_ENV)
    if not executable:
        pytest.fail(f"{EXECUTABLE_ENV} must point to the packaged executable")

    report = run_opted_in_pyinstaller_smoke(
        executable=executable,
        app_data_root=tmp_path / "fresh-app-data",
    )

    assert report.passed, report.to_dict()
