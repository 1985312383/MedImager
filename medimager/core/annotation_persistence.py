"""Versioned JSON persistence for viewport annotations."""

from __future__ import annotations

import json
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
    """Write the model annotations to a UTF-8 JSON file."""
    path = Path(file_path)
    path.write_text(
        json.dumps(export_annotations(model), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def import_annotations(
    model: ImageDataModel,
    source: dict[str, Any] | str | Path,
    *,
    replace: bool = True,
) -> dict[str, int]:
    """
    Load annotations into a model.

    Returns import counts for UI messages and tests.
    """
    document = _load_document(source)
    _validate_document(document)
    annotations = document.get("annotations", {})

    rois = [_deserialize_roi(item) for item in annotations.get("rois", [])]
    measurements = [
        _deserialize_measurement(item) for item in annotations.get("measurements", [])
    ]
    angle_measurements = [
        _deserialize_angle_measurement(item)
        for item in annotations.get("angle_measurements", [])
    ]

    if replace:
        model.rois.clear()
        model.selected_indices.clear()
        model.measurements.clear()
        model.selected_measurement_indices.clear()
        model.angle_measurements.clear()

    model.rois.extend(rois)
    model.measurements.extend(measurements)
    model.angle_measurements.extend(angle_measurements)
    model.data_changed.emit()

    return {
        "rois": len(rois),
        "measurements": len(measurements),
        "angle_measurements": len(angle_measurements),
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
    if document.get("schema") != "medimager.annotations":
        raise ValueError("Not a MedImager annotation file.")
    if int(document.get("schema_version", 0)) != ANNOTATION_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported annotation schema version: "
            f"{document.get('schema_version')}"
        )
    if not isinstance(document.get("annotations"), dict):
        raise ValueError("Invalid annotation file: missing annotations object.")


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
    return tuple(float(item) for item in value)
