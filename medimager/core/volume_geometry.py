"""Patient-space volume geometry and orthogonal MPR reconstruction.

The public types in this module deliberately contain no Qt or SimpleITK
objects.  DICOM geometry is represented in LPS millimetres and NumPy arrays
always use ``(z, y, x)`` order.  SimpleITK is an implementation detail of the
resampler and is imported lazily so normal 2-D viewing remains available when
the optional runtime is damaged or missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event
from typing import Callable, Optional, Sequence

import numpy as np


class GeometryStatus(str, Enum):
    COMPATIBLE = "compatible"
    EMPTY = "empty"
    UNSUPPORTED_MODALITY = "unsupported_modality"
    COLOR = "color"
    MISSING_GEOMETRY = "missing_geometry"
    INVALID_GEOMETRY = "invalid_geometry"
    INCONSISTENT_ORIENTATION = "inconsistent_orientation"
    INCONSISTENT_PIXEL_SPACING = "inconsistent_pixel_spacing"
    INCONSISTENT_FRAME_OF_REFERENCE = "inconsistent_frame_of_reference"
    DUPLICATE_SLICES = "duplicate_slices"
    NON_UNIFORM_SPACING = "non_uniform_spacing"
    GANTRY_TILT = "gantry_tilt"
    MULTI_STACK = "multi_stack"
    MULTI_TEMPORAL = "multi_temporal"
    MEMORY_LIMIT = "memory_limit"
    CANCELLED = "cancelled"
    DECODE_ERROR = "decode_error"
    RESAMPLER_UNAVAILABLE = "resampler_unavailable"


class MprPlane(str, Enum):
    AXIAL = "axial"
    CORONAL = "coronal"
    SAGITTAL = "sagittal"


@dataclass(frozen=True)
class FrameGeometry:
    """Geometry for one decoded frame in DICOM LPS patient coordinates."""

    index: int
    origin_lps: tuple[float, float, float]
    column_axis_lps: tuple[float, float, float]
    row_axis_lps: tuple[float, float, float]
    normal_lps: tuple[float, float, float]
    pixel_spacing_rc: tuple[float, float]
    frame_of_reference_uid: str

    def pixel_to_patient(self, column: float, row: float) -> np.ndarray:
        origin = np.asarray(self.origin_lps, dtype=np.float64)
        column_axis = np.asarray(self.column_axis_lps, dtype=np.float64)
        row_axis = np.asarray(self.row_axis_lps, dtype=np.float64)
        row_spacing, column_spacing = self.pixel_spacing_rc
        return (
            origin
            + column_axis * float(column) * column_spacing
            + row_axis * float(row) * row_spacing
        )


@dataclass(frozen=True)
class VolumeGeometry:
    """Regular three-dimensional lattice in LPS coordinates."""

    origin_lps: tuple[float, float, float]
    direction: tuple[float, ...]
    spacing_xyz: tuple[float, float, float]
    shape_zyx: tuple[int, int, int]
    frame_of_reference_uid: str
    source_frame_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.direction) != 9:
            raise ValueError("direction must contain a row-major 3x3 matrix")
        if len(self.shape_zyx) != 3 or any(value <= 0 for value in self.shape_zyx):
            raise ValueError("shape_zyx must contain three positive dimensions")
        if any(not np.isfinite(value) or value <= 0 for value in self.spacing_xyz):
            raise ValueError("spacing_xyz must contain finite positive values")

    @property
    def direction_matrix(self) -> np.ndarray:
        return np.asarray(self.direction, dtype=np.float64).reshape(3, 3)

    @property
    def voxel_to_patient_affine(self) -> np.ndarray:
        affine = np.eye(4, dtype=np.float64)
        affine[:3, :3] = self.direction_matrix @ np.diag(self.spacing_xyz)
        affine[:3, 3] = np.asarray(self.origin_lps, dtype=np.float64)
        return affine

    @property
    def patient_to_voxel_affine(self) -> np.ndarray:
        return np.linalg.inv(self.voxel_to_patient_affine)

    def voxel_to_patient(self, column: float, row: float, slice_index: float) -> np.ndarray:
        point = self.voxel_to_patient_affine @ np.asarray(
            [column, row, slice_index, 1.0], dtype=np.float64
        )
        return point[:3]

    def patient_to_voxel(self, point_lps: Sequence[float]) -> np.ndarray:
        point = self.patient_to_voxel_affine @ np.asarray(
            [*point_lps[:3], 1.0], dtype=np.float64
        )
        return point[:3]

    @property
    def patient_bounds(self) -> tuple[tuple[float, float], ...]:
        depth, height, width = self.shape_zyx
        corners = [
            self.voxel_to_patient(x, y, z)
            for x in (0, width - 1)
            for y in (0, height - 1)
            for z in (0, depth - 1)
        ]
        values = np.asarray(corners, dtype=np.float64)
        return tuple((float(values[:, axis].min()), float(values[:, axis].max())) for axis in range(3))

    @property
    def center_lps(self) -> tuple[float, float, float]:
        depth, height, width = self.shape_zyx
        point = self.voxel_to_patient((width - 1) / 2, (height - 1) / 2, (depth - 1) / 2)
        return tuple(float(value) for value in point)


@dataclass(frozen=True)
class VolumeData:
    pixels_zyx: np.ndarray
    geometry: VolumeGeometry
    modality: str
    series_instance_uid: str

    def __post_init__(self) -> None:
        if self.pixels_zyx.ndim != 3:
            raise ValueError("VolumeData requires a three-dimensional array")
        if tuple(self.pixels_zyx.shape) != self.geometry.shape_zyx:
            raise ValueError("pixel volume shape does not match VolumeGeometry")


@dataclass(frozen=True)
class VolumeBuildResult:
    status: GeometryStatus
    volume: Optional[VolumeData] = None
    detail: str = ""
    estimated_bytes: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def compatible(self) -> bool:
        return self.status is GeometryStatus.COMPATIBLE


@dataclass(frozen=True)
class PlaneGeometry:
    plane: MprPlane
    origin_lps: tuple[float, float, float]
    u_axis_lps: tuple[float, float, float]
    v_axis_lps: tuple[float, float, float]
    normal_lps: tuple[float, float, float]
    spacing_uv: tuple[float, float]
    shape_hw: tuple[int, int]

    def pixel_to_patient(self, column: float, row: float) -> np.ndarray:
        return (
            np.asarray(self.origin_lps, dtype=np.float64)
            + np.asarray(self.u_axis_lps, dtype=np.float64) * float(column) * self.spacing_uv[0]
            + np.asarray(self.v_axis_lps, dtype=np.float64) * float(row) * self.spacing_uv[1]
        )

    def patient_to_pixel(self, point_lps: Sequence[float]) -> tuple[float, float]:
        delta = np.asarray(point_lps[:3], dtype=np.float64) - np.asarray(self.origin_lps)
        u = float(np.dot(delta, self.u_axis_lps) / self.spacing_uv[0])
        v = float(np.dot(delta, self.v_axis_lps) / self.spacing_uv[1])
        return u, v


@dataclass(frozen=True)
class ResampledPlane:
    pixels: np.ndarray
    geometry: PlaneGeometry


class VolumeBuilder:
    """Validate a loaded ImageDataModel and materialise a regular volume."""

    ORIENTATION_ATOL = 1e-4
    SPACING_ATOL_MM = 1e-2
    SPACING_RTOL = 1e-2
    TILT_ATOL_MM = 0.1

    @classmethod
    def inspect(cls, model, *, memory_budget_bytes: Optional[int] = None) -> VolumeBuildResult:
        return cls._build(model, materialise=False, memory_budget_bytes=memory_budget_bytes)

    @classmethod
    def build(
        cls,
        model,
        *,
        cancel_event: Optional[Event] = None,
        progress: Optional[Callable[[int, int], None]] = None,
        memory_budget_bytes: Optional[int] = None,
    ) -> VolumeBuildResult:
        return cls._build(
            model,
            materialise=True,
            cancel_event=cancel_event,
            progress=progress,
            memory_budget_bytes=memory_budget_bytes,
        )

    @classmethod
    def _failure(cls, status: GeometryStatus, detail: str, estimated_bytes: int = 0) -> VolumeBuildResult:
        return VolumeBuildResult(status=status, detail=detail, estimated_bytes=estimated_bytes)

    @classmethod
    def _build(
        cls,
        model,
        *,
        materialise: bool,
        cancel_event: Optional[Event] = None,
        progress: Optional[Callable[[int, int], None]] = None,
        memory_budget_bytes: Optional[int] = None,
    ) -> VolumeBuildResult:
        slice_count = int(getattr(model, "get_slice_count", lambda: 0)())
        if slice_count < 2:
            return cls._failure(GeometryStatus.EMPTY, "mpr.requires_multiple_slices")
        modality = str(model.get_metadata("Modality", "")).upper()
        if modality not in {"CT", "MR"}:
            return cls._failure(GeometryStatus.UNSUPPORTED_MODALITY, "mpr.unsupported_modality")
        if str(getattr(model, "image_mode", "")).startswith("rgb"):
            return cls._failure(GeometryStatus.COLOR, "mpr.color_not_supported")

        datasets = [model.get_dicom_file(index) for index in range(slice_count)]
        if any(dataset is None for dataset in datasets):
            return cls._failure(GeometryStatus.MISSING_GEOMETRY, "mpr.missing_geometry")
        if any(
            int(getattr(dataset, "SamplesPerPixel", 1) or 1) != 1
            or not str(getattr(dataset, "PhotometricInterpretation", "MONOCHROME2"))
            .upper()
            .startswith("MONOCHROME")
            for dataset in datasets
        ):
            return cls._failure(GeometryStatus.COLOR, "mpr.color_not_supported")

        temporal_values = {
            str(getattr(dataset, "TemporalPositionIndex", getattr(dataset, "TemporalPositionIdentifier", "")) or "")
            for dataset in datasets
        }
        if len(temporal_values) > 1:
            return cls._failure(GeometryStatus.MULTI_TEMPORAL, "mpr.multi_temporal")
        stack_values = {str(getattr(dataset, "StackID", "") or "") for dataset in datasets}
        if len(stack_values) > 1:
            return cls._failure(GeometryStatus.MULTI_STACK, "mpr.multi_stack")

        frames: list[FrameGeometry] = []
        rows = cols = None
        for index, dataset in enumerate(datasets):
            try:
                position = cls._finite_vector(getattr(dataset, "ImagePositionPatient", None), 3)
                orientation = cls._finite_vector(getattr(dataset, "ImageOrientationPatient", None), 6)
                spacing = cls._finite_vector(getattr(dataset, "PixelSpacing", None), 2)
                if position is None or orientation is None or spacing is None or np.any(spacing <= 0):
                    return cls._failure(GeometryStatus.MISSING_GEOMETRY, "mpr.missing_geometry")
                column_axis = cls._normalise(orientation[:3])
                row_axis = cls._normalise(orientation[3:])
                if abs(float(np.dot(column_axis, row_axis))) > 1e-4:
                    return cls._failure(GeometryStatus.INVALID_GEOMETRY, "mpr.invalid_orientation")
                normal = cls._normalise(np.cross(column_axis, row_axis))
                current_rows = int(getattr(dataset, "Rows", model.get_image_shape()[-2]))
                current_cols = int(getattr(dataset, "Columns", model.get_image_shape()[-1]))
                frame_uid = str(getattr(dataset, "FrameOfReferenceUID", "") or "")
                if current_rows <= 0 or current_cols <= 0 or not frame_uid:
                    return cls._failure(GeometryStatus.MISSING_GEOMETRY, "mpr.missing_geometry")
                if rows is None:
                    rows, cols = current_rows, current_cols
                elif (rows, cols) != (current_rows, current_cols):
                    return cls._failure(GeometryStatus.INVALID_GEOMETRY, "mpr.inconsistent_dimensions")
                frames.append(
                    FrameGeometry(
                        index=index,
                        origin_lps=tuple(float(value) for value in position),
                        column_axis_lps=tuple(float(value) for value in column_axis),
                        row_axis_lps=tuple(float(value) for value in row_axis),
                        normal_lps=tuple(float(value) for value in normal),
                        pixel_spacing_rc=(float(spacing[0]), float(spacing[1])),
                        frame_of_reference_uid=frame_uid,
                    )
                )
            except (TypeError, ValueError, OverflowError):
                return cls._failure(GeometryStatus.INVALID_GEOMETRY, "mpr.invalid_geometry")

        reference = frames[0]
        reference_column = np.asarray(reference.column_axis_lps)
        reference_row = np.asarray(reference.row_axis_lps)
        reference_normal = np.asarray(reference.normal_lps)
        reference_spacing = np.asarray(reference.pixel_spacing_rc)
        for frame in frames[1:]:
            if frame.frame_of_reference_uid != reference.frame_of_reference_uid:
                return cls._failure(
                    GeometryStatus.INCONSISTENT_FRAME_OF_REFERENCE,
                    "mpr.inconsistent_frame_of_reference",
                )
            if not (
                np.allclose(frame.column_axis_lps, reference_column, atol=cls.ORIENTATION_ATOL)
                and np.allclose(frame.row_axis_lps, reference_row, atol=cls.ORIENTATION_ATOL)
            ):
                return cls._failure(GeometryStatus.INCONSISTENT_ORIENTATION, "mpr.inconsistent_orientation")
            if not np.allclose(
                frame.pixel_spacing_rc,
                reference_spacing,
                atol=cls.SPACING_ATOL_MM,
                rtol=cls.SPACING_RTOL,
            ):
                return cls._failure(GeometryStatus.INCONSISTENT_PIXEL_SPACING, "mpr.inconsistent_pixel_spacing")

        origins = np.asarray([frame.origin_lps for frame in frames], dtype=np.float64)
        projections = origins @ reference_normal
        order = np.argsort(projections, kind="stable")
        projections = projections[order]
        origins = origins[order]
        frames = [frames[int(index)] for index in order]
        differences = np.diff(projections)
        if np.any(np.abs(differences) <= 1e-6):
            return cls._failure(GeometryStatus.DUPLICATE_SLICES, "mpr.duplicate_slices")
        slice_spacing = float(np.median(differences))
        if slice_spacing <= 0:
            return cls._failure(GeometryStatus.INVALID_GEOMETRY, "mpr.invalid_slice_spacing")
        if not np.allclose(
            differences,
            slice_spacing,
            atol=cls.SPACING_ATOL_MM,
            rtol=cls.SPACING_RTOL,
        ):
            return cls._failure(GeometryStatus.NON_UNIFORM_SPACING, "mpr.non_uniform_spacing")

        expected = origins[0] + np.outer(projections - projections[0], reference_normal)
        lateral_residual = np.linalg.norm(origins - expected, axis=1)
        if np.any(lateral_residual > cls.TILT_ATOL_MM):
            return cls._failure(GeometryStatus.GANTRY_TILT, "mpr.gantry_tilt")

        assert rows is not None and cols is not None
        estimated_bytes = int(slice_count * rows * cols * np.dtype(np.float32).itemsize)
        if memory_budget_bytes is not None and estimated_bytes > int(memory_budget_bytes):
            return cls._failure(GeometryStatus.MEMORY_LIMIT, "mpr.memory_limit", estimated_bytes)

        direction_matrix = np.column_stack((reference_column, reference_row, reference_normal))
        geometry = VolumeGeometry(
            origin_lps=tuple(float(value) for value in origins[0]),
            direction=tuple(float(value) for value in direction_matrix.reshape(-1)),
            spacing_xyz=(float(reference_spacing[1]), float(reference_spacing[0]), slice_spacing),
            shape_zyx=(slice_count, rows, cols),
            frame_of_reference_uid=reference.frame_of_reference_uid,
            source_frame_indices=tuple(frame.index for frame in frames),
        )
        if not materialise:
            return VolumeBuildResult(
                status=GeometryStatus.COMPATIBLE,
                detail="mpr.compatible",
                estimated_bytes=estimated_bytes,
                warnings=(),
            )

        volume = np.empty(geometry.shape_zyx, dtype=np.float32)
        try:
            for target_index, frame in enumerate(frames):
                if cancel_event is not None and cancel_event.is_set():
                    return cls._failure(GeometryStatus.CANCELLED, "mpr.cancelled", estimated_bytes)
                pixels = model.get_slice_data(frame.index)
                if pixels is None or np.asarray(pixels).shape != (rows, cols):
                    return cls._failure(GeometryStatus.DECODE_ERROR, "mpr.decode_error", estimated_bytes)
                volume[target_index] = np.asarray(pixels, dtype=np.float32)
                if progress is not None:
                    progress(target_index + 1, slice_count)
        except Exception:
            return cls._failure(GeometryStatus.DECODE_ERROR, "mpr.decode_error", estimated_bytes)

        volume.setflags(write=False)
        return VolumeBuildResult(
            status=GeometryStatus.COMPATIBLE,
            volume=VolumeData(
                pixels_zyx=volume,
                geometry=geometry,
                modality=modality,
                series_instance_uid=str(model.get_metadata("SeriesInstanceUID", "") or ""),
            ),
            detail="mpr.compatible",
            estimated_bytes=estimated_bytes,
        )

    @staticmethod
    def _finite_vector(value, length: int) -> Optional[np.ndarray]:
        try:
            if value is None or len(value) < length:
                return None
            result = np.asarray([float(item) for item in value[:length]], dtype=np.float64)
            return result if np.all(np.isfinite(result)) else None
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _normalise(value: np.ndarray) -> np.ndarray:
        length = float(np.linalg.norm(value))
        if not np.isfinite(length) or length <= 1e-8:
            raise ValueError("zero direction vector")
        return np.asarray(value, dtype=np.float64) / length


class OrthogonalMprResampler:
    """On-demand patient-aligned orthogonal plane reconstruction."""

    def __init__(self, volume: VolumeData) -> None:
        self.volume = volume
        try:
            import SimpleITK as sitk
        except ImportError as error:  # pragma: no cover - exercised in packaged smoke tests
            raise RuntimeError("mpr.resampler_unavailable") from error
        self._sitk = sitk
        image = sitk.GetImageFromArray(volume.pixels_zyx, isVector=False)
        image.SetOrigin(volume.geometry.origin_lps)
        image.SetSpacing(volume.geometry.spacing_xyz)
        image.SetDirection(volume.geometry.direction)
        self._image = image
        self._bounds = volume.geometry.patient_bounds
        self._sampling = min(volume.geometry.spacing_xyz)

    @property
    def sampling_mm(self) -> float:
        return float(self._sampling)

    def reconstruct(self, plane: MprPlane, cursor_lps: Sequence[float]) -> ResampledPlane:
        geometry = self.plane_geometry(plane, cursor_lps)
        u, v, normal = (
            np.asarray(geometry.u_axis_lps),
            np.asarray(geometry.v_axis_lps),
            np.asarray(geometry.normal_lps),
        )
        direction = np.column_stack((u, v, normal))
        output = self._sitk.Resample(
            self._image,
            [geometry.shape_hw[1], geometry.shape_hw[0], 1],
            self._sitk.Transform(3, self._sitk.sitkIdentity),
            self._sitk.sitkLinear,
            geometry.origin_lps,
            [geometry.spacing_uv[0], geometry.spacing_uv[1], 1.0],
            tuple(float(value) for value in direction.reshape(-1)),
            0.0,
            self._sitk.sitkFloat32,
        )
        pixels = self._sitk.GetArrayFromImage(output)[0].astype(np.float32, copy=False)
        pixels.setflags(write=False)
        return ResampledPlane(pixels=pixels, geometry=geometry)

    def plane_geometry(self, plane: MprPlane, cursor_lps: Sequence[float]) -> PlaneGeometry:
        cursor = np.asarray(cursor_lps[:3], dtype=np.float64)
        (xmin, xmax), (ymin, ymax), (zmin, zmax) = self._bounds
        spacing = float(self._sampling)
        if plane is MprPlane.AXIAL:
            origin = (xmin, ymin, float(np.clip(cursor[2], zmin, zmax)))
            u, v, normal = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
            width, height = xmax - xmin, ymax - ymin
        elif plane is MprPlane.CORONAL:
            origin = (xmin, float(np.clip(cursor[1], ymin, ymax)), zmax)
            u, v, normal = (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)
            width, height = xmax - xmin, zmax - zmin
        else:
            origin = (float(np.clip(cursor[0], xmin, xmax)), ymin, zmax)
            u, v, normal = (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (-1.0, 0.0, 0.0)
            width, height = ymax - ymin, zmax - zmin
        shape = (
            max(1, int(np.floor(height / spacing)) + 1),
            max(1, int(np.floor(width / spacing)) + 1),
        )
        return PlaneGeometry(
            plane=plane,
            origin_lps=tuple(float(value) for value in origin),
            u_axis_lps=u,
            v_axis_lps=v,
            normal_lps=normal,
            spacing_uv=(spacing, spacing),
            shape_hw=shape,
        )

