"""DICOM LPS conversion helpers for annotation schema v2."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF

from medimager.core.image_data_model import AngleMeasurementData, MeasurementData
from medimager.core.roi import BaseROI, CircleROI, EllipseROI, RectangleROI


def plane_for_slice(model, slice_index: int) -> dict[str, list[float]]:
    metadata = model.get_slice_metadata(slice_index)
    position = _vector(metadata.get("ImagePositionPatient"), 3)
    orientation = _vector(metadata.get("ImageOrientationPatient"), 6)
    spacing = model.get_pixel_spacing(slice_index)
    if position is None:
        position = np.asarray((0.0, 0.0, float(slice_index)), dtype=np.float64)
    if orientation is None:
        orientation = np.asarray((1.0, 0.0, 0.0, 0.0, 1.0, 0.0), dtype=np.float64)
    if spacing is None:
        spacing = (1.0, 1.0)
    column_axis = _normalise(orientation[:3])
    row_axis = _normalise(orientation[3:])
    normal = _normalise(np.cross(column_axis, row_axis))
    return {
        "origin_lps": position.tolist(),
        "column_axis_lps": column_axis.tolist(),
        "row_axis_lps": row_axis.tolist(),
        "normal_lps": normal.tolist(),
        "pixel_spacing_rc": [float(spacing[0]), float(spacing[1])],
    }


def serialize_roi_lps(model, roi: BaseROI) -> dict[str, Any]:
    stored = _stored_patient_geometry(roi)
    plane = stored[0] if stored else plane_for_slice(model, roi.slice_index)
    data = {
        "id": roi.id,
        "type": roi.shape.value,
        "plane": plane,
        "show_stats": bool(getattr(roi, "show_stats", True)),
    }
    if isinstance(roi, RectangleROI):
        points = {
            "top_left": pixel_to_lps(plane, QPointF(roi.top_left[1], roi.top_left[0])),
            "bottom_right": pixel_to_lps(plane, QPointF(roi.bottom_right[1], roi.bottom_right[0])),
        }
    elif isinstance(roi, CircleROI):
        center = roi.center
        points = {
            "center": pixel_to_lps(plane, QPointF(center[1], center[0])),
            "radius_edge": pixel_to_lps(plane, QPointF(center[1] + roi.radius, center[0])),
        }
    elif isinstance(roi, EllipseROI):
        center = roi.center
        points = {
            "center": pixel_to_lps(plane, QPointF(center[1], center[0])),
            "radius_x_edge": pixel_to_lps(plane, QPointF(center[1] + roi.radius_x, center[0])),
            "radius_y_edge": pixel_to_lps(plane, QPointF(center[1], center[0] + roi.radius_y)),
        }
    else:
        raise ValueError(f"Unsupported ROI type: {type(roi).__name__}")
    data["points_lps"] = stored[1] if stored else points
    return data


def deserialize_roi_lps(model, data: dict[str, Any]) -> BaseROI:
    roi_type = str(data.get("type", ""))
    if roi_type not in {"Rectangle", "Circle", "Ellipse"}:
        raise ValueError(f"Unsupported ROI type in annotation file: {roi_type}")
    points = _points(data)
    first_point = next(iter(points.values()))
    index, _ = patient_to_target_pixel(model, first_point)
    projected = {key: patient_to_pixel_on_slice(model, value, index) for key, value in points.items()}
    if roi_type == "Rectangle":
        roi = RectangleROI(_round_rc(projected["top_left"]), _round_rc(projected["bottom_right"]), index)
    elif roi_type == "Circle":
        center = projected["center"]
        radius = max(1, int(round(math.dist(center, projected["radius_edge"]))))
        roi = CircleROI(_round_rc(center), radius, index)
    else:
        center = projected["center"]
        roi = EllipseROI(
            _round_rc(center),
            max(1, int(round(math.dist(center, projected["radius_x_edge"])))),
            max(1, int(round(math.dist(center, projected["radius_y_edge"])))),
            index,
        )
    roi.id = str(data.get("id", roi.id))
    roi.selected = False
    roi.show_stats = bool(data.get("show_stats", True))
    _retain_patient_geometry(roi, data, points)
    return roi


def serialize_measurement_lps(model, item: MeasurementData) -> dict[str, Any]:
    stored = _stored_patient_geometry(item)
    plane = stored[0] if stored else plane_for_slice(model, item.slice_index)
    return {
        "id": item.id,
        "plane": plane,
        "points_lps": stored[1] if stored else {
            "start": pixel_to_lps(plane, item.start_point),
            "end": pixel_to_lps(plane, item.end_point),
        },
        "distance": float(item.distance),
        "unit": item.unit,
    }


def deserialize_measurement_lps(model, data: dict[str, Any]) -> MeasurementData:
    points = _points(data)
    index, _ = patient_to_target_pixel(model, points["start"])
    start = patient_to_pixel_on_slice(model, points["start"], index)
    end = patient_to_pixel_on_slice(model, points["end"], index)
    item = MeasurementData(
        id=str(data["id"]),
        slice_index=index,
        start_point=QPointF(*start),
        end_point=QPointF(*end),
        distance=float(data["distance"]),
        unit=str(data.get("unit", "mm")),
    )
    _retain_patient_geometry(item, data, points)
    return item


def serialize_angle_lps(model, item: AngleMeasurementData) -> dict[str, Any]:
    stored = _stored_patient_geometry(item)
    plane = stored[0] if stored else plane_for_slice(model, item.slice_index)
    return {
        "id": item.id,
        "plane": plane,
        "points_lps": stored[1] if stored else {
            "point1": pixel_to_lps(plane, item.point1),
            "vertex": pixel_to_lps(plane, item.vertex),
            "point3": pixel_to_lps(plane, item.point3),
        },
        "angle_degrees": float(item.angle_degrees),
    }


def deserialize_angle_lps(model, data: dict[str, Any]) -> AngleMeasurementData:
    points = _points(data)
    index, _ = patient_to_target_pixel(model, points["vertex"])
    point1 = patient_to_pixel_on_slice(model, points["point1"], index)
    vertex = patient_to_pixel_on_slice(model, points["vertex"], index)
    point3 = patient_to_pixel_on_slice(model, points["point3"], index)
    item = AngleMeasurementData(
        id=str(data["id"]),
        slice_index=index,
        point1=QPointF(*point1),
        vertex=QPointF(*vertex),
        point3=QPointF(*point3),
        angle_degrees=float(data["angle_degrees"]),
    )
    _retain_patient_geometry(item, data, points)
    return item


def pixel_to_lps(plane: dict[str, Any], point: Any) -> list[float]:
    x, y = _xy(point)
    origin = np.asarray(plane["origin_lps"], dtype=np.float64)
    column = np.asarray(plane["column_axis_lps"], dtype=np.float64)
    row = np.asarray(plane["row_axis_lps"], dtype=np.float64)
    row_spacing, column_spacing = plane["pixel_spacing_rc"]
    value = origin + column * x * column_spacing + row * y * row_spacing
    return [float(component) for component in value]


def patient_to_target_pixel(model, point_lps: Any) -> tuple[int, tuple[float, float]]:
    point = np.asarray(_tuple(point_lps, 3), dtype=np.float64)
    candidates = []
    for index in range(model.get_slice_count()):
        plane = plane_for_slice(model, index)
        origin = np.asarray(plane["origin_lps"], dtype=np.float64)
        normal = np.asarray(plane["normal_lps"], dtype=np.float64)
        candidates.append((abs(float(np.dot(point - origin, normal))), index, plane))
    if not candidates:
        raise ValueError("Target series has no slices")
    _, index, plane = min(candidates, key=lambda item: item[0])
    delta = point - np.asarray(plane["origin_lps"], dtype=np.float64)
    row_spacing, column_spacing = plane["pixel_spacing_rc"]
    x = float(np.dot(delta, plane["column_axis_lps"]) / column_spacing)
    y = float(np.dot(delta, plane["row_axis_lps"]) / row_spacing)
    shape = model.get_image_shape()
    height, width = int(shape[-2]), int(shape[-1])
    # Control handles may legitimately extend just outside the image, but
    # reject coordinates that are clearly unrelated to this volume.
    margin = max(height, width) * 4.0
    if not (-margin <= x <= width - 1 + margin and -margin <= y <= height - 1 + margin):
        raise ValueError("Patient-space annotation point lies outside the target image")
    return index, (x, y)



def patient_to_pixel_on_slice(model, point_lps: Any, slice_index: int) -> tuple[float, float]:
    point = np.asarray(_tuple(point_lps, 3), dtype=np.float64)
    plane = plane_for_slice(model, slice_index)
    delta = point - np.asarray(plane["origin_lps"], dtype=np.float64)
    row_spacing, column_spacing = plane["pixel_spacing_rc"]
    return (
        float(np.dot(delta, plane["column_axis_lps"]) / column_spacing),
        float(np.dot(delta, plane["row_axis_lps"]) / row_spacing),
    )


def _stored_patient_geometry(item) -> tuple[dict[str, Any], dict[str, list[float]]] | None:
    plane = getattr(item, "creation_plane", None)
    points = getattr(item, "points_lps", None)
    if not isinstance(plane, dict) or not isinstance(points, dict):
        return None
    validated = {str(key): list(_tuple(value, 3)) for key, value in points.items()}
    return plane, validated


def _retain_patient_geometry(item, data: dict[str, Any], points) -> None:
    plane = data.get("plane")
    if not isinstance(plane, dict):
        raise ValueError("Missing annotation creation plane")
    item.creation_plane = plane
    item.points_lps = {key: list(value) for key, value in points.items()}

def _points(data: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    raw = data.get("points_lps")
    if not isinstance(raw, dict):
        raise ValueError("Missing points_lps patient-space coordinates")
    return {str(key): _tuple(value, 3) for key, value in raw.items()}


def _vector(value: Any, length: int) -> np.ndarray | None:
    try:
        if value is None or len(value) < length:
            return None
        result = np.asarray([float(item) for item in value[:length]], dtype=np.float64)
        return result if np.all(np.isfinite(result)) else None
    except (TypeError, ValueError, IndexError):
        return None


def _normalise(value: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(value))
    if not np.isfinite(length) or length <= 1e-8:
        raise ValueError("Invalid annotation plane direction")
    return np.asarray(value, dtype=np.float64) / length


def _tuple(value: Any, length: int) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) != length:
        raise ValueError(f"Expected a {length}-item patient-space coordinate")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("Patient-space coordinates must be finite")
    return result


def _xy(point: Any) -> tuple[float, float]:
    if isinstance(point, QPointF):
        return float(point.x()), float(point.y())
    return float(point[0]), float(point[1])


def _round(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[0])), int(round(point[1]))


def _round_rc(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[1])), int(round(point[0]))


def _same_slice(first: int, second: int) -> None:
    if first != second:
        raise ValueError("Annotation control points do not lie on one target slice")
