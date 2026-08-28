"""Versioned JSON persistence for viewport annotations."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF

from medimager.app_info import APP_NAME, get_version
from medimager.core.image_data_model import (
    AngleMeasurementData,
    ImageDataModel,
    MeasurementData,
)
from medimager.core.roi import BaseROI, CircleROI, EllipseROI, RectangleROI


ANNOTATION_SCHEMA_VERSION = 1
_ANNOTATION_COUNT_KEYS = ("rois", "measurements", "angle_measurements")
_SAVED_ANNOTATION_SIGNATURE_ATTRIBUTE = "_medimager_saved_annotation_signature"


class AnnotationImportError(ValueError):
    """Base class for annotation documents that cannot be imported safely."""


class AnnotationSeriesMismatchError(AnnotationImportError):
    """Raised when an annotation document belongs to a different series."""

    def __init__(self, mismatches: dict[str, tuple[str, str]]) -> None:
        self.mismatches = mismatches
        fields = ", ".join(sorted(mismatches))
        super().__init__(f"Annotation series identity mismatch: {fields}.")


class InvalidAnnotationError(AnnotationImportError):
    """Raised when an annotation item is malformed or outside the volume."""


@dataclass(frozen=True, eq=False)
class AnnotationImportResult(Mapping[str, int]):
    """Structured import outcome with count-mapping backward compatibility."""

    rois: int
    measurements: int
    angle_measurements: int
    mode: str
    identity_mismatch_overridden: bool = False

    @property
    def total(self) -> int:
        return self.rois + self.measurements + self.angle_measurements

    def __getitem__(self, key: str) -> int:
        if key not in _ANNOTATION_COUNT_KEYS:
            raise KeyError(key)
        return int(getattr(self, key))

    def __iter__(self) -> Iterator[str]:
        return iter(_ANNOTATION_COUNT_KEYS)

    def __len__(self) -> int:
        return len(_ANNOTATION_COUNT_KEYS)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AnnotationImportResult):
            return (
                tuple(self[key] for key in _ANNOTATION_COUNT_KEYS)
                == tuple(other[key] for key in _ANNOTATION_COUNT_KEYS)
                and self.mode == other.mode
                and self.identity_mismatch_overridden
                == other.identity_mismatch_overridden
            )
        if isinstance(other, Mapping):
            return dict(self) == dict(other)
        return NotImplemented


def export_annotations(model: ImageDataModel) -> dict[str, Any]:
    """Return a JSON-serializable annotation document for an image model."""
    return {
        "schema": "medimager.annotations",
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "app": APP_NAME,
        "app_version": get_version(),
        "series": _series_identity(model),
        "annotations": {
            "rois": [_serialize_roi(roi) for roi in model.rois],
            "measurements": [
                _serialize_measurement(measurement) for measurement in model.measurements
            ],
            "angle_measurements": [
                _serialize_angle_measurement(measurement)
                for measurement in model.angle_measurements
            ],
        },
    }


def save_annotations(model: ImageDataModel, file_path: str | Path) -> None:
    """Atomically write the model annotations to a UTF-8 JSON file."""
    path = Path(file_path)
    payload = json.dumps(export_annotations(model), ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        setattr(model, _SAVED_ANNOTATION_SIGNATURE_ATTRIBUTE, _annotation_signature(model))
        mark_saved = getattr(model, "mark_annotations_saved", None)
        if callable(mark_saved):
            mark_saved()
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def import_annotations(
    model: ImageDataModel,
    source: dict[str, Any] | str | Path,
    *,
    replace: bool = True,
    allow_identity_mismatch: bool = False,
) -> AnnotationImportResult:
    """
    Load annotations into a model.

    The default is deliberately safe: PatientID, StudyInstanceUID and
    SeriesInstanceUID must match the target model. A caller that has already
    obtained explicit user consent may set ``allow_identity_mismatch=True``;
    this never bypasses item or slice-bound validation.

    All parsing and validation happens before the target model is mutated.
    """
    document = _load_document(source)
    _validate_document(document)
    annotations = document["annotations"]
    rois = _deserialize_items(annotations, "rois", _deserialize_roi)
    measurements = _deserialize_items(
        annotations, "measurements", _deserialize_measurement
    )
    angle_measurements = _deserialize_items(
        annotations, "angle_measurements", _deserialize_angle_measurement
    )

    source_identity = document.get("series")
    if not isinstance(source_identity, dict):
        raise AnnotationSeriesMismatchError(
            {"series": ("missing", "target series")}
        )
    mismatches = _series_identity_mismatches(model, source_identity)
    if mismatches and not allow_identity_mismatch:
        raise AnnotationSeriesMismatchError(mismatches)

    _validate_annotation_items(
        model,
        source_identity,
        rois,
        measurements,
        angle_measurements,
        replace=replace,
    )

    if replace:
        model.rois.clear()
        model.selected_indices.clear()
        model.measurements.clear()
        model.selected_measurement_indices.clear()
        model.angle_measurements.clear()
        selected_angle_ids = getattr(model, "selected_angle_measurement_ids", None)
        if selected_angle_ids is not None:
            selected_angle_ids.clear()

    model.rois.extend(rois)
    model.measurements.extend(measurements)
    model.angle_measurements.extend(angle_measurements)
    model.data_changed.emit()
    mark_dirty = getattr(model, "mark_annotations_dirty", None)
    if callable(mark_dirty):
        mark_dirty()

    return AnnotationImportResult(
        rois=len(rois),
        measurements=len(measurements),
        angle_measurements=len(angle_measurements),
        mode="replace" if replace else "merge",
        identity_mismatch_overridden=bool(mismatches),
    )


def has_unsaved_annotations(model: ImageDataModel) -> bool:
    """Return whether annotations differ from the model's last successful save."""
    model_checker = getattr(model, "has_unsaved_annotations", None)
    if callable(model_checker) and model_checker():
        return True
    saved_signature = getattr(model, _SAVED_ANNOTATION_SIGNATURE_ATTRIBUTE, None)
    if saved_signature is None:
        return bool(model.rois or model.measurements or model.angle_measurements)
    return saved_signature != _annotation_signature(model)


def get_annotation_counts(model: ImageDataModel) -> dict[str, int]:
    """Return current annotation counts for confirmation and status UIs."""
    return {
        "rois": len(model.rois),
        "measurements": len(model.measurements),
        "angle_measurements": len(model.angle_measurements),
    }


def _series_identity(model: ImageDataModel) -> dict[str, Any]:
    return {
        "patient_id": str(model.get_metadata("PatientID", "")),
        "study_instance_uid": str(model.get_metadata("StudyInstanceUID", "")),
        "series_instance_uid": str(model.get_metadata("SeriesInstanceUID", "")),
        "series_description": str(model.get_metadata("SeriesDescription", "")),
        "slice_count": model.get_slice_count(),
    }


def _serialize_roi(roi: BaseROI) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": roi.id,
        "type": roi.shape.value,
        "slice_index": roi.slice_index,
        "show_stats": bool(getattr(roi, "show_stats", True)),
    }

    if isinstance(roi, RectangleROI):
        data["top_left"] = _point_tuple(roi.top_left)
        data["bottom_right"] = _point_tuple(roi.bottom_right)
    elif isinstance(roi, CircleROI):
        data["center"] = _point_tuple(roi.center)
        data["radius"] = int(roi.radius)
    elif isinstance(roi, EllipseROI):
        data["center"] = _point_tuple(roi.center)
        data["radius_x"] = int(roi.radius_x)
        data["radius_y"] = int(roi.radius_y)
    else:
        raise ValueError(f"Unsupported ROI type: {type(roi).__name__}")

    return data


def _deserialize_roi(data: dict[str, Any]) -> BaseROI:
    roi_type = str(data.get("type", ""))
    slice_index = int(data["slice_index"])

    if roi_type == "Rectangle":
        roi = RectangleROI(
            _as_int_tuple(data["top_left"], 2),
            _as_int_tuple(data["bottom_right"], 2),
            slice_index,
        )
    elif roi_type == "Circle":
        roi = CircleROI(
            _as_int_tuple(data["center"], 2),
            int(data["radius"]),
            slice_index,
        )
    elif roi_type == "Ellipse":
        roi = EllipseROI(
            _as_int_tuple(data["center"], 2),
            int(data["radius_x"]),
            int(data["radius_y"]),
            slice_index,
        )
    else:
        raise ValueError(f"Unsupported ROI type in annotation file: {roi_type}")

    roi.id = str(data.get("id", roi.id))
    roi.selected = False
    roi.show_stats = bool(data.get("show_stats", True))
    return roi


def _serialize_measurement(measurement: MeasurementData) -> dict[str, Any]:
    return {
        "id": measurement.id,
        "slice_index": measurement.slice_index,
        "start_point": _qt_point(measurement.start_point),
        "end_point": _qt_point(measurement.end_point),
        "distance": float(measurement.distance),
        "unit": measurement.unit,
    }


def _deserialize_measurement(data: dict[str, Any]) -> MeasurementData:
    return MeasurementData(
        id=str(data["id"]),
        slice_index=int(data["slice_index"]),
        start_point=_as_qpoint(data["start_point"]),
        end_point=_as_qpoint(data["end_point"]),
        distance=float(data["distance"]),
        unit=str(data.get("unit", "mm")),
    )


def _serialize_angle_measurement(measurement: AngleMeasurementData) -> dict[str, Any]:
    return {
        "id": measurement.id,
        "slice_index": measurement.slice_index,
        "point1": _qt_point(measurement.point1),
        "vertex": _qt_point(measurement.vertex),
        "point3": _qt_point(measurement.point3),
        "angle_degrees": float(measurement.angle_degrees),
    }


def _deserialize_angle_measurement(data: dict[str, Any]) -> AngleMeasurementData:
    return AngleMeasurementData(
        id=str(data["id"]),
        slice_index=int(data["slice_index"]),
        point1=_as_qpoint(data["point1"]),
        vertex=_as_qpoint(data["vertex"]),
        point3=_as_qpoint(data["point3"]),
        angle_degrees=float(data["angle_degrees"]),
    )


def _load_document(source: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(source, dict):
        return source

    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_document(document: dict[str, Any]) -> None:
    if not isinstance(document, dict):
        raise AnnotationImportError("Invalid annotation file: expected an object.")
    if document.get("schema") != "medimager.annotations":
        raise AnnotationImportError("Not a MedImager annotation file.")
    try:
        version = int(document.get("schema_version", 0))
    except (TypeError, ValueError) as error:
        raise AnnotationImportError("Invalid annotation schema version.") from error
    if version != ANNOTATION_SCHEMA_VERSION:
        raise AnnotationImportError(
            "Unsupported annotation schema version: "
            f"{document.get('schema_version')}"
        )
    if not isinstance(document.get("annotations"), dict):
        raise AnnotationImportError("Invalid annotation file: missing annotations object.")


def _series_identity_mismatches(
    model: ImageDataModel, source_identity: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    target_identity = _series_identity(model)
    mismatches: dict[str, tuple[str, str]] = {}
    for field in ("patient_id", "study_instance_uid", "series_instance_uid"):
        source_value = _normalize_identity(source_identity.get(field, ""))
        target_value = _normalize_identity(target_identity.get(field, ""))
        if source_value != target_value:
            mismatches[field] = (source_value or "<missing>", target_value or "<missing>")
    return mismatches


def _normalize_identity(value: Any) -> str:
    return str(value or "").strip()


def _deserialize_items(
    annotations: dict[str, Any], key: str, loader
) -> list[Any]:
    raw_items = annotations.get(key, [])
    if not isinstance(raw_items, list):
        raise InvalidAnnotationError(f"Invalid annotations.{key}: expected a list.")

    items = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise InvalidAnnotationError(
                f"Invalid {key} item at index {index}: expected an object."
            )
        try:
            items.append(loader(raw_item))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise InvalidAnnotationError(
                f"Invalid {key} item at index {index}: {error}"
            ) from error
    return items


def _validate_annotation_items(
    model: ImageDataModel,
    source_identity: dict[str, Any],
    rois: list[BaseROI],
    measurements: list[MeasurementData],
    angle_measurements: list[AngleMeasurementData],
    *,
    replace: bool,
) -> None:
    target_slice_count = model.get_slice_count()
    try:
        source_slice_count = int(source_identity.get("slice_count", 0))
    except (TypeError, ValueError, OverflowError) as error:
        raise InvalidAnnotationError("Invalid series.slice_count.") from error
    if source_slice_count < 0:
        raise InvalidAnnotationError("Invalid series.slice_count: must be non-negative.")
    imported_item_count = len(rois) + len(measurements) + len(angle_measurements)
    if imported_item_count and source_slice_count == 0:
        raise InvalidAnnotationError(
            "Invalid series.slice_count: a non-empty annotation document must "
            "identify its source volume bounds."
        )

    collections = (
        ("ROI", rois),
        ("measurement", measurements),
        ("angle measurement", angle_measurements),
    )
    for label, items in collections:
        _validate_unique_ids(label, items)
        for item in items:
            slice_index = item.slice_index
            if slice_index < 0:
                raise InvalidAnnotationError(
                    f"Invalid {label} {item.id}: negative slice index {slice_index}."
                )
            if source_slice_count and slice_index >= source_slice_count:
                raise InvalidAnnotationError(
                    f"Invalid {label} {item.id}: slice {slice_index} is outside "
                    f"the source volume ({source_slice_count} slices)."
                )
            if slice_index >= target_slice_count:
                raise InvalidAnnotationError(
                    f"Invalid {label} {item.id}: slice {slice_index} is outside "
                    f"the target volume ({target_slice_count} slices)."
                )

    for roi in rois:
        if isinstance(roi, CircleROI) and roi.radius <= 0:
            raise InvalidAnnotationError(f"Invalid ROI {roi.id}: radius must be positive.")
        if isinstance(roi, EllipseROI) and (
            roi.radius_x <= 0 or roi.radius_y <= 0
        ):
            raise InvalidAnnotationError(
                f"Invalid ROI {roi.id}: ellipse radii must be positive."
            )

    for measurement in measurements:
        if not math.isfinite(measurement.distance) or measurement.distance < 0:
            raise InvalidAnnotationError(
                f"Invalid measurement {measurement.id}: distance must be finite and non-negative."
            )
    for measurement in angle_measurements:
        if not math.isfinite(measurement.angle_degrees) or not (
            0.0 <= measurement.angle_degrees <= 180.0
        ):
            raise InvalidAnnotationError(
                f"Invalid angle measurement {measurement.id}: angle must be between 0 and 180 degrees."
            )

    if not replace:
        _validate_no_merge_id_conflicts("ROI", model.rois, rois)
        _validate_no_merge_id_conflicts(
            "measurement", model.measurements, measurements
        )
        _validate_no_merge_id_conflicts(
            "angle measurement", model.angle_measurements, angle_measurements
        )


def _validate_unique_ids(label: str, items: list[Any]) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = str(getattr(item, "id", "")).strip()
        if not item_id:
            raise InvalidAnnotationError(f"Invalid {label}: id must not be empty.")
        if item_id in seen:
            raise InvalidAnnotationError(f"Duplicate {label} id: {item_id}.")
        seen.add(item_id)


def _validate_no_merge_id_conflicts(
    label: str, existing_items: list[Any], imported_items: list[Any]
) -> None:
    existing_ids = {str(item.id) for item in existing_items}
    conflicts = sorted(existing_ids.intersection(str(item.id) for item in imported_items))
    if conflicts:
        raise InvalidAnnotationError(
            f"Cannot merge duplicate {label} id(s): {', '.join(conflicts)}."
        )


def _annotation_signature(model: ImageDataModel) -> str:
    annotations = export_annotations(model)["annotations"]
    return json.dumps(
        annotations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _point_tuple(value: tuple[int, int]) -> list[int]:
    return [int(value[0]), int(value[1])]


def _qt_point(point: QPointF) -> list[float]:
    return [float(point.x()), float(point.y())]


def _as_qpoint(value: Any) -> QPointF:
    x, y = _as_float_tuple(value, 2)
    return QPointF(x, y)


def _as_int_tuple(value: Any, length: int) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"Expected a {length}-item coordinate.")
    return tuple(int(item) for item in value)


def _as_float_tuple(value: Any, length: int) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"Expected a {length}-item point.")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("Point coordinates must be finite.")
    return result
