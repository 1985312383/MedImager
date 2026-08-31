"""MedImager v2.6 end-to-end release performance baseline.

The stable API is :func:`run_v26_release_baseline`; the command-line entry is
``python -m medimager.performance.v26_release``.  Production mode exercises
all three deterministic example studies.  Quick mode follows the identical
pipeline with smaller synthetic dimensions and is intended for offline CI.

Durations are comparable only on the same host and build configuration.  The
companion :func:`compare_release_baselines` helper applies the v2.6 policy:
lower-is-better duration, memory, and heartbeat metrics regress when they
exceed the recorded baseline by more than 20 percent.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import tempfile
import time
import tracemalloc
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pydicom
from PySide6.QtCore import QCoreApplication

from medimager.app_info import get_version
from medimager.core.image_data_model import ImageDataModel
from medimager.core.local_source import (
    LocalOpenOrigin,
    LocalOpenRequest,
    LocalSeriesSource,
    LocalSourceKind,
    index_dicom_folder,
)
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.sync_manager import SyncGroup, SyncManager, SyncMode
from medimager.core.volume_geometry import (
    MprPlane,
    OrthogonalMprResampler,
    VolumeBuilder,
)
from medimager.demo import (
    DemoGenerationProfile,
    DemoStudyId,
    DemoStudyService,
    generate_demo_study,
    get_demo_study_spec,
)
from medimager.demo.manifest import DemoStudyManifest
from medimager.qa.visual_regression import GuiHeartbeatProbe


SCHEMA = "medimager.performance.v26_release"
SCHEMA_VERSION = 1
BASELINE_VERSION = "2.6"
DEFAULT_RELATIVE_LIMIT = 1.20
DEFAULT_HEARTBEAT_TARGET_MS = 100.0

QUICK_PROFILE = DemoGenerationProfile(
    ct_shape_zyx=(3, 12, 12),
    ct_coronal_slices=3,
    mr_shape_zyx=(3, 12, 12),
    geometry_shape_zyx=(3, 12, 12),
    random_seed=260,
)


@dataclass(frozen=True)
class RegressionMetric:
    """One numeric JSON path governed by the relative regression policy."""

    path: str
    lower_is_better: bool = True


DEFAULT_REGRESSION_METRICS = (
    RegressionMetric("benchmarks.demo_generation.total_ms"),
    RegressionMetric("benchmarks.demo_generation.python_peak_mb"),
    RegressionMetric("benchmarks.folder_scan.total_ms"),
    RegressionMetric("benchmarks.series_readiness_proxy.first_series_ms"),
    RegressionMetric("benchmarks.series_readiness_proxy.all_series_ms"),
    RegressionMetric("benchmarks.cache_second_open.total_ms"),
    RegressionMetric("benchmarks.mpr.volume_build_ms"),
    RegressionMetric("benchmarks.mpr.first_frame_ms"),
    RegressionMetric("benchmarks.mpr.interaction_p95_ms"),
    RegressionMetric("benchmarks.sync_interaction.p95_ms"),
    RegressionMetric("benchmarks.gui_heartbeat.max_gap_ms"),
)


@dataclass(frozen=True)
class RegressionFinding:
    metric: str
    baseline: float | None
    current: float | None
    ratio: float | None
    limit: float
    status: str

    @property
    def is_regression(self) -> bool:
        return self.status == "regression"


@dataclass(frozen=True)
class RegressionReport:
    relative_limit: float
    findings: tuple[RegressionFinding, ...]

    @property
    def comparable(self) -> bool:
        return all(item.status != "missing" for item in self.findings)

    @property
    def regressions(self) -> tuple[RegressionFinding, ...]:
        return tuple(item for item in self.findings if item.is_regression)

    @property
    def passed(self) -> bool:
        return self.comparable and not self.regressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_limit": self.relative_limit,
            "comparable": self.comparable,
            "passed": self.passed,
            "regression_count": len(self.regressions),
            "findings": [asdict(item) for item in self.findings],
        }


def compare_release_baselines(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    relative_limit: float = DEFAULT_RELATIVE_LIMIT,
    metrics: Iterable[RegressionMetric] = DEFAULT_REGRESSION_METRICS,
) -> RegressionReport:
    """Compare two v2.6 baseline documents using a same-host relative limit."""

    _validate_document(current)
    _validate_document(baseline)
    if not np.isfinite(relative_limit) or relative_limit < 1.0:
        raise ValueError("relative_limit must be finite and at least 1.0")

    findings: list[RegressionFinding] = []
    for metric in tuple(metrics):
        before = _numeric_path(baseline, metric.path)
        after = _numeric_path(current, metric.path)
        if before is None or after is None:
            findings.append(
                RegressionFinding(
                    metric.path,
                    before,
                    after,
                    None,
                    relative_limit,
                    "missing",
                )
            )
            continue
        if before == 0.0:
            ratio = 1.0 if after == 0.0 else float("inf")
        else:
            ratio = after / before
        regressed = (
            ratio > relative_limit
            if metric.lower_is_better
            else ratio < (1.0 / relative_limit)
        )
        findings.append(
            RegressionFinding(
                metric.path,
                before,
                after,
                ratio,
                relative_limit,
                "regression" if regressed else "ok",
            )
        )
    return RegressionReport(relative_limit, tuple(findings))


def run_v26_release_baseline(
    *,
    profile: DemoGenerationProfile | None = None,
    study_ids: Sequence[DemoStudyId | str] = tuple(DemoStudyId),
    sync_samples: int = 24,
    timeout_seconds: float = 30.0,
    heartbeat_interval_ms: int = 10,
    output_path: str | Path | None = None,
    work_parent: str | Path | None = None,
    event_app: QCoreApplication | None = None,
) -> dict[str, Any]:
    """Run the v2.6 example-to-reading pipeline and return a JSON document.

    ``profile=None`` selects production dimensions.  Tests should pass
    :data:`QUICK_PROFILE`.  Temporary DICOM pixels are removed before return;
    only aggregate, non-PHI measurements are serialized.
    """

    selected_profile = profile or DemoGenerationProfile()
    selected_profile.validate()
    normalized_ids = tuple(DemoStudyId(value) for value in study_ids)
    if not normalized_ids:
        raise ValueError("study_ids must not be empty")
    if DemoStudyId.CT_MULTIPHASE not in normalized_ids:
        raise ValueError("CT Multiphase is required for scan, MPR, and sync metrics")
    if sync_samples < 2:
        raise ValueError("sync_samples must be at least 2")
    if not np.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")

    app = event_app or QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(["medimager-v26-release-benchmark"])
    probe = GuiHeartbeatProbe(interval_ms=heartbeat_interval_ms)
    probe.start()
    _arm_heartbeat_probe(
        probe,
        app,
        timeout_seconds=min(timeout_seconds, 1.0),
    )

    parent = Path(work_parent) if work_parent is not None else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    temp_context = tempfile.TemporaryDirectory(
        prefix="medimager_v26_release_",
        dir=str(parent) if parent is not None else None,
    )
    generation_peak_bytes = 0
    try:
        with temp_context as temporary, ThreadPoolExecutor(max_workers=4) as executor:
            work = Path(temporary)
            service = DemoStudyService(
                work / "cache",
                executor=executor,
                profile=selected_profile,
            )
            build_results: dict[DemoStudyId, Any] = {}
            generation_runs: dict[str, float] = {}

            tracemalloc.start()
            try:
                for study_id in normalized_ids:
                    elapsed_ms, build = _measure_future(
                        service.ensure_ready(study_id),
                        app,
                        timeout_seconds,
                    )
                    if not build.generated:
                        raise RuntimeError(f"Expected a fresh generation for {study_id.value}")
                    build_results[study_id] = build
                    generation_runs[study_id.value] = elapsed_ms
                _, generation_peak_bytes = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            ct_build = build_results[DemoStudyId.CT_MULTIPHASE]
            deterministic_path = work / "determinism_ct"
            determinism_ms, deterministic_manifest = _measure_future(
                executor.submit(
                    generate_demo_study,
                    get_demo_study_spec(DemoStudyId.CT_MULTIPHASE),
                    deterministic_path,
                    profile=selected_profile,
                ),
                app,
                timeout_seconds,
            )
            deterministic = _manifest_signature(ct_build.manifest) == _manifest_signature(
                deterministic_manifest
            )
            if not deterministic:
                raise RuntimeError("CT example generation was not deterministic")

            # Reopen through a new service so this measures manifest validation
            # and disk-cache reuse, not the first service's memoized Future.
            reopen_service = DemoStudyService(
                work / "cache",
                executor=executor,
                profile=selected_profile,
            )
            cache_ms, cached_build = _measure_future(
                reopen_service.ensure_ready(DemoStudyId.CT_MULTIPHASE),
                app,
                timeout_seconds,
            )
            if cached_build.generated:
                raise RuntimeError("Second CT open unexpectedly regenerated the cache")

            request = LocalOpenRequest.create(
                LocalSourceKind.FOLDER,
                ct_build.root,
                origin=LocalOpenOrigin.SAMPLE,
            )
            scan_ms, index_result = _measure_future(
                executor.submit(index_dicom_folder, request),
                app,
                timeout_seconds,
            )
            if index_result.has_fatal_issue or not index_result.studies:
                raise RuntimeError("Generated CT example could not be indexed")
            series_sources = tuple(
                series
                for study in index_result.studies
                for series in study.series
            )
            readiness = _measure_series_readiness(
                series_sources,
                executor,
                app,
                timeout_seconds,
            )
            models: dict[str, ImageDataModel] = readiness.pop("models")

            phase_sources = tuple(
                item
                for item in series_sources
                if item.modality.upper() == "CT"
                and item.orientation == "axial"
                and item.slice_count > 1
                and item.series_instance_uid in models
            )
            if len(phase_sources) < 2:
                raise RuntimeError("CT example did not provide two compatible axial phases")

            active_source = phase_sources[0]
            active_model = models[active_source.series_instance_uid]
            mpr_build_ms, volume_result = _measure_future(
                executor.submit(VolumeBuilder.build, active_model),
                app,
                timeout_seconds,
            )
            if not volume_result.compatible or volume_result.volume is None:
                raise RuntimeError(f"CT example is not MPR compatible: {volume_result.detail}")
            resampler = OrthogonalMprResampler(volume_result.volume)
            cursor = np.asarray(volume_result.volume.geometry.center_lps, dtype=np.float64)
            mpr_first_ms, _ = _time_call(
                lambda: resampler.reconstruct(MprPlane.AXIAL, cursor)
            )
            mpr_runs: list[float] = []
            z_bounds = volume_result.volume.geometry.patient_bounds[2]
            for position in np.linspace(z_bounds[0], z_bounds[1], sync_samples):
                current = cursor.copy()
                current[2] = float(position)
                elapsed_ms, _ = _time_call(
                    lambda point=current: resampler.reconstruct(MprPlane.AXIAL, point)
                )
                mpr_runs.append(elapsed_ms)
                app.processEvents()

            sync_runs = _measure_sync_interaction(
                phase_sources[:2],
                models,
                samples=sync_samples,
                event_app=app,
            )

            # Let the timer observe the final synchronous interaction gap.
            time.sleep(max(0.001, heartbeat_interval_ms / 1000.0 * 1.2))
            app.processEvents()
            heartbeat_max_ms = probe.stop()

            generation_values = list(generation_runs.values())
            result = {
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "environment": _environment_info(),
                "profile": selected_profile.to_dict(),
                "studies": [item.value for item in normalized_ids],
                "benchmarks": {
                    "demo_generation": {
                        "studies_ms": {
                            key: _round_ms(value)
                            for key, value in generation_runs.items()
                        },
                        "total_ms": _round_ms(sum(generation_values)),
                        "determinism_check_ms": _round_ms(determinism_ms),
                        "deterministic": deterministic,
                        "semantic_digest": ct_build.manifest.semantic_digest,
                        "python_peak_mb": round(
                            generation_peak_bytes / (1024 * 1024), 3
                        ),
                    },
                    "folder_scan": {
                        "total_ms": _round_ms(scan_ms),
                        "candidate_count": index_result.candidate_count,
                        "study_count": len(index_result.studies),
                        "series_count": len(series_sources),
                    },
                    "series_readiness_proxy": readiness,
                    "cache_second_open": {
                        "total_ms": _round_ms(cache_ms),
                        "cache_hit": not cached_build.generated,
                        "new_service_instance": True,
                    },
                    "mpr": {
                        "volume_build_ms": _round_ms(mpr_build_ms),
                        "first_frame_ms": _round_ms(mpr_first_ms),
                        "interaction_p95_ms": _percentile(mpr_runs, 95),
                        "interaction_runs_ms": [_round_ms(value) for value in mpr_runs],
                        "estimated_volume_mb": round(
                            volume_result.estimated_bytes / (1024 * 1024), 3
                        ),
                    },
                    "sync_interaction": {
                        "p95_ms": _percentile(sync_runs, 95),
                        "runs_ms": [_round_ms(value) for value in sync_runs],
                        "samples": len(sync_runs),
                    },
                    "gui_heartbeat": {
                        "max_gap_ms": _round_ms(heartbeat_max_ms),
                        "sample_count": probe.sample_count,
                        "target_ms": DEFAULT_HEARTBEAT_TARGET_MS,
                        "within_target": heartbeat_max_ms
                        < DEFAULT_HEARTBEAT_TARGET_MS,
                    },
                },
                "regression_policy": {
                    "baseline_version": BASELINE_VERSION,
                    "relative_limit": DEFAULT_RELATIVE_LIMIT,
                    "same_host_only": True,
                    "metric_paths": [
                        item.path for item in DEFAULT_REGRESSION_METRICS
                    ],
                },
            }
    except Exception:
        probe.stop()
        raise

    if output_path is not None:
        _atomic_write_json(Path(output_path), result)
    return result


def load_release_baseline(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Performance baseline must be a JSON object")
    _validate_document(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("production", "quick"),
        default="production",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("performance_baseline_v2.6.json"),
    )
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--sync-samples", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    profile = QUICK_PROFILE if args.profile == "quick" else None
    result = run_v26_release_baseline(
        profile=profile,
        sync_samples=args.sync_samples,
        timeout_seconds=args.timeout,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.baseline is None:
        return 0
    report = compare_release_baselines(result, load_release_baseline(args.baseline))
    report_payload = report.to_dict()
    print(json.dumps(report_payload, ensure_ascii=False, indent=2))
    if args.comparison_output is not None:
        _atomic_write_json(args.comparison_output, report_payload)
    return 0 if report.passed else 2


def _measure_future(
    future: Future[Any],
    app: QCoreApplication,
    timeout_seconds: float,
) -> tuple[float, Any]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    while not future.done():
        if time.perf_counter() >= deadline:
            future.cancel()
            raise TimeoutError(f"Benchmark stage exceeded {timeout_seconds:.1f}s")
        app.processEvents()
        time.sleep(0.001)
    result = future.result()
    app.processEvents()
    return (time.perf_counter() - started) * 1000.0, result


def _arm_heartbeat_probe(
    probe: GuiHeartbeatProbe,
    app: QCoreApplication,
    *,
    timeout_seconds: float,
) -> None:
    """Wait for the timer's first delivered tick before measuring workload gaps."""

    deadline = time.perf_counter() + timeout_seconds
    while not probe.is_armed:
        if time.perf_counter() >= deadline:
            probe.stop()
            raise TimeoutError("GUI heartbeat probe did not receive its first timer tick")
        app.processEvents()
        time.sleep(0.001)


def _measure_series_readiness(
    sources: Sequence[LocalSeriesSource],
    executor: ThreadPoolExecutor,
    app: QCoreApplication,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    futures = {
        executor.submit(_load_series, source.file_paths): source
        for source in sources
    }
    pending = set(futures)
    models: dict[str, ImageDataModel] = {}
    first_series_ms: float | None = None
    while pending:
        if time.perf_counter() >= deadline:
            for future in pending:
                future.cancel()
            raise TimeoutError(
                f"Series readiness proxy exceeded {timeout_seconds:.1f}s"
            )
        completed = tuple(future for future in pending if future.done())
        if not completed:
            app.processEvents()
            time.sleep(0.001)
            continue
        for future in completed:
            pending.remove(future)
            source = futures[future]
            model = future.result()
            models[source.series_instance_uid] = model
            if first_series_ms is None:
                first_series_ms = (time.perf_counter() - started) * 1000.0
        app.processEvents()
    all_series_ms = (time.perf_counter() - started) * 1000.0
    return {
        "first_series_ms": _round_ms(first_series_ms or all_series_ms),
        "all_series_ms": _round_ms(all_series_ms),
        "successful_series": len(models),
        "total_series": len(sources),
        "proxy_definition": (
            "Time from parallel decode submission to the first and all "
            "successful ImageDataModel loads."
        ),
        "models": models,
    }


def _load_series(file_paths: Sequence[str]) -> ImageDataModel:
    model = ImageDataModel()
    if not model.load_dicom_series(list(file_paths)):
        raise RuntimeError("Series readiness proxy failed to decode a series")
    return model


def _measure_sync_interaction(
    sources: Sequence[LocalSeriesSource],
    models: Mapping[str, ImageDataModel],
    *,
    samples: int,
    event_app: QCoreApplication,
) -> list[float]:
    manager = MultiSeriesManager()
    if not manager.set_layout(1, 2):
        raise RuntimeError("Could not prepare the sync benchmark layout")
    for index, source in enumerate(sources):
        series_id = f"sync_{index}"
        info = SeriesInfo(
            series_id=series_id,
            patient_name=source.patient_name,
            patient_id=source.patient_id,
            study_description=source.study_description,
            series_description=source.series_description,
            modality=source.modality,
            slice_count=source.slice_count,
            study_instance_uid=source.study_instance_uid,
            series_instance_uid=source.series_instance_uid,
            frame_of_reference_uid=source.frame_of_reference_uid,
            orientation=source.orientation,
        )
        manager.add_series(info)
        manager.load_series_data(series_id, models[source.series_instance_uid])
        manager.bind_series_to_view(f"view_0_{index}", series_id)

    sync = SyncManager(manager)
    sync.set_sync_group(SyncGroup.SAME_STUDY)
    sync.set_sync_mode(SyncMode.SLICE)
    source_model = models[sources[0].series_instance_uid]
    indices = np.linspace(
        0,
        max(0, source_model.get_slice_count() - 1),
        samples,
    )
    runs: list[float] = []
    for index in indices:
        elapsed_ms, _ = _time_call(
            lambda value=int(round(float(index))): sync.sync_slice("view_0_0", value)
        )
        runs.append(elapsed_ms)
        event_app.processEvents()
    return runs


def _manifest_signature(manifest: DemoStudyManifest) -> tuple[Any, ...]:
    return (
        manifest.study_id.value,
        manifest.study_instance_uid,
        manifest.semantic_digest,
        tuple(
            (
                series.role,
                series.series_instance_uid,
                series.pixel_sha256,
                tuple(
                    (item.sop_instance_uid, item.sha256, item.size_bytes)
                    for item in series.files
                ),
            )
            for series in manifest.series
        ),
    )


def _time_call(call) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    return (time.perf_counter() - started) * 1000.0, result


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    return _round_ms(float(np.percentile(values, percentile)))


def _round_ms(value: float) -> float:
    return round(float(value), 6)


def _environment_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "medimager": get_version(),
        "numpy": np.__version__,
        "pydicom": pydicom.__version__,
        "pyside6": _package_version("PySide6"),
    }


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not-installed"


def _numeric_path(document: Mapping[str, Any], path: str) -> float | None:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None


def _validate_document(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA:
        raise ValueError(f"Expected performance schema {SCHEMA!r}")
    if int(document.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported performance schema version: "
            f"{document.get('schema_version')!r}"
        )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
