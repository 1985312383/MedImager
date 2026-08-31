"""Repeatable performance baseline for large DICOM loading and display paths."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from medimager.app_info import get_version
from medimager.core.image_data_model import ImageDataModel
from medimager.core.volume_geometry import (
    MprPlane,
    OrthogonalMprResampler,
    VolumeBuilder,
)
from medimager.ui.qt_image_utils import qimage_from_display_data
from medimager.utils.settings import get_performance_manager


SCHEMA = "medimager.performance_baseline"
SCHEMA_VERSION = 2


def run_baseline(
    *,
    slices: int = 128,
    rows: int = 256,
    cols: int = 256,
    repeats: int = 3,
    display_samples: int = 32,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Run a synthetic large-series baseline and optionally write it as JSON.

    The benchmark records timings only; it does not enforce thresholds because
    developer machines and CI runners vary too much for stable hard limits.
    """
    if slices < 1 or rows < 1 or cols < 1:
        raise ValueError("slices, rows and cols must be positive")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if display_samples < 1:
        raise ValueError("display_samples must be positive")

    with tempfile.TemporaryDirectory(prefix="medimager_perf_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        file_paths, volume_bytes = _write_synthetic_series(tmp_path, slices, rows, cols)

        load_runs: list[float] = []
        last_model: ImageDataModel | None = None
        for _ in range(repeats):
            get_performance_manager().clear_cache()
            model = ImageDataModel()
            elapsed_ms, success = _time_call(lambda: model.load_dicom_series(file_paths))
            if not success:
                raise RuntimeError("Synthetic DICOM series failed to load")
            load_runs.append(elapsed_ms)
            last_model = model

        if last_model is None:
            raise RuntimeError("No model was produced by the load benchmark")

        sample_indices = _sample_slice_indices(slices, display_samples)
        get_performance_manager().clear_cache()
        window_runs = [_time_call(lambda idx=idx: last_model.get_display_slice(idx))[0] for idx in sample_indices]
        cached_runs = [_time_call(lambda idx=idx: last_model.get_display_slice(idx))[0] for idx in sample_indices]
        qimage_runs = [
            _time_call(lambda idx=idx: qimage_from_display_data(last_model.get_display_slice(idx)))[0]
            for idx in sample_indices
        ]

        tracemalloc.start()
        mpr_build_ms, volume_result = _time_call(lambda: VolumeBuilder.build(last_model))
        _, mpr_peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if not volume_result.compatible or volume_result.volume is None:
            raise RuntimeError(f"Synthetic series is not MPR compatible: {volume_result.detail}")
        resampler = OrthogonalMprResampler(volume_result.volume)
        cursor = np.asarray(volume_result.volume.geometry.center_lps, dtype=np.float64)
        first_frame_ms, _ = _time_call(
            lambda: resampler.reconstruct(MprPlane.AXIAL, cursor)
        )
        mpr_interaction_runs = []
        bounds = volume_result.volume.geometry.patient_bounds
        for position in np.linspace(bounds[2][0], bounds[2][1], len(sample_indices)):
            sample_cursor = cursor.copy()
            sample_cursor[2] = position
            elapsed_ms, _ = _time_call(
                lambda current=sample_cursor: resampler.reconstruct(MprPlane.AXIAL, current)
            )
            mpr_interaction_runs.append(elapsed_ms)
        repeat_frame_runs = [
            _time_call(lambda: resampler.reconstruct(MprPlane.AXIAL, cursor))[0]
            for _ in range(max(1, len(sample_indices)))
        ]

    result = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": _environment_info(),
        "dataset": {
            "synthetic": True,
            "modality": "CT",
            "transfer_syntax": str(ExplicitVRLittleEndian),
            "slices": slices,
            "rows": rows,
            "cols": cols,
            "dtype": "int16",
            "volume_mb": round(volume_bytes / (1024 * 1024), 3),
            "display_samples": len(sample_indices),
            "repeats": repeats,
        },
        "benchmarks": {
            "dicom_series_load": _summarize_runs(load_runs, work_units=slices, unit_name="slices_per_second"),
            "display_windowing_cold": _summarize_runs(window_runs, work_units=len(sample_indices), unit_name="slices_per_second"),
            "display_windowing_cached": _summarize_runs(cached_runs, work_units=len(sample_indices), unit_name="slices_per_second"),
            "display_qimage_conversion": _summarize_runs(qimage_runs, work_units=len(sample_indices), unit_name="images_per_second"),
            "mpr_volume_build": {
                "total_ms": round(mpr_build_ms, 3),
                "estimated_volume_mb": round(volume_result.estimated_bytes / (1024 * 1024), 3),
                "python_peak_mb": round(mpr_peak_bytes / (1024 * 1024), 3),
            },
            "mpr_first_frame": {"total_ms": round(first_frame_ms, 3)},
            "mpr_cursor_interaction": {
                **_summarize_runs(
                    mpr_interaction_runs,
                    work_units=len(mpr_interaction_runs),
                    unit_name="frames_per_second",
                ),
                "p95_ms": round(float(np.percentile(mpr_interaction_runs, 95)), 3),
            },
            "mpr_repeat_frame": _summarize_runs(
                repeat_frame_runs,
                work_units=len(repeat_frame_runs),
                unit_name="frames_per_second",
            ),
        },
        "regression_policy": {
            "baseline_version": "2.6",
            "relative_limit": 1.20,
            "description": "Flag a regression when duration or peak memory exceeds the recorded v2.6 baseline by more than 20% on the same host.",
        },
    }

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MedImager performance baseline")
    parser.add_argument("--slices", type=int, default=128)
    parser.add_argument("--rows", type=int, default=256)
    parser.add_argument("--cols", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--display-samples", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("performance_baseline.json"))
    args = parser.parse_args(argv)

    result = run_baseline(
        slices=args.slices,
        rows=args.rows,
        cols=args.cols,
        repeats=args.repeats,
        display_samples=args.display_samples,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved performance baseline to {args.output}")
    return 0


def _write_synthetic_series(
    directory: Path,
    slices: int,
    rows: int,
    cols: int,
) -> tuple[list[str], int]:
    study_uid = generate_uid()
    series_uid = generate_uid()
    file_paths: list[str] = []
    volume_bytes = 0

    base = np.arange(rows * cols, dtype=np.int16).reshape(rows, cols)
    for index in range(slices):
        pixel_array = (base + index).astype(np.int16, copy=False)
        volume_bytes += int(pixel_array.nbytes)
        dataset = _make_ct_slice(
            pixel_array,
            study_uid=study_uid,
            series_uid=series_uid,
            instance_number=index + 1,
            z_position=float(index),
        )
        path = directory / f"slice_{index:04d}.dcm"
        dataset.save_as(path, enforce_file_format=True)
        file_paths.append(str(path))

    return file_paths, volume_bytes


def _make_ct_slice(
    pixel_array: np.ndarray,
    *,
    study_uid: str,
    series_uid: str,
    instance_number: int,
    z_position: float,
) -> FileDataset:
    rows, cols = pixel_array.shape
    sop_instance_uid = generate_uid()

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_instance_uid
    dataset.PatientName = "Performance^Synthetic"
    dataset.PatientID = "PERF-SYNTHETIC"
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.FrameOfReferenceUID = study_uid
    dataset.Modality = "CT"
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = instance_number
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.ImagePositionPatient = [0, 0, z_position]
    dataset.PixelSpacing = [0.7, 0.7]
    dataset.SliceThickness = 1.0
    dataset.Rows = rows
    dataset.Columns = cols
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 1
    dataset.RescaleSlope = 1.0
    dataset.RescaleIntercept = -1024.0
    dataset.WindowCenter = 40
    dataset.WindowWidth = 400
    dataset.PixelData = pixel_array.tobytes()
    return dataset


def _time_call(call: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = call()
    return (time.perf_counter() - start) * 1000.0, result


def _sample_slice_indices(slices: int, display_samples: int) -> list[int]:
    count = min(slices, display_samples)
    if count == slices:
        return list(range(slices))
    return sorted({int(round(value)) for value in np.linspace(0, slices - 1, count)})


def _summarize_runs(
    runs_ms: list[float],
    *,
    work_units: int,
    unit_name: str,
) -> dict[str, Any]:
    total_ms = float(sum(runs_ms))
    median_ms = float(statistics.median(runs_ms))
    mean_ms = float(statistics.fmean(runs_ms))
    throughput = 0.0 if total_ms <= 0 else work_units / (total_ms / 1000.0)
    return {
        "runs_ms": [round(value, 3) for value in runs_ms],
        "min_ms": round(min(runs_ms), 3),
        "median_ms": round(median_ms, 3),
        "mean_ms": round(mean_ms, 3),
        "max_ms": round(max(runs_ms), 3),
        "total_ms": round(total_ms, 3),
        unit_name: round(throughput, 3),
    }


def _environment_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "numpy": np.__version__,
        "pydicom": pydicom.__version__,
        "pyside6": _package_version("PySide6"),
        "medimager": get_version(),
    }


def _package_version(package_name: str) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "not-installed"


if __name__ == "__main__":
    raise SystemExit(main())
