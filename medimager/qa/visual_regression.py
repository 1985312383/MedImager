"""Deterministic visual-regression capture, comparison, and QA workflows.

The release harness deliberately keeps capture orchestration separate from the
comparison algorithm. Screens can therefore be captured from an installed
Windows executable or from pytest-qt while sharing exactly the same thresholds.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


BASELINE_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
BASELINE_MANIFEST_NAME = "visual-baselines.json"
REPORT_FILE_NAME = "visual-report.json"
VISIBILITY_REPORT_FILE_NAME = "visibility-report.json"
DEFAULT_VISIBILITY_SCALE_FACTORS = (1.25, 1.5)
_SCENARIO_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


@dataclass(frozen=True)
class VisualDiffThresholds:
    mae: float = 2.0
    outlier_delta: int = 12
    outlier_ratio: float = 0.005


@dataclass(frozen=True)
class VisualDiffMetrics:
    mae: float
    outlier_ratio: float
    max_delta: int
    width: int
    height: int
    same_size: bool = True

    def passes(self, thresholds: VisualDiffThresholds = VisualDiffThresholds()) -> bool:
        return (
            self.same_size
            and self.mae <= thresholds.mae
            and self.outlier_ratio <= thresholds.outlier_ratio
        )


@dataclass(frozen=True)
class VisualScenario:
    key: str
    theme: str
    language: str
    surface: str
    width: int = 1280
    height: int = 800
    dpr: float = 1.0

    def __post_init__(self) -> None:
        if not _SCENARIO_KEY_RE.fullmatch(self.key):
            raise ValueError(f"Invalid visual scenario key: {self.key!r}")
        if self.width <= 0 or self.height <= 0 or self.dpr <= 0:
            raise ValueError("Visual scenario dimensions and DPR must be positive")

    @property
    def pixel_size(self) -> tuple[int, int]:
        return (round(self.width * self.dpr), round(self.height * self.dpr))


class VisualRunMode(StrEnum):
    COMPARE = "compare"
    UPDATE = "update"


class BaselineUpdateNotAllowed(PermissionError):
    """Raised when baseline mutation was not explicitly authorized."""


@dataclass(frozen=True)
class VisualScenarioResult:
    key: str
    status: str
    metrics: VisualDiffMetrics | None = None
    actual_path: Path | None = None
    baseline_path: Path | None = None
    diff_path: Path | None = None
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"passed", "updated"}


@dataclass(frozen=True)
class VisualRunReport:
    mode: VisualRunMode
    results: tuple[VisualScenarioResult, ...]
    report_path: Path
    baseline_manifest_path: Path

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def failed_keys(self) -> tuple[str, ...]:
        return tuple(result.key for result in self.results if not result.passed)


@dataclass(frozen=True)
class VisibilityCheckResult:
    scenario_key: str
    scale_factor: float
    logical_width: int
    logical_height: int
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class VisibilityRunReport:
    results: tuple[VisibilityCheckResult, ...]
    report_path: Path | None = None

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)


def default_v26_scenarios() -> tuple[VisualScenario, ...]:
    dark_zh = (
        ("start_center", "start_center"),
        ("ct_overview", "ct_2x2"),
        ("ct_reference_lines", "reference_lines"),
        ("mr_neuro", "mr_2x2"),
        ("mpr_console", "mpr"),
        ("geometry_rejection", "geometry_rejection"),
        ("settings_center", "settings"),
    )
    light_en = (
        ("start_center", "start_center"),
        ("ct_overview", "ct_2x2"),
        ("mr_neuro", "mr_2x2"),
        ("mpr_console", "mpr"),
        ("settings_center", "settings"),
    )
    scenarios = [
        VisualScenario(f"dark_zh_{key}", "dark", "zh_CN", surface)
        for key, surface in dark_zh
    ]
    scenarios.extend(
        VisualScenario(f"light_en_{key}", "light", "en_US", surface)
        for key, surface in light_en
    )
    return tuple(scenarios)


def default_v26_manifest_metadata() -> dict[str, Any]:
    """Return stable metadata describing the release capture contract.

    Runtime-specific data such as the machine name or capture timestamp is
    intentionally excluded so that a checked-in manifest remains reproducible.
    """

    return {
        "application": "MedImager",
        "release": "2.6.0",
        "target_platform": "Windows",
        "target_resolution": "1280x800",
        "target_dpr": 1.0,
        "target_font": "Segoe UI 9",
        "surface_provider": "RealMedImagerSurfaceProvider",
        "capture_shell": "VisualWorkbenchShell",
        "captured_chrome": [
            "menu_bar",
            "ViewerToolbar",
            "SeriesPanel",
            "workspace",
            "status_bar",
        ],
        "scenario_count": len(default_v26_scenarios()),
    }


def _scenario_document(scenario: VisualScenario) -> dict[str, Any]:
    return {
        "key": scenario.key,
        "theme": scenario.theme,
        "language": scenario.language,
        "surface": scenario.surface,
        "width": scenario.width,
        "height": scenario.height,
        "dpr": scenario.dpr,
    }


def _qimage_array(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    height, width = converted.height(), converted.width()
    if height <= 0 or width <= 0:
        raise ValueError("Image is empty")
    raw = np.frombuffer(
        converted.constBits(), dtype=np.uint8, count=converted.sizeInBytes()
    )
    rows = raw.reshape(height, converted.bytesPerLine())
    return np.ascontiguousarray(rows[:, : width * 4].reshape(height, width, 4))


def _image_array(value: Any) -> np.ndarray:
    if isinstance(value, (str, Path)):
        with Image.open(value) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if isinstance(value, QWidget):
        value = value.grab()
    if isinstance(value, QPixmap):
        value = value.toImage()
    if isinstance(value, QImage):
        return _qimage_array(value)
    array = np.asarray(value)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 4, axis=2)
        array[..., 3] = 255
    elif array.ndim == 3 and array.shape[2] == 3:
        alpha = np.full((*array.shape[:2], 1), 255, dtype=array.dtype)
        array = np.concatenate((array, alpha), axis=2)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("Expected an HxW, HxWx3, or HxWx4 image")
    return np.ascontiguousarray(np.clip(array, 0, 255).astype(np.uint8, copy=False))


def _settle_widget(widget: QWidget, cycles: int) -> None:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("A QApplication is required to capture QWidget surfaces")
    widget.ensurePolished()
    for _ in range(max(1, cycles)):
        layout = widget.layout()
        if layout is not None:
            layout.activate()
        app.processEvents()


def _clear_pointer_hover_state(widget: QWidget) -> None:
    """Put a capture tree into a deterministic, non-hovered state.

    Native Qt windows inherit the host cursor position when they are shown.
    A cursor over a menu, list row, or button can therefore change a baseline
    even though the scenario itself is identical.  The capture root is made
    mouse-transparent while it settles, and stale ``WA_UnderMouse`` flags are
    cleared from deepest children first so stylesheet ``:hover`` selectors and
    menu status tips cannot leak into the image.
    """

    descendants = widget.findChildren(QWidget)
    for candidate in (*reversed(descendants), widget):
        if not candidate.testAttribute(Qt.WidgetAttribute.WA_UnderMouse):
            continue
        candidate.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        QApplication.sendEvent(candidate, QEvent(QEvent.Type.Leave))


def capture_widget_surface(
    widget: QWidget,
    scenario: VisualScenario,
    *,
    settle_cycles: int = 3,
) -> QImage:
    """Render a QWidget at the scenario's exact logical size and DPR.

    Rendering into an explicitly sized QImage avoids inheriting the capture
    monitor's device-pixel ratio. The widget's original size and visibility are
    restored after capture, making the helper safe for pytest fixture surfaces.
    """

    old_size = widget.size()
    was_visible = widget.isVisible()
    ignored_pointer_events = widget.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    _clear_pointer_hover_state(widget)
    widget.resize(QSize(scenario.width, scenario.height))
    if not was_visible:
        widget.show()
    try:
        _settle_widget(widget, settle_cycles)
        pixel_width, pixel_height = scenario.pixel_size
        image = QImage(
            pixel_width,
            pixel_height,
            QImage.Format.Format_RGBA8888,
        )
        image.setDevicePixelRatio(scenario.dpr)
        image.fill(0)
        painter = QPainter(image)
        try:
            widget.render(painter, QPoint())
        finally:
            painter.end()
        return image
    finally:
        widget.resize(old_size)
        if not was_visible:
            widget.hide()
        widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            ignored_pointer_events,
        )


def _capture_array(value: Any, scenario: VisualScenario) -> np.ndarray:
    image = (
        capture_widget_surface(value, scenario) if isinstance(value, QWidget) else value
    )
    array = _image_array(image).copy()
    expected_width, expected_height = scenario.pixel_size
    if array.shape[:2] != (expected_height, expected_width):
        raise ValueError(
            f"Scenario {scenario.key!r} expected {expected_width}x{expected_height} pixels, "
            f"got {array.shape[1]}x{array.shape[0]}"
        )
    return array


def _png_bytes(value: Any) -> bytes:
    output = io.BytesIO()
    Image.fromarray(_image_array(value), mode="RGBA").save(
        output,
        format="PNG",
        compress_level=9,
        optimize=False,
    )
    return output.getvalue()


def _atomic_write_bytes(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def _atomic_write_json(destination: Path, document: Mapping[str, Any]) -> Path:
    try:
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Visual regression metadata must be JSON serializable"
        ) from exc
    return _atomic_write_bytes(destination, payload)


def _image_digest(array: np.ndarray) -> str:
    height, width = array.shape[:2]
    digest = hashlib.sha256()
    digest.update(f"rgba8:{width}x{height}\n".encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


class VisualBaselineStore:
    """Content-addressed baseline storage with an atomically switched manifest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / BASELINE_MANIFEST_NAME
        self.images_path = self.root / "images"

    def load_manifest(self, *, required: bool = True) -> dict[str, Any] | None:
        if not self.manifest_path.is_file():
            if required:
                raise FileNotFoundError(self.manifest_path)
            return None
        try:
            document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Invalid visual baseline manifest: {self.manifest_path}"
            ) from exc
        if not isinstance(document, dict):
            raise ValueError("Visual baseline manifest must be a JSON object")
        if document.get("schema_version") != BASELINE_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported visual baseline schema: "
                f"{document.get('schema_version')!r}"
            )
        if not isinstance(document.get("scenarios"), dict):
            raise ValueError("Visual baseline manifest has no scenario map")
        return document

    def resolve_entry_path(self, entry: Mapping[str, Any]) -> Path:
        relative_name = entry.get("file")
        if not isinstance(relative_name, str) or not relative_name:
            raise ValueError("Visual baseline entry has no file")
        root = self.root.resolve()
        candidate = (self.root / relative_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Visual baseline entry escapes the baseline root") from exc
        return candidate

    def update(
        self,
        captures: Mapping[VisualScenario, np.ndarray],
        *,
        allow_update: bool,
        metadata: Mapping[str, Any] | None = None,
        thresholds: VisualDiffThresholds = VisualDiffThresholds(),
    ) -> dict[str, Path]:
        if not allow_update:
            raise BaselineUpdateNotAllowed(
                "Baseline updates require allow_baseline_update=True"
            )
        current = self.load_manifest(required=False)
        scenario_entries: dict[str, Any] = dict(
            current.get("scenarios", {}) if current is not None else {}
        )
        written: dict[str, Path] = {}
        for scenario, capture in captures.items():
            array = _capture_array(capture, scenario)
            digest = _image_digest(array)
            relative_path = Path("images") / f"{scenario.key}.{digest[:24]}.png"
            destination = self.root / relative_path
            destination_matches = False
            if destination.is_file():
                try:
                    destination_matches = (
                        _image_digest(_image_array(destination)) == digest
                    )
                except (OSError, ValueError):
                    destination_matches = False
            if not destination_matches:
                _atomic_write_bytes(destination, _png_bytes(array))
            entry = _scenario_document(scenario)
            entry.update(
                {
                    "file": relative_path.as_posix(),
                    "sha256_rgba": digest,
                }
            )
            scenario_entries[scenario.key] = entry
            written[scenario.key] = destination

        manifest_metadata = default_v26_manifest_metadata()
        if current is not None and isinstance(current.get("metadata"), dict):
            manifest_metadata.update(current["metadata"])
        if metadata:
            manifest_metadata.update(dict(metadata))
        manifest_metadata["scenario_count"] = len(scenario_entries)
        document = {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "suite": "medimager-v2.6",
            "metadata": manifest_metadata,
            "thresholds": {
                "mae": thresholds.mae,
                "outlier_delta": thresholds.outlier_delta,
                "outlier_ratio": thresholds.outlier_ratio,
            },
            "scenarios": scenario_entries,
        }
        # Image names are content addressed. New images can be committed first;
        # the old manifest remains coherent until this final atomic replacement.
        _atomic_write_json(self.manifest_path, document)
        try:
            self._prune_unreferenced_images(document)
        except OSError:
            # Old content-addressed images are harmless. Cleanup must never turn
            # an already committed, coherent manifest into a reported failure.
            pass
        return written

    def _prune_unreferenced_images(self, manifest: Mapping[str, Any]) -> None:
        if not self.images_path.is_dir():
            return
        referenced = {
            str(entry.get("file", ""))
            for entry in manifest.get("scenarios", {}).values()
            if isinstance(entry, dict)
        }
        for candidate in self.images_path.iterdir():
            relative = candidate.relative_to(self.root).as_posix()
            if candidate.is_file() and relative not in referenced:
                candidate.unlink(missing_ok=True)


def compare_images(
    actual: Any,
    reference: Any,
    thresholds: VisualDiffThresholds = VisualDiffThresholds(),
) -> VisualDiffMetrics:
    actual_rgba = _image_array(actual)
    reference_rgba = _image_array(reference)
    if actual_rgba.shape != reference_rgba.shape:
        actual_height, actual_width = actual_rgba.shape[:2]
        return VisualDiffMetrics(
            mae=float("inf"),
            outlier_ratio=1.0,
            max_delta=255,
            width=actual_width,
            height=actual_height,
            same_size=False,
        )
    delta = np.abs(
        actual_rgba[..., :3].astype(np.int16) - reference_rgba[..., :3].astype(np.int16)
    )
    pixel_delta = delta.max(axis=2)
    height, width = actual_rgba.shape[:2]
    return VisualDiffMetrics(
        mae=float(delta.mean()) if delta.size else 0.0,
        outlier_ratio=float(
            np.count_nonzero(pixel_delta > thresholds.outlier_delta) / pixel_delta.size
        ),
        max_delta=int(delta.max()) if delta.size else 0,
        width=width,
        height=height,
    )


def assert_visual_match(
    actual: Any,
    reference: Any,
    thresholds: VisualDiffThresholds = VisualDiffThresholds(),
) -> VisualDiffMetrics:
    metrics = compare_images(actual, reference, thresholds)
    if not metrics.passes(thresholds):
        raise AssertionError(
            "Visual regression failed: "
            f"size={metrics.width}x{metrics.height} same_size={metrics.same_size}, "
            f"MAE={metrics.mae:.3f} (limit {thresholds.mae:.3f}), "
            f"outliers={metrics.outlier_ratio:.3%} (limit {thresholds.outlier_ratio:.3%}), "
            f"max_delta={metrics.max_delta}"
        )
    return metrics


def save_diff_image(actual: Any, reference: Any, destination: str | Path) -> Path:
    actual_rgba = _image_array(actual)
    reference_rgba = _image_array(reference)
    if actual_rgba.shape != reference_rgba.shape:
        raise ValueError("Cannot render a diff for images with different dimensions")
    delta = np.abs(
        actual_rgba[..., :3].astype(np.int16) - reference_rgba[..., :3].astype(np.int16)
    ).max(axis=2)
    heat = np.zeros((*delta.shape, 4), dtype=np.uint8)
    heat[..., 0] = np.clip(delta * 4, 0, 255).astype(np.uint8)
    heat[..., 1] = np.clip(delta - 32, 0, 255).astype(np.uint8)
    heat[..., 3] = 255
    path = Path(destination)
    return _atomic_write_bytes(path, _png_bytes(heat))


def _save_comparison_diff(actual: Any, reference: Any, destination: Path) -> Path:
    actual_rgba = _image_array(actual)
    reference_rgba = _image_array(reference)
    if actual_rgba.shape == reference_rgba.shape:
        return save_diff_image(actual_rgba, reference_rgba, destination)

    height = max(actual_rgba.shape[0], reference_rgba.shape[0])
    width = max(actual_rgba.shape[1], reference_rgba.shape[1])
    heat = np.zeros((height, width, 4), dtype=np.uint8)
    heat[..., 0] = 255
    heat[..., 3] = 255
    overlap_height = min(actual_rgba.shape[0], reference_rgba.shape[0])
    overlap_width = min(actual_rgba.shape[1], reference_rgba.shape[1])
    delta = np.abs(
        actual_rgba[:overlap_height, :overlap_width, :3].astype(np.int16)
        - reference_rgba[:overlap_height, :overlap_width, :3].astype(np.int16)
    ).max(axis=2)
    overlap = heat[:overlap_height, :overlap_width]
    overlap[..., 0] = np.clip(delta * 4, 0, 255).astype(np.uint8)
    overlap[..., 1] = np.clip(delta - 32, 0, 255).astype(np.uint8)
    return _atomic_write_bytes(destination, _png_bytes(heat))


def _metric_document(metrics: VisualDiffMetrics | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {
        "mae": metrics.mae if math.isfinite(metrics.mae) else None,
        "outlier_ratio": metrics.outlier_ratio,
        "max_delta": metrics.max_delta,
        "width": metrics.width,
        "height": metrics.height,
        "same_size": metrics.same_size,
    }


def _result_document(result: VisualScenarioResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "status": result.status,
        "passed": result.passed,
        "detail": result.detail,
        "metrics": _metric_document(result.metrics),
        "actual": str(result.actual_path) if result.actual_path else None,
        "baseline": str(result.baseline_path) if result.baseline_path else None,
        "diff": str(result.diff_path) if result.diff_path else None,
    }


class VisualRegressionHarness:
    """Capture a deterministic visual suite in compare or opt-in update mode."""

    def __init__(
        self,
        baseline_root: str | Path,
        artifact_root: str | Path,
        *,
        thresholds: VisualDiffThresholds = VisualDiffThresholds(),
        enforce_release_contract: bool = True,
    ) -> None:
        self.baselines = VisualBaselineStore(baseline_root)
        self.artifact_root = Path(artifact_root)
        self.thresholds = thresholds
        self.enforce_release_contract = enforce_release_contract

    def run(
        self,
        surface_provider: Mapping[str, Any] | Callable[[VisualScenario], Any],
        *,
        scenarios: Sequence[VisualScenario] | None = None,
        mode: VisualRunMode | str = VisualRunMode.COMPARE,
        allow_baseline_update: bool = False,
        manifest_metadata: Mapping[str, Any] | None = None,
    ) -> VisualRunReport:
        selected = tuple(scenarios or default_v26_scenarios())
        self._validate_scenarios(selected)
        selected_mode = VisualRunMode(mode)
        if selected_mode is VisualRunMode.UPDATE and not allow_baseline_update:
            raise BaselineUpdateNotAllowed(
                "Baseline updates require allow_baseline_update=True"
            )

        captures: dict[VisualScenario, np.ndarray] = {}
        capture_errors: dict[str, str] = {}
        for scenario in selected:
            try:
                provided = (
                    surface_provider(scenario)
                    if callable(surface_provider)
                    else surface_provider[scenario.key]
                )
                captures[scenario] = _capture_array(provided, scenario)
            except Exception as exc:  # noqa: BLE001 - capture failures belong in QA output
                capture_errors[scenario.key] = f"{type(exc).__name__}: {exc}"

        if selected_mode is VisualRunMode.UPDATE:
            if capture_errors:
                failed = ", ".join(sorted(capture_errors))
                raise RuntimeError(
                    "Baseline update aborted before mutation because capture failed for: "
                    f"{failed}"
                )
            results = self._update(captures, manifest_metadata, allow_baseline_update)
        else:
            results = self._compare(selected, captures, capture_errors)

        report_path = self.artifact_root / REPORT_FILE_NAME
        report = VisualRunReport(
            mode=selected_mode,
            results=tuple(results),
            report_path=report_path,
            baseline_manifest_path=self.baselines.manifest_path,
        )
        self._write_report(report, selected)
        return report

    def _validate_scenarios(self, scenarios: Sequence[VisualScenario]) -> None:
        if not scenarios:
            raise ValueError("A visual regression run requires at least one scenario")
        keys = [scenario.key for scenario in scenarios]
        if len(keys) != len(set(keys)):
            raise ValueError("Visual scenario keys must be unique")
        if self.enforce_release_contract:
            invalid = [
                scenario.key
                for scenario in scenarios
                if (scenario.width, scenario.height, scenario.dpr) != (1280, 800, 1.0)
            ]
            if invalid:
                raise ValueError(
                    "Release baselines require 1280x800 at DPR 1: " + ", ".join(invalid)
                )

    def _update(
        self,
        captures: Mapping[VisualScenario, np.ndarray],
        metadata: Mapping[str, Any] | None,
        allow_update: bool,
    ) -> list[VisualScenarioResult]:
        written = self.baselines.update(
            captures,
            allow_update=allow_update,
            metadata=metadata,
            thresholds=self.thresholds,
        )
        return [
            VisualScenarioResult(
                key=scenario.key,
                status="updated",
                baseline_path=written[scenario.key],
            )
            for scenario in captures
        ]

    def _compare(
        self,
        scenarios: Sequence[VisualScenario],
        captures: Mapping[VisualScenario, np.ndarray],
        capture_errors: Mapping[str, str],
    ) -> list[VisualScenarioResult]:
        try:
            manifest = self.baselines.load_manifest(required=True)
            manifest_error = ""
        except (FileNotFoundError, ValueError) as exc:
            manifest = None
            manifest_error = f"{type(exc).__name__}: {exc}"
        entries = manifest.get("scenarios", {}) if manifest else {}
        results: list[VisualScenarioResult] = []
        for scenario in scenarios:
            if scenario.key in capture_errors:
                results.append(
                    VisualScenarioResult(
                        key=scenario.key,
                        status="capture_error",
                        detail=capture_errors[scenario.key],
                    )
                )
                continue
            capture = captures[scenario]
            actual_path = self.artifact_root / "actual" / f"{scenario.key}.png"
            _atomic_write_bytes(actual_path, _png_bytes(capture))
            entry = entries.get(scenario.key)
            if not isinstance(entry, dict):
                results.append(
                    VisualScenarioResult(
                        key=scenario.key,
                        status="missing_baseline",
                        actual_path=actual_path,
                        detail=manifest_error
                        or "Scenario is absent from the baseline manifest",
                    )
                )
                continue
            try:
                baseline_path = self.baselines.resolve_entry_path(entry)
                baseline = _image_array(baseline_path)
                expected_digest = entry.get("sha256_rgba")
                if expected_digest != _image_digest(baseline):
                    raise ValueError(
                        "Baseline pixel digest does not match its manifest"
                    )
            except (OSError, ValueError) as exc:
                results.append(
                    VisualScenarioResult(
                        key=scenario.key,
                        status="invalid_baseline",
                        actual_path=actual_path,
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            metrics = compare_images(capture, baseline, self.thresholds)
            diff_path = self.artifact_root / "diff" / f"{scenario.key}.png"
            _save_comparison_diff(capture, baseline, diff_path)
            scenario_contract = _scenario_document(scenario)
            contract_matches = all(
                entry.get(key) == value for key, value in scenario_contract.items()
            )
            passed = metrics.passes(self.thresholds) and contract_matches
            detail = ""
            if not contract_matches:
                detail = (
                    "Baseline scenario metadata does not match the requested capture"
                )
            results.append(
                VisualScenarioResult(
                    key=scenario.key,
                    status="passed" if passed else "failed",
                    metrics=metrics,
                    actual_path=actual_path,
                    baseline_path=baseline_path,
                    diff_path=diff_path,
                    detail=detail,
                )
            )
        return results

    def _write_report(
        self,
        report: VisualRunReport,
        scenarios: Sequence[VisualScenario],
    ) -> None:
        document = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "suite": "medimager-v2.6",
            "mode": report.mode.value,
            "passed": report.passed,
            "thresholds": {
                "mae": self.thresholds.mae,
                "outlier_delta": self.thresholds.outlier_delta,
                "outlier_ratio": self.thresholds.outlier_ratio,
            },
            "baseline_manifest": str(report.baseline_manifest_path),
            "scenarios": [_scenario_document(scenario) for scenario in scenarios],
            "results": [_result_document(result) for result in report.results],
        }
        _atomic_write_json(report.report_path, document)


def find_visibility_violations(
    root: QWidget,
    widgets: Iterable[QWidget] | None = None,
    *,
    fully_contained: bool = False,
    require_visible: bool = False,
) -> tuple[str, ...]:
    """Return controls hidden or outside the root's logical viewport.

    The backward-compatible default only reports controls that are fully
    outside. High-DPI checks use ``fully_contained=True`` to also detect partial
    clipping and ``require_visible=True`` for explicitly required controls.
    """

    candidates = (
        tuple(widgets) if widgets is not None else tuple(root.findChildren(QWidget))
    )
    root_bounds = QRect(QPoint(0, 0), root.size())
    failures: list[str] = []
    for widget in candidates:
        if widget is root or widget.isWindow():
            continue
        name = widget.objectName() or widget.__class__.__name__
        if not widget.isVisibleTo(root):
            if require_visible:
                failures.append(f"hidden:{name}")
            continue
        top_left = widget.mapTo(root, QPoint(0, 0))
        bounds = QRect(top_left, widget.size())
        if fully_contained:
            if not root_bounds.contains(bounds):
                failures.append(f"clipped:{name}")
        elif not root_bounds.intersects(bounds):
            failures.append(name)
    return tuple(failures)


def check_widget_visibility_at_scale(
    root: QWidget,
    scenario: VisualScenario,
    scale_factor: float,
    *,
    widgets: Iterable[QWidget] | None = None,
    settle_cycles: int = 3,
) -> VisibilityCheckResult:
    """Run a no-screenshot clipping check for a physical DPI scale factor.

    A 1280x800 physical viewport corresponds to 1024x640 logical pixels at
    125%, and roughly 853x533 at 150%. This deliberately checks geometry only;
    pixel baselines remain fixed to DPR 1.
    """

    if scale_factor <= 0:
        raise ValueError("DPI scale factor must be positive")
    required = tuple(widgets) if widgets is not None else None
    logical_width = max(1, round(scenario.width / scale_factor))
    logical_height = max(1, round(scenario.height / scale_factor))
    old_size = root.size()
    was_visible = root.isVisible()
    root.resize(logical_width, logical_height)
    if not was_visible:
        root.show()
    try:
        _settle_widget(root, settle_cycles)
        violations = find_visibility_violations(
            root,
            required,
            fully_contained=True,
            require_visible=required is not None,
        )
    finally:
        root.resize(old_size)
        if not was_visible:
            root.hide()
    return VisibilityCheckResult(
        scenario_key=scenario.key,
        scale_factor=float(scale_factor),
        logical_width=logical_width,
        logical_height=logical_height,
        violations=violations,
    )


def run_visibility_matrix(
    surface_provider: Mapping[str, QWidget] | Callable[[VisualScenario], QWidget],
    *,
    scenarios: Sequence[VisualScenario] | None = None,
    scale_factors: Sequence[float] = DEFAULT_VISIBILITY_SCALE_FACTORS,
    required_widgets: Callable[[VisualScenario, QWidget], Iterable[QWidget]]
    | None = None,
    artifact_root: str | Path | None = None,
) -> VisibilityRunReport:
    """Evaluate the v2.6 surfaces at 125% and 150% without pixel diffs."""

    selected = tuple(scenarios or default_v26_scenarios())
    if not selected:
        raise ValueError("A visibility run requires at least one scenario")
    if not scale_factors:
        raise ValueError("A visibility run requires at least one DPI scale factor")
    results: list[VisibilityCheckResult] = []
    for scenario in selected:
        surface = (
            surface_provider(scenario)
            if callable(surface_provider)
            else surface_provider[scenario.key]
        )
        if not isinstance(surface, QWidget):
            raise TypeError(f"Visibility surface {scenario.key!r} is not a QWidget")
        critical = (
            tuple(required_widgets(scenario, surface)) if required_widgets else None
        )
        for scale_factor in scale_factors:
            results.append(
                check_widget_visibility_at_scale(
                    surface,
                    scenario,
                    float(scale_factor),
                    widgets=critical,
                )
            )

    report_path = (
        Path(artifact_root) / VISIBILITY_REPORT_FILE_NAME
        if artifact_root is not None
        else None
    )
    report = VisibilityRunReport(tuple(results), report_path)
    if report_path is not None:
        _atomic_write_json(
            report_path,
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "suite": "medimager-v2.6",
                "mode": "visibility_only",
                "passed": report.passed,
                "results": [
                    {
                        "key": result.scenario_key,
                        "scale_factor": result.scale_factor,
                        "logical_width": result.logical_width,
                        "logical_height": result.logical_height,
                        "passed": result.passed,
                        "violations": list(result.violations),
                    }
                    for result in report.results
                ],
            },
        )
    return report


class GuiHeartbeatProbe(QObject):
    """Measure the longest interval during which the GUI event loop did not tick."""

    def __init__(self, interval_ms: int = 10, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._interval_ms = max(1, int(interval_ms))
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._tick)
        self._last_tick: float | None = None
        self._gaps_ms: list[float] = []

    @property
    def max_gap_ms(self) -> float:
        return max(self._gaps_ms, default=0.0)

    @property
    def sample_count(self) -> int:
        return len(self._gaps_ms)

    @property
    def is_armed(self) -> bool:
        """Return whether the first real timer tick established the baseline."""

        return self._last_tick is not None

    def start(self) -> None:
        self._gaps_ms.clear()
        # Starting a QTimer merely schedules its first timeout.  Measuring from
        # this method would incorrectly attribute any pre-existing event-queue
        # backlog (for example deferred Qt teardown from an earlier test) to the
        # workload being probed.  The first delivered timeout therefore arms
        # the probe; only intervals between consecutive real GUI ticks are
        # heartbeat samples.
        self._last_tick = None
        self._timer.start()

    def stop(self) -> float:
        self._timer.stop()
        self._last_tick = None
        return self.max_gap_ms

    def _tick(self) -> None:
        now = perf_counter()
        if self._last_tick is not None:
            self._gaps_ms.append((now - self._last_tick) * 1000.0)
        self._last_tick = now
