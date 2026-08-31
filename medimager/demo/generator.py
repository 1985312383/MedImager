"""Deterministic, fully synthetic DICOM study generation and validation."""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage

from medimager.demo.catalog import GENERATOR_VERSION, DemoStudyId, DemoStudySpec
from medimager.demo.manifest import (
    MANIFEST_FILENAME,
    DemoFileManifest,
    DemoSeriesManifest,
    DemoStudyManifest,
)


_UID_NAMESPACE = uuid.UUID("3cc7cc91-2b80-53ca-9978-4fa17cfb4f1c")
_IMPLEMENTATION_UID = f"2.25.{uuid.uuid5(_UID_NAMESPACE, 'implementation').int}"
_DATE = "20260115"
_BASE_TIME = 93000


class DemoGenerationCancelled(RuntimeError):
    """Raised internally when a cooperative generation request is cancelled."""


@dataclass(frozen=True)
class DemoGenerationProfile:
    """Dimensions are injectable so tests can exercise the real writer cheaply."""

    ct_shape_zyx: tuple[int, int, int] = (64, 192, 192)
    ct_coronal_slices: int = 48
    mr_shape_zyx: tuple[int, int, int] = (48, 160, 160)
    geometry_shape_zyx: tuple[int, int, int] = (16, 64, 64)
    random_seed: int = 260

    def validate(self) -> None:
        for name, shape in (
            ("ct_shape_zyx", self.ct_shape_zyx),
            ("mr_shape_zyx", self.mr_shape_zyx),
            ("geometry_shape_zyx", self.geometry_shape_zyx),
        ):
            if len(shape) != 3 or any(int(value) < 2 for value in shape):
                raise ValueError(f"{name} must contain three dimensions >= 2")
        if not 2 <= self.ct_coronal_slices <= self.ct_shape_zyx[1]:
            raise ValueError("ct_coronal_slices must fit the CT row dimension")
        if self.ct_shape_zyx[1] % self.ct_coronal_slices:
            raise ValueError("CT rows must be divisible by ct_coronal_slices")

    def to_dict(self) -> dict:
        return asdict(self)


PRODUCTION_PROFILE = DemoGenerationProfile()


@dataclass(frozen=True)
class DemoValidationResult:
    valid: bool
    reason: str
    manifest: Optional[DemoStudyManifest] = None


@dataclass(frozen=True)
class _StudyIdentity:
    patient_name: str
    patient_id: str
    study_description: str
    study_instance_uid: str
    frame_of_reference_uid: str


@dataclass(frozen=True)
class _SeriesDefinition:
    role: str
    number: int
    description: str
    protocol_name: str
    body_part: str
    modality: str
    pixels: Sequence[np.ndarray] | np.ndarray
    positions: Sequence[Sequence[float]]
    orientations: Sequence[Optional[Sequence[float]]]
    frame_uids: Sequence[str]
    pixel_spacing: tuple[float, float]
    slice_spacing: float
    window_center: float
    window_width: float
    expected_geometry_status: str = "compatible"
    expected_reason_key: str = "mpr.compatible"
    image_type: str = "AXIAL"


def uid_for(logical_name: str) -> str:
    """Return a stable, standards-compliant 2.25 UID for a logical object."""

    normalized = str(logical_name).strip()
    if not normalized:
        raise ValueError("logical_name must not be empty")
    return f"2.25.{uuid.uuid5(_UID_NAMESPACE, normalized).int}"


def generate_demo_study(
    spec: DemoStudySpec,
    output_dir: str | Path,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    profile: DemoGenerationProfile = PRODUCTION_PROFILE,
) -> DemoStudyManifest:
    """Generate one complete study and write its manifest last.

    ``output_dir`` must be empty. Cache promotion and stale-directory cleanup
    belong to :class:`DemoStudyService`, keeping this function deterministic.
    """

    profile.validate()
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Demo output directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    cancel_check = cancelled or (lambda: False)
    total = _expected_instance_count(spec.id, profile)
    completed = 0
    if progress is not None:
        progress(0, total)

    def instance_progress() -> None:
        nonlocal completed
        completed += 1
        if progress is not None:
            progress(completed, total)

    identity, definitions = _build_study(spec.id, profile)
    series_manifests: list[DemoSeriesManifest] = []
    for definition in definitions:
        if cancel_check():
            raise DemoGenerationCancelled(spec.id.value)
        series_manifests.append(
            _write_series(
                root,
                spec.id,
                identity,
                definition,
                cancelled=cancel_check,
                progress=instance_progress,
            )
        )

    if len(series_manifests) != spec.expected_series_count:
        raise RuntimeError(
            f"Catalog expects {spec.expected_series_count} series, "
            f"generator produced {len(series_manifests)}"
        )
    if completed != total:
        raise RuntimeError(f"Expected {total} instances, generated {completed}")

    disk_bytes = sum(
        item.size_bytes for series in series_manifests for item in series.files
    )
    manifest = DemoStudyManifest(
        study_id=spec.id,
        study_instance_uid=identity.study_instance_uid,
        generator_version=GENERATOR_VERSION,
        profile=profile.to_dict(),
        series=tuple(series_manifests),
        disk_bytes=disk_bytes,
    ).with_digest()
    manifest.write(root)
    return manifest


def validate_demo_study(
    root: str | Path,
    spec: DemoStudySpec,
    *,
    verify_file_hashes: bool = True,
) -> DemoValidationResult:
    """Validate a generated cache without decoding protected pixel content."""

    path = Path(root)
    try:
        manifest_path = path / MANIFEST_FILENAME
        if not manifest_path.is_file():
            return DemoValidationResult(False, "demo.manifest_missing")
        manifest = DemoStudyManifest.read(path)
        if not manifest.complete:
            return DemoValidationResult(False, "demo.manifest_incomplete")
        if manifest.study_id is not spec.id:
            return DemoValidationResult(False, "demo.manifest_study_mismatch")
        if manifest.generator_version != spec.generator_version:
            return DemoValidationResult(False, "demo.generator_version_mismatch")
        if len(manifest.series) != spec.expected_series_count:
            return DemoValidationResult(False, "demo.series_count_mismatch")
        if not manifest.digest_is_valid():
            return DemoValidationResult(False, "demo.manifest_digest_mismatch")

        total_bytes = 0
        roles: set[str] = set()
        for series in manifest.series:
            if series.role in roles:
                return DemoValidationResult(False, "demo.duplicate_series_role")
            roles.add(series.role)
            relative_dir = _safe_relative_path(series.relative_path)
            if len(series.files) != series.instances:
                return DemoValidationResult(False, "demo.instance_count_mismatch")
            for file_info in series.files:
                relative_file = _safe_relative_path(file_info.relative_path)
                if relative_file.parent != relative_dir:
                    return DemoValidationResult(False, "demo.invalid_file_path")
                file_path = path.joinpath(*relative_file.parts)
                if not file_path.is_file():
                    return DemoValidationResult(False, "demo.file_missing")
                size = file_path.stat().st_size
                if size != file_info.size_bytes:
                    return DemoValidationResult(False, "demo.file_size_mismatch")
                total_bytes += size
                if verify_file_hashes and _sha256_file(file_path) != file_info.sha256:
                    return DemoValidationResult(False, "demo.file_digest_mismatch")
        if total_bytes != manifest.disk_bytes:
            return DemoValidationResult(False, "demo.disk_size_mismatch")
        return DemoValidationResult(True, "demo.valid", manifest)
    except (OSError, ValueError, KeyError, TypeError):
        return DemoValidationResult(False, "demo.manifest_invalid")


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Unsafe relative path in demo manifest")
    return path


def _expected_instance_count(
    study_id: DemoStudyId,
    profile: DemoGenerationProfile,
) -> int:
    if study_id is DemoStudyId.CT_MULTIPHASE:
        return profile.ct_shape_zyx[0] * 2 + profile.ct_coronal_slices + 1
    if study_id is DemoStudyId.MR_BRAIN:
        return profile.mr_shape_zyx[0] * 4
    return profile.geometry_shape_zyx[0] * 12


def _build_study(
    study_id: DemoStudyId,
    profile: DemoGenerationProfile,
) -> tuple[_StudyIdentity, list[_SeriesDefinition]]:
    if study_id is DemoStudyId.CT_MULTIPHASE:
        return _build_ct_study(profile)
    if study_id is DemoStudyId.MR_BRAIN:
        return _build_mr_study(profile)
    if study_id is DemoStudyId.GEOMETRY_LAB:
        return _build_geometry_study(profile)
    raise ValueError(f"Unsupported demo study: {study_id}")


def _identity(study_id: DemoStudyId, label: str) -> _StudyIdentity:
    return _StudyIdentity(
        patient_name=f"MEDIMAGER^{label}",
        patient_id=f"DEMO-{label}-001",
        study_description=f"MedImager {label} Example Study",
        study_instance_uid=uid_for(f"{study_id.value}:study"),
        frame_of_reference_uid=uid_for(f"{study_id.value}:frame"),
    )


def _build_ct_study(
    profile: DemoGenerationProfile,
) -> tuple[_StudyIdentity, list[_SeriesDefinition]]:
    identity = _identity(DemoStudyId.CT_MULTIPHASE, "CT")
    noncontrast, arterial = _ct_volumes(profile.ct_shape_zyx, profile.random_seed)
    depth, rows, cols = noncontrast.shape
    spacing_z = 2.0
    origin = np.asarray((-cols / 2.0, -rows / 2.0, -depth * spacing_z / 2.0))
    axial_positions = [origin + (0.0, 0.0, index * spacing_z) for index in range(depth)]
    axial_orientation = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    frame_uids = [identity.frame_of_reference_uid] * depth

    step = rows // profile.ct_coronal_slices
    coronal_indices = [
        (profile.ct_coronal_slices - 1 - index) * step
        for index in range(profile.ct_coronal_slices)
    ]
    coronal_pixels = [noncontrast[:, row_index, :] for row_index in coronal_indices]
    coronal_positions = [
        (float(origin[0]), float(origin[1] + row_index), float(origin[2]))
        for row_index in coronal_indices
    ]
    coronal_orientation = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    scout = np.repeat(np.max(noncontrast, axis=1), 2, axis=0).astype(np.int16)

    common = dict(
        body_part="CHEST_ABDOMEN",
        modality="CT",
        frame_uids=frame_uids,
        pixel_spacing=(1.0, 1.0),
        slice_spacing=spacing_z,
        window_center=40.0,
        window_width=400.0,
    )
    definitions = [
        _SeriesDefinition(
            role="ct_noncontrast_axial",
            number=1,
            description="CT Chest Abdomen Non Contrast Axial",
            protocol_name="Synthetic non contrast",
            pixels=noncontrast,
            positions=axial_positions,
            orientations=[axial_orientation] * depth,
            **common,
        ),
        _SeriesDefinition(
            role="ct_arterial_axial",
            number=2,
            description="CT Chest Abdomen Arterial Contrast Axial",
            protocol_name="Synthetic arterial contrast",
            pixels=arterial,
            positions=axial_positions,
            orientations=[axial_orientation] * depth,
            **common,
        ),
        _SeriesDefinition(
            role="ct_coronal_reference",
            number=3,
            description="CT Coronal Reference",
            protocol_name="Synthetic coronal reformatted",
            body_part="CHEST_ABDOMEN",
            modality="CT",
            pixels=coronal_pixels,
            positions=coronal_positions,
            orientations=[coronal_orientation] * len(coronal_pixels),
            frame_uids=[identity.frame_of_reference_uid] * len(coronal_pixels),
            pixel_spacing=(spacing_z, 1.0),
            slice_spacing=float(step),
            window_center=40.0,
            window_width=400.0,
            image_type="CORONAL",
        ),
        _SeriesDefinition(
            role="ct_localizer",
            number=4,
            description="CT Scout Localizer",
            protocol_name="Synthetic scout localizer",
            body_part="CHEST_ABDOMEN",
            modality="CT",
            pixels=[scout],
            positions=[coronal_positions[len(coronal_positions) // 2]],
            orientations=[coronal_orientation],
            frame_uids=[identity.frame_of_reference_uid],
            pixel_spacing=(1.0, 1.0),
            slice_spacing=1.0,
            window_center=0.0,
            window_width=1200.0,
            expected_geometry_status="rejected",
            expected_reason_key="mpr.requires_multiple_slices",
            image_type="LOCALIZER",
        ),
    ]
    return identity, definitions


def _ct_volumes(
    shape: tuple[int, int, int],
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    depth, rows, cols = shape
    z, y, x = np.ogrid[
        -1.0 : 1.0 : complex(0, depth),
        -1.0 : 1.0 : complex(0, rows),
        -1.0 : 1.0 : complex(0, cols),
    ]
    body_metric = (x / 0.82) ** 2 + (y / 0.68) ** 2 + (z / 0.94) ** 2
    body = body_metric <= 1.0
    volume = np.full(shape, -1000, dtype=np.int16)
    volume[body] = 42
    subcutaneous = body & (body_metric > 0.78)
    volume[subcutaneous] = -90

    left_lung = ((x + 0.31) / 0.24) ** 2 + ((y + 0.07) / 0.36) ** 2 + (
        z / 0.68
    ) ** 2 <= 1
    right_lung = ((x - 0.31) / 0.27) ** 2 + ((y + 0.05) / 0.38) ** 2 + (
        z / 0.72
    ) ** 2 <= 1
    lungs = (left_lung | right_lung) & body
    volume[lungs] = -790

    heart = (x / 0.26) ** 2 + ((y - 0.13) / 0.29) ** 2 + ((z + 0.03) / 0.35) ** 2 <= 1
    volume[heart & body] = 58
    spine = (x / 0.09) ** 2 + ((y - 0.45) / 0.12) ** 2 <= 1
    volume[spine & body] = 720
    vessel = ((x + 0.03) / 0.055) ** 2 + ((y - 0.12) / 0.07) ** 2 <= 1
    volume[vessel & body] = 55
    lesion = ((x - 0.27) / 0.065) ** 2 + ((y + 0.08) / 0.065) ** 2 + (
        (z - 0.06) / 0.09
    ) ** 2 <= 1
    volume[lesion] = 45
    nodule = ((x + 0.38) / 0.035) ** 2 + ((y + 0.1) / 0.035) ** 2 + (
        (z + 0.22) / 0.045
    ) ** 2 <= 1
    volume[nodule] = 120

    rng = np.random.default_rng(seed)
    noise = rng.integers(-7, 8, size=shape, dtype=np.int16)
    volume[body] = np.clip(volume[body] + noise[body], -1000, 3000)
    arterial = volume.copy()
    arterial[vessel & body] = 310
    arterial[lesion] = 135
    return np.ascontiguousarray(volume), np.ascontiguousarray(arterial)


def _build_mr_study(
    profile: DemoGenerationProfile,
) -> tuple[_StudyIdentity, list[_SeriesDefinition]]:
    identity = _identity(DemoStudyId.MR_BRAIN, "MR")
    volumes = _mr_volumes(profile.mr_shape_zyx, profile.random_seed + 1)
    depth, rows, cols = profile.mr_shape_zyx
    spacing_z = 3.0
    origin = np.asarray((-cols * 0.45, -rows * 0.45, -depth * spacing_z / 2.0))
    positions = [origin + (0.0, 0.0, index * spacing_z) for index in range(depth)]
    orientation = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    roles = (
        ("mr_t1_mprage", 1, "3D T1 MPRAGE", 500.0, 1000.0),
        ("mr_t2_tse", 2, "T2 TSE", 650.0, 1300.0),
        ("mr_flair", 3, "Ax FLAIR", 600.0, 1200.0),
        ("mr_dwi_b1000", 4, "DWI b1000", 650.0, 1300.0),
    )
    definitions = []
    for role, number, description, center, width in roles:
        definitions.append(
            _SeriesDefinition(
                role=role,
                number=number,
                description=description,
                protocol_name=f"Synthetic {description}",
                body_part="BRAIN",
                modality="MR",
                pixels=volumes[role],
                positions=positions,
                orientations=[orientation] * depth,
                frame_uids=[identity.frame_of_reference_uid] * depth,
                pixel_spacing=(0.9, 0.9),
                slice_spacing=spacing_z,
                window_center=center,
                window_width=width,
            )
        )
    return identity, definitions


def _mr_volumes(
    shape: tuple[int, int, int],
    seed: int,
) -> dict[str, np.ndarray]:
    depth, rows, cols = shape
    z, y, x = np.ogrid[
        -1.0 : 1.0 : complex(0, depth),
        -1.0 : 1.0 : complex(0, rows),
        -1.0 : 1.0 : complex(0, cols),
    ]
    outer = (x / 0.73) ** 2 + (y / 0.88) ** 2 + (z / 0.76) ** 2 <= 1
    inner = (x / 0.66) ** 2 + (y / 0.80) ** 2 + (z / 0.69) ** 2 <= 1
    white = (x / 0.54) ** 2 + (y / 0.67) ** 2 + (z / 0.57) ** 2 <= 1
    vent_left = ((x + 0.12) / 0.075) ** 2 + (y / 0.2) ** 2 + (z / 0.22) ** 2 <= 1
    vent_right = ((x - 0.12) / 0.075) ** 2 + (y / 0.2) ** 2 + (z / 0.22) ** 2 <= 1
    ventricles = vent_left | vent_right
    lesion = ((x - 0.31) / 0.105) ** 2 + ((y + 0.13) / 0.13) ** 2 + (
        (z - 0.05) / 0.16
    ) ** 2 <= 1

    values = {
        "mr_t1_mprage": (70, 520, 760, 90, 390),
        "mr_t2_tse": (90, 720, 520, 1050, 930),
        "mr_flair": (80, 690, 510, 110, 980),
        "mr_dwi_b1000": (45, 360, 430, 120, 1180),
    }
    rng = np.random.default_rng(seed)
    result: dict[str, np.ndarray] = {}
    for index, (role, levels) in enumerate(values.items()):
        background, gray_level, white_level, csf_level, lesion_level = levels
        volume = np.full(shape, background, dtype=np.uint16)
        volume[outer] = 120
        volume[inner] = gray_level
        volume[white] = white_level
        volume[ventricles] = csf_level
        volume[lesion & inner] = lesion_level
        noise = rng.integers(-8, 9, size=shape, dtype=np.int16)
        inside_values = volume[outer].astype(np.int32) + noise[outer] + index
        volume[outer] = np.clip(inside_values, 0, 4095).astype(np.uint16)
        result[role] = np.ascontiguousarray(volume)
    return result


def _build_geometry_study(
    profile: DemoGenerationProfile,
) -> tuple[_StudyIdentity, list[_SeriesDefinition]]:
    identity = _identity(DemoStudyId.GEOMETRY_LAB, "GEOMETRY")
    volume = _geometry_volume(profile.geometry_shape_zyx)
    depth, rows, cols = volume.shape
    origin = np.asarray((-cols / 2.0, -rows / 2.0, -depth))
    axial_iop = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    regular_positions = [origin + (0.0, 0.0, index * 2.0) for index in range(depth)]
    main_frame = identity.frame_of_reference_uid

    def definition(
        role: str,
        number: int,
        description: str,
        *,
        pixels: Sequence[np.ndarray] | np.ndarray = volume,
        positions: Sequence[Sequence[float]] = regular_positions,
        orientations: Optional[Sequence[Optional[Sequence[float]]]] = None,
        frame_uid: Optional[str] = None,
        status: str = "compatible",
        reason: str = "mpr.compatible",
        spacing: tuple[float, float] = (1.0, 1.0),
        slice_spacing: float = 2.0,
    ) -> _SeriesDefinition:
        count = len(pixels)
        return _SeriesDefinition(
            role=role,
            number=number,
            description=description,
            protocol_name="Synthetic geometry validation",
            body_part="PHANTOM",
            modality="CT",
            pixels=pixels,
            positions=positions,
            orientations=list(orientations or [axial_iop] * count),
            frame_uids=[frame_uid or main_frame] * count,
            pixel_spacing=spacing,
            slice_spacing=slice_spacing,
            window_center=320.0,
            window_width=900.0,
            expected_geometry_status=status,
            expected_reason_key=reason,
        )

    reversed_positions = list(reversed(regular_positions))
    reversed_pixels = np.ascontiguousarray(volume[::-1])
    angle = math.radians(15.0)
    oblique_iop = (1.0, 0.0, 0.0, 0.0, math.cos(angle), math.sin(angle))
    oblique_normal = np.cross(oblique_iop[:3], oblique_iop[3:])
    oblique_positions = [
        origin + oblique_normal * (index * 2.0) for index in range(depth)
    ]

    duplicate_positions = list(regular_positions)
    duplicate_positions[-1] = duplicate_positions[-2]
    gap_positions = [
        origin + (0.0, 0.0, index * 2.0 + (2.0 if index >= depth // 2 else 0.0))
        for index in range(depth)
    ]
    nonuniform_positions = [
        origin + (0.0, 0.0, index * 2.0 + (0.5 if index >= depth // 2 else 0.0))
        for index in range(depth)
    ]
    changed_orientations: list[Optional[Sequence[float]]] = [axial_iop] * depth
    changed_angle = math.radians(5.0)
    changed_orientations[depth // 2] = (
        math.cos(changed_angle),
        math.sin(changed_angle),
        0.0,
        -math.sin(changed_angle),
        math.cos(changed_angle),
        0.0,
    )
    tilt_positions = [
        origin + (index * 0.2, 0.0, index * 2.0) for index in range(depth)
    ]
    missing_orientations: list[Optional[Sequence[float]]] = [axial_iop] * depth
    missing_orientations[depth // 2] = None

    definitions = [
        definition("geometry_regular_axial", 1, "[PASS] Regular axial"),
        definition(
            "geometry_reversed_order",
            2,
            "[PASS] Reversed file order",
            pixels=reversed_pixels,
            positions=reversed_positions,
        ),
        definition(
            "geometry_anisotropic",
            3,
            "[PASS] Anisotropic spacing",
            spacing=(0.7, 1.4),
            slice_spacing=3.0,
            positions=[origin + (0.0, 0.0, index * 3.0) for index in range(depth)],
        ),
        definition(
            "geometry_regular_oblique",
            4,
            "[PASS] Regular 15 degree oblique",
            positions=oblique_positions,
            orientations=[oblique_iop] * depth,
        ),
        definition(
            "geometry_duplicate_position",
            5,
            "[REJECT] Duplicate slice position",
            positions=duplicate_positions,
            status="rejected",
            reason="mpr.duplicate_slices",
        ),
        definition(
            "geometry_missing_layer",
            6,
            "[REJECT] Missing layer gap",
            positions=gap_positions,
            status="rejected",
            reason="mpr.non_uniform_spacing",
        ),
        definition(
            "geometry_nonuniform_spacing",
            7,
            "[REJECT] Non-uniform spacing",
            positions=nonuniform_positions,
            status="rejected",
            reason="mpr.non_uniform_spacing",
        ),
        definition(
            "geometry_orientation_change",
            8,
            "[REJECT] Orientation changes",
            orientations=changed_orientations,
            status="rejected",
            reason="mpr.inconsistent_orientation",
        ),
        definition(
            "geometry_gantry_tilt",
            9,
            "[REJECT] Gantry tilt",
            positions=tilt_positions,
            status="rejected",
            reason="mpr.gantry_tilt",
        ),
        definition(
            "geometry_missing_tags",
            10,
            "[REJECT] Missing orientation tag",
            orientations=missing_orientations,
            status="rejected",
            reason="mpr.missing_geometry",
        ),
        definition(
            "geometry_different_for_a",
            11,
            "[ISOLATED] Frame of reference A",
            frame_uid=uid_for("geometry_lab:isolated-frame-a"),
        ),
        definition(
            "geometry_different_for_b",
            12,
            "[ISOLATED] Frame of reference B",
            frame_uid=uid_for("geometry_lab:isolated-frame-b"),
        ),
    ]
    return identity, definitions


def _geometry_volume(shape: tuple[int, int, int]) -> np.ndarray:
    depth, rows, cols = shape
    z, y, x = np.indices(shape, dtype=np.int32)
    volume = (x * 3 + y * 5 + z * 23).astype(np.int16)
    marker = (x - cols * 0.68) ** 2 + (y - rows * 0.34) ** 2 + (
        (z - depth * 0.62) * 2.0
    ) ** 2 <= (min(rows, cols) * 0.09) ** 2
    volume[marker] = 1800
    return np.ascontiguousarray(volume)


def _write_series(
    root: Path,
    study_id: DemoStudyId,
    identity: _StudyIdentity,
    definition: _SeriesDefinition,
    *,
    cancelled: Callable[[], bool],
    progress: Callable[[], None],
) -> DemoSeriesManifest:
    count = len(definition.pixels)
    if not (
        count
        == len(definition.positions)
        == len(definition.orientations)
        == len(definition.frame_uids)
    ):
        raise ValueError(f"Geometry length mismatch for {definition.role}")
    series_dir = root / definition.role
    series_dir.mkdir(parents=True, exist_ok=False)
    series_uid = uid_for(f"{study_id.value}:series:{definition.role}")
    pixel_digest = hashlib.sha256()
    files: list[DemoFileManifest] = []

    for index, pixel_array in enumerate(definition.pixels):
        if cancelled():
            raise DemoGenerationCancelled(study_id.value)
        normalized = _normalise_pixels(pixel_array, definition.modality)
        pixel_digest.update(normalized.tobytes(order="C"))
        sop_uid = uid_for(f"{study_id.value}:{definition.role}:instance:{index + 1}")
        path = series_dir / f"IM_{index + 1:04d}.dcm"
        _write_dicom(
            path,
            identity,
            definition,
            series_uid=series_uid,
            sop_uid=sop_uid,
            instance_number=index + 1,
            pixel_array=normalized,
            position=definition.positions[index],
            orientation=definition.orientations[index],
            frame_uid=definition.frame_uids[index],
        )
        relative = path.relative_to(root).as_posix()
        files.append(
            DemoFileManifest(
                relative_path=relative,
                sop_instance_uid=sop_uid,
                sha256=_sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
        progress()

    return DemoSeriesManifest(
        role=definition.role,
        series_instance_uid=series_uid,
        relative_path=definition.role,
        modality=definition.modality,
        instances=count,
        pixel_sha256=pixel_digest.hexdigest(),
        expected_geometry_status=definition.expected_geometry_status,
        expected_reason_key=definition.expected_reason_key,
        files=tuple(files),
    )


def _normalise_pixels(pixel_array: np.ndarray, modality: str) -> np.ndarray:
    if modality == "MR":
        return np.ascontiguousarray(pixel_array, dtype="<u2")
    return np.ascontiguousarray(pixel_array, dtype="<i2")


def _write_dicom(
    path: Path,
    identity: _StudyIdentity,
    definition: _SeriesDefinition,
    *,
    series_uid: str,
    sop_uid: str,
    instance_number: int,
    pixel_array: np.ndarray,
    position: Sequence[float],
    orientation: Optional[Sequence[float]],
    frame_uid: str,
) -> None:
    sop_class = MRImageStorage if definition.modality == "MR" else CTImageStorage
    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = _IMPLEMENTATION_UID
    file_meta.ImplementationVersionName = "MEDIMAGER_260"

    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = sop_class
    dataset.SOPInstanceUID = sop_uid
    dataset.PatientName = identity.patient_name
    dataset.PatientID = identity.patient_id
    dataset.PatientSex = "O"
    dataset.PatientIdentityRemoved = "YES"
    dataset.DeidentificationMethod = "Fully synthetic; no source patient"
    dataset.StudyInstanceUID = identity.study_instance_uid
    dataset.SeriesInstanceUID = series_uid
    if frame_uid:
        dataset.FrameOfReferenceUID = frame_uid
    dataset.StudyID = "DEMO260"
    dataset.AccessionNumber = ""
    dataset.StudyDescription = identity.study_description
    dataset.SeriesDescription = definition.description
    dataset.ProtocolName = definition.protocol_name
    dataset.BodyPartExamined = definition.body_part
    dataset.Modality = definition.modality
    dataset.Manufacturer = "MedImager Synthetic"
    dataset.InstitutionName = "MedImager Example Data"
    dataset.StudyDate = _DATE
    dataset.SeriesDate = _DATE
    dataset.AcquisitionDate = _DATE
    dataset.ContentDate = _DATE
    dataset.StudyTime = f"{_BASE_TIME:06d}"
    series_time = _BASE_TIME + definition.number * 100
    dataset.SeriesTime = f"{series_time:06d}"
    dataset.AcquisitionTime = f"{series_time:06d}"
    dataset.ContentTime = f"{series_time:06d}"
    dataset.SeriesNumber = definition.number
    dataset.AcquisitionNumber = definition.number
    dataset.InstanceNumber = instance_number
    dataset.ImageType = ["ORIGINAL", "PRIMARY", definition.image_type]
    dataset.PatientPosition = "HFS"
    dataset.BurnedInAnnotation = "NO"

    if orientation is not None:
        dataset.ImageOrientationPatient = [float(value) for value in orientation]
    dataset.ImagePositionPatient = [float(value) for value in position]
    dataset.SliceLocation = (
        float(np.dot(np.asarray(position), _normal(orientation)))
        if orientation
        else 0.0
    )
    dataset.PixelSpacing = [float(value) for value in definition.pixel_spacing]
    dataset.SliceThickness = float(definition.slice_spacing)
    dataset.SpacingBetweenSlices = float(definition.slice_spacing)

    rows, cols = pixel_array.shape
    dataset.Rows = rows
    dataset.Columns = cols
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 0 if definition.modality == "MR" else 1
    dataset.WindowCenter = float(definition.window_center)
    dataset.WindowWidth = float(definition.window_width)
    dataset.RescaleSlope = 1.0
    dataset.RescaleIntercept = 0.0
    if definition.modality == "CT":
        dataset.RescaleType = "HU"
        dataset.PixelPaddingValue = -1000
    dataset.PixelData = pixel_array.tobytes(order="C")
    dataset.save_as(path, enforce_file_format=True)


def _normal(orientation: Optional[Sequence[float]]) -> np.ndarray:
    if orientation is None:
        return np.asarray((0.0, 0.0, 1.0))
    return np.cross(
        np.asarray(orientation[:3], dtype=np.float64),
        np.asarray(orientation[3:6], dtype=np.float64),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
