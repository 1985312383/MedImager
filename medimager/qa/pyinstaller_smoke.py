"""Opt-in PyInstaller and deterministic-demo release smoke checks.

The release contract is intentionally end-to-end: after a fresh-data boot
probe, the packaged executable itself is launched with ``--demo`` for CT first
generation, CT cache reopen, MR, and Geometry Lab.  Each process publishes an
atomic, non-PHI completion handshake and this driver independently validates
the generated manifest before terminating the GUI.

Real executable execution is gated by ``MEDIMAGER_RUN_PYINSTALLER_SMOKE=1``.
Ordinary pytest runs can safely import and test the orchestration without
launching a GUI or generating production-size studies.  The in-process timeout
is cooperative: a timed-out generator is cancelled, but Python cannot forcibly
kill its worker thread.  The generator checks cancellation between instances,
so shutdown is normally prompt while preserving staging-directory safety.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from medimager.demo import (
    DemoGenerationProfile,
    DemoStudyId,
    DemoStudyService,
    get_demo_study_spec,
    validate_demo_study,
)
from medimager.demo.generator import PRODUCTION_PROFILE


OPT_IN_ENV = "MEDIMAGER_RUN_PYINSTALLER_SMOKE"
EXECUTABLE_ENV = "MEDIMAGER_PYINSTALLER_EXE"
SMOKE_APP_DATA_ENV = "MEDIMAGER_SMOKE_APP_DATA_ROOT"
SMOKE_REQUEST_TOKEN_ENV = "MEDIMAGER_SMOKE_REQUEST_TOKEN"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_BOOT_OBSERVATION_SECONDS = 2.0


class SmokeCase(StrEnum):
    EXECUTABLE_BOOT = "executable_boot"
    CT_FIRST_GENERATION = "ct_first_generation"
    CT_CACHE_REOPEN = "ct_cache_reopen"
    MR_FIRST_GENERATION = "mr_first_generation"
    GEOMETRY_FIRST_GENERATION = "geometry_first_generation"


class SmokeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SmokeCaseSpec:
    case: SmokeCase
    study_id: DemoStudyId
    expected_generated: bool
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    prerequisite: SmokeCase | None = None


@dataclass(frozen=True)
class SmokeCaseResult:
    case: SmokeCase
    status: SmokeStatus
    duration_seconds: float
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status is SmokeStatus.PASSED


@dataclass(frozen=True)
class ExecutableProbeObservation:
    success: bool
    detail: str = ""


@dataclass(frozen=True)
class DemoCaseObservation:
    generated: bool
    root: Path
    valid: bool = True
    detail: str = ""


@dataclass(frozen=True)
class SmokeReport:
    opted_in: bool
    app_data_root: Path | None
    executable: Path | None
    cases: tuple[SmokeCaseResult, ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return self.opted_in and bool(self.cases) and all(
            result.passed for result in self.cases
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "opted_in": self.opted_in,
            "passed": self.passed,
            "app_data_root": (
                str(self.app_data_root) if self.app_data_root is not None else None
            ),
            "executable": str(self.executable) if self.executable is not None else None,
            "cases": [
                {
                    **asdict(result),
                    "case": result.case.value,
                    "status": result.status.value,
                }
                for result in self.cases
            ],
        }


DemoEnsure = Callable[
    [DemoStudyId, Path, DemoGenerationProfile, float], DemoCaseObservation
]
ExecutableProbe = Callable[
    [Path, Path, float, Mapping[str, str]], ExecutableProbeObservation
]
PackagedDemoProbe = Callable[
    [Path, Path, SmokeCaseSpec, Mapping[str, str]], DemoCaseObservation
]


def default_demo_smoke_plan(
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[SmokeCaseSpec, ...]:
    """Return the stable v2.6 demo order and per-case expectations."""

    timeout = _positive_timeout(timeout_seconds)
    return (
        SmokeCaseSpec(
            SmokeCase.CT_FIRST_GENERATION,
            DemoStudyId.CT_MULTIPHASE,
            True,
            timeout,
        ),
        SmokeCaseSpec(
            SmokeCase.CT_CACHE_REOPEN,
            DemoStudyId.CT_MULTIPHASE,
            False,
            timeout,
            SmokeCase.CT_FIRST_GENERATION,
        ),
        SmokeCaseSpec(
            SmokeCase.MR_FIRST_GENERATION,
            DemoStudyId.MR_BRAIN,
            True,
            timeout,
        ),
        SmokeCaseSpec(
            SmokeCase.GEOMETRY_FIRST_GENERATION,
            DemoStudyId.GEOMETRY_LAB,
            True,
            timeout,
        ),
    )


def smoke_opted_in(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the destructive/GUI integration smoke was requested."""

    source = os.environ if environ is None else environ
    return str(source.get(OPT_IN_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def probe_packaged_executable(
    executable: Path,
    app_data_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
    *,
    observation_seconds: float = DEFAULT_BOOT_OBSERVATION_SECONDS,
) -> ExecutableProbeObservation:
    """Verify that a packaged GUI process boots and remains alive briefly.

    The process is always terminated by the probe.  Output is discarded so a
    release smoke log cannot accidentally collect clinical paths or metadata.
    """

    timeout = _positive_timeout(timeout_seconds)
    observation = _positive_timeout(observation_seconds)
    if observation >= timeout:
        raise ValueError("observation_seconds must be smaller than timeout_seconds")
    executable = Path(executable).resolve()
    if not executable.is_file():
        return ExecutableProbeObservation(False, "executable does not exist")

    process_env = dict(os.environ if environ is None else environ)
    process_env["LOCALAPPDATA"] = str(Path(app_data_root).resolve())
    process_env[SMOKE_APP_DATA_ENV] = str(Path(app_data_root).resolve())
    started = time.perf_counter()
    try:
        process = subprocess.Popen(  # noqa: S603 - explicit release artifact path
            [str(executable)],
            cwd=str(executable.parent),
            env=process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as error:
        return ExecutableProbeObservation(
            False,
            f"launch failed: {type(error).__name__}",
        )

    success = False
    detail = ""
    observation_deadline = started + observation
    timeout_deadline = started + timeout
    try:
        while time.perf_counter() < observation_deadline:
            return_code = process.poll()
            if return_code is not None:
                detail = f"process exited during boot with code {return_code}"
                break
            if time.perf_counter() >= timeout_deadline:
                detail = "boot observation timed out"
                break
            time.sleep(0.05)
        else:
            success = process.poll() is None
            detail = "process remained alive for the boot observation window"
    finally:
        _terminate_process(process, timeout_deadline)
    return ExecutableProbeObservation(success, detail)


def probe_packaged_demo(
    executable: Path,
    app_data_root: Path,
    spec: SmokeCaseSpec,
    environ: Mapping[str, str] | None = None,
) -> DemoCaseObservation:
    """Run one demo through the packaged GUI and validate its cache artifact."""

    timeout = _positive_timeout(spec.timeout_seconds)
    executable = Path(executable).resolve()
    root = Path(app_data_root).resolve()
    target = root / "demo_studies" / "v1" / spec.study_id.value
    if not executable.is_file():
        return DemoCaseObservation(False, target, False, "executable does not exist")

    token = f"{spec.case.value}-{uuid.uuid4().hex}"
    marker = _smoke_marker_path(root, token)
    marker.unlink(missing_ok=True)
    process_env = dict(os.environ if environ is None else environ)
    process_env["LOCALAPPDATA"] = str(root)
    process_env[SMOKE_APP_DATA_ENV] = str(root)
    process_env[SMOKE_REQUEST_TOKEN_ENV] = token
    started = time.perf_counter()
    try:
        process = subprocess.Popen(  # noqa: S603 - explicit release artifact path
            [str(executable), "--demo", spec.study_id.value],
            cwd=str(executable.parent),
            env=process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as error:
        return DemoCaseObservation(
            False,
            target,
            False,
            f"launch failed: {type(error).__name__}",
        )

    deadline = started + timeout
    observation = DemoCaseObservation(False, target, False, "demo process timed out")
    try:
        while time.perf_counter() < deadline:
            if marker.is_file():
                observation = _read_packaged_demo_observation(
                    marker,
                    token=token,
                    spec=spec,
                    target=target,
                )
                break
            return_code = process.poll()
            if return_code is not None:
                observation = DemoCaseObservation(
                    False,
                    target,
                    False,
                    f"process exited before demo completion with code {return_code}",
                )
                break
            time.sleep(0.05)
    finally:
        _terminate_process(process, deadline)
    return observation


def ensure_demo_once(
    study_id: DemoStudyId,
    cache_root: Path,
    profile: DemoGenerationProfile = PRODUCTION_PROFILE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> DemoCaseObservation:
    """Run one demo request through a newly constructed production service."""

    timeout = _positive_timeout(timeout_seconds)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-smoke")
    service = DemoStudyService(cache_root, executor=executor, profile=profile)
    timed_out = False
    try:
        future = service.ensure_ready(study_id)
        try:
            result = future.result(timeout=timeout)
        except FutureTimeout as error:
            timed_out = True
            service.cancel(study_id)
            raise TimeoutError(
                f"demo case exceeded {timeout:.1f} seconds"
            ) from error
        return DemoCaseObservation(
            generated=result.generated,
            root=result.root,
            valid=result.root.is_dir() and result.manifest.study_id is study_id,
        )
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=True)


def run_demo_smoke_cases(
    cache_root: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    profile: DemoGenerationProfile = PRODUCTION_PROFILE,
    ensure_demo: DemoEnsure = ensure_demo_once,
) -> tuple[SmokeCaseResult, ...]:
    """Execute the four demo cases against an initially empty cache root."""

    cache_root = Path(cache_root).resolve()
    _prepare_fresh_directory(cache_root)
    results: list[SmokeCaseResult] = []
    by_case: dict[SmokeCase, SmokeCaseResult] = {}
    for spec in default_demo_smoke_plan(timeout_seconds):
        if spec.prerequisite is not None and not by_case[spec.prerequisite].passed:
            result = SmokeCaseResult(
                spec.case,
                SmokeStatus.SKIPPED,
                0.0,
                f"prerequisite failed: {spec.prerequisite.value}",
            )
            results.append(result)
            by_case[spec.case] = result
            continue

        started = time.perf_counter()
        try:
            observation = ensure_demo(
                spec.study_id,
                cache_root,
                profile,
                spec.timeout_seconds,
            )
            status, detail = _evaluate_demo_observation(
                observation,
                cache_root,
                spec.expected_generated,
            )
        except Exception as error:  # release boundary: report every case
            status = SmokeStatus.FAILED
            detail = _exception_detail(error)
        result = SmokeCaseResult(
            spec.case,
            status,
            time.perf_counter() - started,
            detail,
        )
        results.append(result)
        by_case[spec.case] = result
    return tuple(results)


def run_packaged_demo_smoke_cases(
    executable: Path,
    app_data_root: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
    packaged_demo_probe: PackagedDemoProbe = probe_packaged_demo,
) -> tuple[SmokeCaseResult, ...]:
    """Run all demo cases through separate packaged GUI processes."""

    executable = Path(executable).resolve()
    root = Path(app_data_root).resolve()
    cache_root = (root / "demo_studies" / "v1").resolve()
    if cache_root.exists() and any(cache_root.iterdir()):
        raise ValueError("packaged demo cache must be empty before the first case")

    results: list[SmokeCaseResult] = []
    by_case: dict[SmokeCase, SmokeCaseResult] = {}
    effective_env = dict(os.environ if environ is None else environ)
    for spec in default_demo_smoke_plan(timeout_seconds):
        if spec.prerequisite is not None and not by_case[spec.prerequisite].passed:
            result = SmokeCaseResult(
                spec.case,
                SmokeStatus.SKIPPED,
                0.0,
                f"prerequisite failed: {spec.prerequisite.value}",
            )
            results.append(result)
            by_case[spec.case] = result
            continue
        started = time.perf_counter()
        try:
            observation = packaged_demo_probe(executable, root, spec, effective_env)
            status, detail = _evaluate_demo_observation(
                observation,
                cache_root,
                spec.expected_generated,
            )
        except Exception as error:  # release boundary: report every case
            status = SmokeStatus.FAILED
            detail = _exception_detail(error)
        result = SmokeCaseResult(
            spec.case,
            status,
            time.perf_counter() - started,
            detail,
        )
        results.append(result)
        by_case[spec.case] = result
    return tuple(results)


def run_opted_in_pyinstaller_smoke(
    *,
    executable: str | Path | None = None,
    app_data_root: str | Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    profile: DemoGenerationProfile = PRODUCTION_PROFILE,
    environ: Mapping[str, str] | None = None,
    executable_probe: ExecutableProbe = probe_packaged_executable,
    ensure_demo: DemoEnsure | None = None,
    packaged_demo_probe: PackagedDemoProbe = probe_packaged_demo,
) -> SmokeReport:
    """Run the release smoke only when the environment explicitly opts in."""

    effective_env = dict(os.environ if environ is None else environ)
    executable_path = _resolve_executable(executable, effective_env)
    if not smoke_opted_in(effective_env):
        skipped = tuple(
            SmokeCaseResult(case, SmokeStatus.SKIPPED, 0.0, "opt-in not enabled")
            for case in (SmokeCase.EXECUTABLE_BOOT,)
            + tuple(spec.case for spec in default_demo_smoke_plan(timeout_seconds))
        )
        return SmokeReport(
            False,
            Path(app_data_root).resolve() if app_data_root is not None else None,
            executable_path,
            skipped,
        )

    root = (
        Path(app_data_root).resolve()
        if app_data_root is not None
        else Path(tempfile.mkdtemp(prefix="medimager-v26-smoke-")).resolve()
    )
    _prepare_fresh_directory(root)
    started = time.perf_counter()
    if executable_path is None:
        probe_result = SmokeCaseResult(
            SmokeCase.EXECUTABLE_BOOT,
            SmokeStatus.FAILED,
            0.0,
            f"set --executable or {EXECUTABLE_ENV}",
        )
    else:
        try:
            observation = executable_probe(
                executable_path,
                root,
                _positive_timeout(timeout_seconds),
                effective_env,
            )
            probe_result = SmokeCaseResult(
                SmokeCase.EXECUTABLE_BOOT,
                SmokeStatus.PASSED if observation.success else SmokeStatus.FAILED,
                time.perf_counter() - started,
                observation.detail,
            )
        except Exception as error:  # release boundary
            probe_result = SmokeCaseResult(
                SmokeCase.EXECUTABLE_BOOT,
                SmokeStatus.FAILED,
                time.perf_counter() - started,
                _exception_detail(error),
            )

    if ensure_demo is not None:
        # Injectable in-process pipeline retained for fast orchestration unit
        # tests.  Release runs intentionally take the packaged branch below.
        demo_results = run_demo_smoke_cases(
            root / "demo_studies" / "v1",
            timeout_seconds=timeout_seconds,
            profile=profile,
            ensure_demo=ensure_demo,
        )
    elif executable_path is None:
        demo_results = tuple(
            SmokeCaseResult(
                spec.case,
                SmokeStatus.SKIPPED,
                0.0,
                "packaged executable is unavailable",
            )
            for spec in default_demo_smoke_plan(timeout_seconds)
        )
    else:
        demo_results = run_packaged_demo_smoke_cases(
            executable_path,
            root,
            timeout_seconds=timeout_seconds,
            environ=effective_env,
            packaged_demo_probe=packaged_demo_probe,
        )
    return SmokeReport(
        True,
        root,
        executable_path,
        (probe_result, *demo_results),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """CLI entry point for release machines and CI jobs."""

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--app-data-root", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)
    report = run_opted_in_pyinstaller_smoke(
        executable=arguments.executable,
        app_data_root=arguments.app_data_root,
        timeout_seconds=arguments.timeout,
        environ=environ,
    )
    if arguments.as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        state = "PASSED" if report.passed else "SKIPPED" if not report.opted_in else "FAILED"
        print(f"MedImager v2.6 PyInstaller smoke: {state}")
        for result in report.cases:
            print(
                f"  {result.case.value}: {result.status.value} "
                f"({result.duration_seconds:.3f}s) {result.detail}".rstrip()
            )
    if not report.opted_in:
        return 0
    return 0 if report.passed else 1


def _resolve_executable(
    explicit: str | Path | None,
    environ: Mapping[str, str],
) -> Path | None:
    value = explicit if explicit is not None else environ.get(EXECUTABLE_ENV)
    if value is None or not str(value).strip():
        return None
    return Path(value).resolve()


def _positive_timeout(value: float) -> float:
    timeout = float(value)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    return timeout


def _prepare_fresh_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError("fresh root must be a directory")
        if any(path.iterdir()):
            raise ValueError("fresh root must be empty")
    else:
        path.mkdir(parents=True, exist_ok=False)


def _smoke_marker_path(root: Path, token: str) -> Path:
    name = hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()[:24]
    return root / "smoke_results" / f"{name}.json"


def _read_packaged_demo_observation(
    marker: Path,
    *,
    token: str,
    spec: SmokeCaseSpec,
    target: Path,
) -> DemoCaseObservation:
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported smoke marker")
        if payload.get("request_token") != token:
            raise ValueError("smoke marker token mismatch")
        if payload.get("study_id") != spec.study_id.value:
            raise ValueError("smoke marker study mismatch")
        generated = payload.get("generated")
        if not isinstance(generated, bool):
            raise ValueError("smoke marker generation state is invalid")
        validation = validate_demo_study(target, get_demo_study_spec(spec.study_id))
        if not validation.valid or validation.manifest is None:
            return DemoCaseObservation(
                generated,
                target,
                False,
                f"manifest validation failed: {validation.reason}",
            )
        if payload.get("manifest_digest") != validation.manifest.semantic_digest:
            return DemoCaseObservation(
                generated,
                target,
                False,
                "smoke marker manifest digest mismatch",
            )
        return DemoCaseObservation(
            generated,
            target,
            True,
            "packaged demo completed and manifest was validated",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        return DemoCaseObservation(
            False,
            target,
            False,
            f"invalid smoke marker: {type(error).__name__}",
        )


def _terminate_process(process: subprocess.Popen, deadline: float) -> None:
    """Stop exactly the process launched by the smoke and its Windows children.

    A PyInstaller one-file executable keeps a bootloader parent while the real
    GUI runs as its child.  ``Popen.terminate()`` only stops that parent on
    Windows and can therefore orphan the GUI.  ``taskkill /T`` is scoped to
    the concrete PID returned by ``Popen`` and terminates that process tree.
    Other MedImager processes are never selected by image name.
    """

    if process.poll() is not None:
        return

    # Cleanup gets a small independent grace window even when the case itself
    # consumed its whole budget; otherwise a timeout could immediately abort
    # taskkill and recreate the orphan we are trying to prevent.
    remaining = max(2.0, min(5.0, deadline - time.perf_counter()))
    if sys.platform.startswith("win") and _terminate_windows_process_tree(
        process,
        remaining,
    ):
        return

    _terminate_single_process(process, remaining)


def _terminate_windows_process_tree(
    process: subprocess.Popen,
    remaining: float,
) -> bool:
    """Terminate one Windows PID tree, returning whether the parent exited."""

    timeout = max(0.1, min(5.0, remaining))
    try:
        subprocess.run(  # noqa: S603,S607 - fixed OS utility and exact child PID
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return process.poll() is not None
    return True


def _terminate_single_process(
    process: subprocess.Popen,
    remaining: float,
) -> None:
    """Best-effort cross-platform fallback when tree termination is unavailable."""

    try:
        process.terminate()
    except OSError:
        if process.poll() is not None:
            return
    try:
        process.wait(timeout=max(0.1, remaining))
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except OSError:
        if process.poll() is not None:
            return
    process.wait(timeout=2.0)


def _evaluate_demo_observation(
    observation: DemoCaseObservation,
    cache_root: Path,
    expected_generated: bool,
) -> tuple[SmokeStatus, str]:
    if not observation.valid:
        return SmokeStatus.FAILED, observation.detail or "demo validation failed"
    try:
        resolved_root = observation.root.resolve()
    except OSError:
        return SmokeStatus.FAILED, "demo result root could not be resolved"
    if cache_root != resolved_root and cache_root not in resolved_root.parents:
        return SmokeStatus.FAILED, "demo result escaped the smoke cache root"
    if observation.generated is not expected_generated:
        expectation = "generation" if expected_generated else "cache reuse"
        return SmokeStatus.FAILED, f"expected {expectation}"
    return SmokeStatus.PASSED, observation.detail


def _exception_detail(error: Exception) -> str:
    message = str(error).strip()
    return type(error).__name__ if not message else f"{type(error).__name__}: {message}"


if __name__ == "__main__":
    raise SystemExit(main())
