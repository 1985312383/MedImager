"""Stable patient/study/series hierarchy used by the v2.5 workspace.

The hierarchy deliberately keeps display labels separate from internal keys.  A
missing DICOM UID therefore never causes unrelated studies to be merged merely
because they happen to share an empty description.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Iterable, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for static checking
    from medimager.core.multi_series_manager import SeriesInfo


_MISSING_IDENTIFIERS = {"", "unknown", "n/a", "none", "null"}


def meaningful_identifier(value: object) -> bool:
    return str(value or "").strip().lower() not in _MISSING_IDENTIFIERS


def _opaque_key(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:20]
    return f"{prefix}:{digest}"


class SeriesOrientation(str, Enum):
    AXIAL = "axial"
    CORONAL = "coronal"
    SAGITTAL = "sagittal"
    OBLIQUE = "oblique"
    UNKNOWN = "unknown"


def classify_orientation(
    image_orientation_patient: Optional[Sequence[float]],
    *,
    axis_threshold: float = 0.9,
) -> SeriesOrientation:
    """Classify the normal of a DICOM image plane in LPS patient space."""
    if image_orientation_patient is None or len(image_orientation_patient) < 6:
        return SeriesOrientation.UNKNOWN
    try:
        row = tuple(float(value) for value in image_orientation_patient[:3])
        column = tuple(float(value) for value in image_orientation_patient[3:6])
    except (TypeError, ValueError):
        return SeriesOrientation.UNKNOWN
    normal = (
        row[1] * column[2] - row[2] * column[1],
        row[2] * column[0] - row[0] * column[2],
        row[0] * column[1] - row[1] * column[0],
    )
    dominant = max(range(3), key=lambda index: abs(normal[index]))
    if abs(normal[dominant]) < axis_threshold:
        return SeriesOrientation.OBLIQUE
    return (
        SeriesOrientation.SAGITTAL,
        SeriesOrientation.CORONAL,
        SeriesOrientation.AXIAL,
    )[dominant]


@dataclass(frozen=True)
class StudySeriesNode:
    key: str
    series_id: str
    series_instance_uid: str
    description: str
    modality: str
    series_number: str
    slice_count: int
    orientation: SeriesOrientation
    frame_of_reference_uid: str
    is_loaded: bool


@dataclass(frozen=True)
class StudyNode:
    key: str
    patient_key: str
    study_instance_uid: str
    description: str
    study_date: str
    study_time: str
    modalities: Tuple[str, ...]
    series: Tuple[StudySeriesNode, ...]

    @property
    def series_count(self) -> int:
        return len(self.series)


@dataclass(frozen=True)
class PatientNode:
    key: str
    patient_id: str
    display_name: str
    studies: Tuple[StudyNode, ...]


@dataclass(frozen=True)
class StudyHierarchy:
    """Immutable snapshot so UI code can traverse without manager mutation."""

    patients: Tuple[PatientNode, ...]
    series_to_study: Mapping[str, str]
    study_to_patient: Mapping[str, str]

    @classmethod
    def build(cls, series_items: Iterable["SeriesInfo"]) -> "StudyHierarchy":
        patient_groups: dict[str, dict[str, list["SeriesInfo"]]] = {}
        patient_meta: dict[str, tuple[str, str]] = {}
        study_meta: dict[str, tuple[str, str, str, str]] = {}
        series_to_study: dict[str, str] = {}
        study_to_patient: dict[str, str] = {}

        for info in series_items:
            patient_key = (
                f"patient:{str(info.patient_id).strip()}"
                if meaningful_identifier(info.patient_id)
                else _opaque_key(
                    "patient",
                    info.patient_name,
                    info.study_instance_uid,
                    info.series_id,
                )
            )
            study_key = (
                f"study:{str(info.study_instance_uid).strip()}"
                if meaningful_identifier(info.study_instance_uid)
                else _opaque_key(
                    "study",
                    patient_key,
                    info.study_date,
                    info.study_time,
                    info.study_description,
                    info.series_id,
                )
            )
            patient_meta.setdefault(
                patient_key,
                (str(info.patient_id or ""), str(info.patient_name or "")),
            )
            study_meta.setdefault(
                study_key,
                (
                    str(info.study_instance_uid or ""),
                    str(info.study_description or ""),
                    str(info.study_date or ""),
                    str(info.study_time or ""),
                ),
            )
            patient_groups.setdefault(patient_key, {}).setdefault(study_key, []).append(info)
            series_to_study[info.series_id] = study_key
            study_to_patient[study_key] = patient_key

        patients = []
        for patient_key, studies_by_key in patient_groups.items():
            studies = []
            for study_key, infos in studies_by_key.items():
                series_nodes = tuple(
                    sorted(
                        (
                            StudySeriesNode(
                                key=(
                                    f"series:{str(info.series_instance_uid).strip()}"
                                    if meaningful_identifier(info.series_instance_uid)
                                    else f"series-local:{info.series_id}"
                                ),
                                series_id=info.series_id,
                                series_instance_uid=str(info.series_instance_uid or ""),
                                description=str(info.series_description or ""),
                                modality=str(info.modality or ""),
                                series_number=str(info.series_number or ""),
                                slice_count=max(0, int(info.slice_count or 0)),
                                orientation=SeriesOrientation(
                                    info.orientation
                                    if info.orientation in SeriesOrientation._value2member_map_
                                    else SeriesOrientation.UNKNOWN.value
                                ),
                                frame_of_reference_uid=str(info.frame_of_reference_uid or ""),
                                is_loaded=bool(info.is_loaded),
                            )
                            for info in infos
                        ),
                        key=lambda node: (
                            _series_number_key(node.series_number),
                            node.description.casefold(),
                            node.series_id,
                        ),
                    )
                )
                uid, description, date, time = study_meta[study_key]
                modalities = tuple(sorted({node.modality for node in series_nodes if node.modality}))
                studies.append(
                    StudyNode(
                        key=study_key,
                        patient_key=patient_key,
                        study_instance_uid=uid,
                        description=description,
                        study_date=date,
                        study_time=time,
                        modalities=modalities,
                        series=series_nodes,
                    )
                )
            patient_id, display_name = patient_meta[patient_key]
            patients.append(
                PatientNode(
                    key=patient_key,
                    patient_id=patient_id,
                    display_name=display_name,
                    studies=tuple(
                        sorted(
                            studies,
                            key=lambda study: (
                                study.study_date,
                                study.study_time,
                                study.description.casefold(),
                                study.key,
                            ),
                            reverse=True,
                        )
                    ),
                )
            )

        return cls(
            patients=tuple(
                sorted(
                    patients,
                    key=lambda patient: (
                        patient.display_name.casefold(),
                        patient.patient_id,
                        patient.key,
                    ),
                )
            ),
            series_to_study=series_to_study,
            study_to_patient=study_to_patient,
        )

    def study_for_series(self, series_id: str) -> Optional[StudyNode]:
        study_key = self.series_to_study.get(series_id)
        if not study_key:
            return None
        for patient in self.patients:
            for study in patient.studies:
                if study.key == study_key:
                    return study
        return None


def _series_number_key(value: str) -> tuple[int, object]:
    try:
        return 0, int(str(value).strip())
    except (TypeError, ValueError):
        return 1, str(value or "").casefold()
