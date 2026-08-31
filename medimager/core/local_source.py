"""Typed local-study source contracts for the v2.6 workspace.

The module deliberately contains no main-window or image-viewer dependencies.
Folder and DICOMDIR indexers return the same immutable structures, allowing the
GUI to inspect a study before any pixel data is decoded.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Iterator, Protocol, Sequence

from PySide6.QtCore import QObject, Signal

from medimager.core.study_model import classify_orientation


class LocalSourceKind(str, Enum):
    """Kinds of local sources understood by the workspace."""

    FOLDER = "folder"
    DICOMDIR = "dicomdir"
    IMAGE = "image"
    DEMO = "demo"
    # Read compatibility for early v2.6 development builds.
    SAMPLE = "sample"


class LocalOpenOrigin(str, Enum):
    """User-visible origin of an open request."""

    DIALOG = "dialog"
    STARTUP = "startup"
    RECENT = "recent"
    DRAG_DROP = "drag_drop"
    DEMO = "demo"
    SAMPLE = "sample"


class LocalIssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class LocalIssueCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_NOT_READABLE = "source_not_readable"
    EMPTY_SOURCE = "empty_source"
    CANCELLED = "cancelled"
    MISSING_REQUIRED_METADATA = "missing_required_metadata"
    UNREADABLE_INSTANCE = "unreadable_instance"
    UNSUPPORTED_INSTANCE = "unsupported_instance"
    MISSING_REFERENCE = "missing_reference"
    UNSAFE_REFERENCE = "unsafe_reference"
    DUPLICATE_REFERENCE = "duplicate_reference"
    DUPLICATE_UID = "duplicate_uid"
    STUDY_NOT_FOUND = "study_not_found"
    SERIES_NOT_FOUND = "series_not_found"


@dataclass(frozen=True)
class LocalOpenRequest:
    """A serializable request to inspect or open one local source."""

    request_id: str
    kind: LocalSourceKind
    source_path: str
    study_key: str | None = None
    selected_series_uids: tuple[str, ...] = ()
    origin: LocalOpenOrigin = LocalOpenOrigin.DIALOG

    @classmethod
    def create(
        cls,
        kind: LocalSourceKind | str,
        source_path: str | Path,
        *,
        study_key: str | None = None,
        selected_series_uids: Sequence[str] = (),
        origin: LocalOpenOrigin | str = LocalOpenOrigin.DIALOG,
    ) -> "LocalOpenRequest":
        kind_value = LocalSourceKind(kind)
        origin_value = LocalOpenOrigin(origin)
        canonical = canonical_source_path(source_path)
        request_seed = "\0".join(
            (
                kind_value.value,
                canonical,
                str(study_key or ""),
                *sorted(str(value) for value in selected_series_uids),
                str(time.time_ns()),
            )
        )
        request_id = hashlib.sha256(request_seed.encode("utf-8", "replace")).hexdigest()[:24]
        return cls(
            request_id=request_id,
            kind=kind_value,
            source_path=canonical,
            study_key=study_key,
            selected_series_uids=tuple(str(value) for value in selected_series_uids),
            origin=origin_value,
        )


@dataclass(frozen=True)
class LocalSourceIssue:
    """One non-PHI diagnostic produced while indexing a source."""

    code: LocalIssueCode
    severity: LocalIssueSeverity
    detail: str = ""
    reference: str = ""


@dataclass(frozen=True)
class LocalSeriesSource:
    """Metadata and paths sufficient to enqueue an existing series loader."""

    patient_name: str = ""
    patient_id: str = ""
    study_description: str = ""
    series_description: str = ""
    modality: str = ""
    acquisition_date: str = ""
    acquisition_time: str = ""
    study_date: str = ""
    study_time: str = ""
    protocol_name: str = ""
    body_part_examined: str = ""
    slice_count: int = 0
    series_number: str = ""
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    frame_of_reference_uid: str = ""
    orientation: str = "unknown"
    file_paths: tuple[str, ...] = ()
    sop_class_uid: str = ""
    is_viewable: bool = True
    unsupported_reason: str = ""

    def to_series_info(self, series_id: str):
        """Create the existing mutable ``SeriesInfo`` at the integration edge."""

        from medimager.core.multi_series_manager import SeriesInfo

        return SeriesInfo(
            series_id=str(series_id),
            patient_name=self.patient_name,
            patient_id=self.patient_id,
            study_description=self.study_description,
            series_description=self.series_description,
            modality=self.modality,
            acquisition_date=self.acquisition_date,
            acquisition_time=self.acquisition_time,
            study_date=self.study_date,
            study_time=self.study_time,
            protocol_name=self.protocol_name,
            body_part_examined=self.body_part_examined,
            slice_count=max(0, int(self.slice_count)),
            series_number=self.series_number,
            study_instance_uid=self.study_instance_uid,
            series_instance_uid=self.series_instance_uid,
            frame_of_reference_uid=self.frame_of_reference_uid,
            orientation=self.orientation,
            is_loaded=False,
            file_paths=list(self.file_paths),
        )


@dataclass(frozen=True)
class LocalStudyCandidate:
    """One study shown in a local-media selection UI."""

    study_key: str
    study_instance_uid: str
    patient_name: str
    patient_id: str
    study_description: str
    study_date: str
    modalities: tuple[str, ...]
    series: tuple[LocalSeriesSource, ...]

    @property
    def series_count(self) -> int:
        return len(self.series)

    @property
    def instance_count(self) -> int:
        return sum(max(0, int(item.slice_count)) for item in self.series)


@dataclass(frozen=True)
class LocalSelection:
    """Selection emitted by the media browser."""

    study_keys: tuple[str, ...] = ()
    series_uids: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.study_keys and not self.series_uids


@dataclass(frozen=True)
class LocalIndexResult:
    """Immutable output shared by folder and DICOMDIR indexers."""

    request: LocalOpenRequest
    studies: tuple[LocalStudyCandidate, ...] = ()
    issues: tuple[LocalSourceIssue, ...] = ()
    candidate_count: int = 0
    skipped_count: int = 0
    media_root: str = ""
    cancelled: bool = False

    @property
    def has_fatal_issue(self) -> bool:
        return any(issue.severity is LocalIssueSeverity.FATAL for issue in self.issues)

    @property
    def is_usable(self) -> bool:
        return bool(self.studies) and not self.cancelled and not self.has_fatal_issue

    def iter_series(self) -> Iterator[LocalSeriesSource]:
        for study in self.studies:
            yield from (series for series in study.series if series.is_viewable)

    def find_study(self, study_key: str) -> LocalStudyCandidate | None:
        return next((study for study in self.studies if study.study_key == study_key), None)

    def select(self, selection: LocalSelection) -> tuple[LocalSeriesSource, ...]:
        study_keys = set(selection.study_keys)
        series_uids = set(selection.series_uids)
        selected: list[LocalSeriesSource] = []
        for study in self.studies:
            if study.study_key in study_keys:
                selected.extend(item for item in study.series if item.is_viewable)
                continue
            selected.extend(
                item
                for item in study.series
                if item.is_viewable and item.series_instance_uid in series_uids
            )
        return tuple(selected)


@dataclass(frozen=True)
class LocalOpenSummary:
    request_id: str
    successful_series: int
    failed_series: int
    cancelled_series: int = 0

    @property
    def succeeded(self) -> bool:
        return self.successful_series > 0


def canonical_source_path(path: str | Path) -> str:
    """Return a stable absolute path without requiring the source to exist."""

    return str(Path(path).expanduser().resolve(strict=False))


def study_key_for_uid(uid: str, *, fallback_seed: str = "") -> str:
    """Return a non-reversible stable key suitable for local settings."""

    source = str(uid or "").strip() or str(fallback_seed or "").strip()
    if not source:
        source = "unknown-study"
    return hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()[:24]


def source_key(kind: LocalSourceKind | str, source_path: str | Path) -> str:
    kind_value = LocalSourceKind(kind)
    seed = f"{kind_value.value}\0{canonical_source_path(source_path)}"
    return hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:24]


def _series_sort_key(item: LocalSeriesSource) -> tuple[int, object, str]:
    try:
        number: tuple[int, object] = (0, int(str(item.series_number).strip()))
    except (TypeError, ValueError):
        number = (1, str(item.series_number or "").casefold())
    return number[0], number[1], item.series_instance_uid or item.series_description.casefold()


def build_study_candidates(
    series_sources: Iterable[LocalSeriesSource],
    *,
    source_seed: str = "",
) -> tuple[LocalStudyCandidate, ...]:
    """Group typed series into a deterministic Patient/Study hierarchy."""

    groups: dict[str, list[LocalSeriesSource]] = {}
    for item in series_sources:
        fallback = "\0".join(
            (
                source_seed,
                item.patient_id,
                item.study_date,
                item.study_description,
            )
        )
        key = study_key_for_uid(item.study_instance_uid, fallback_seed=fallback)
        groups.setdefault(key, []).append(item)

    studies: list[LocalStudyCandidate] = []
    for key, values in groups.items():
        ordered = tuple(sorted(values, key=_series_sort_key))
        first = ordered[0]
        modalities = tuple(
            sorted({value.modality.upper() for value in ordered if value.modality})
        )
        studies.append(
            LocalStudyCandidate(
                study_key=key,
                study_instance_uid=first.study_instance_uid,
                patient_name=first.patient_name,
                patient_id=first.patient_id,
                study_description=first.study_description,
                study_date=first.study_date,
                modalities=modalities,
                series=ordered,
            )
        )
    return tuple(
        sorted(
            studies,
            key=lambda study: (
                study.patient_name.casefold(),
                study.study_date,
                study.study_description.casefold(),
                study.study_key,
            ),
        )
    )


def apply_request_filters(
    request: LocalOpenRequest,
    studies: Sequence[LocalStudyCandidate],
    issues: Sequence[LocalSourceIssue] = (),
) -> tuple[tuple[LocalStudyCandidate, ...], tuple[LocalSourceIssue, ...]]:
    """Apply recent-entry or explicit-series filters to an index result."""

    filtered = tuple(studies)
    result_issues = list(issues)
    if request.study_key:
        filtered = tuple(study for study in filtered if study.study_key == request.study_key)
        if not filtered:
            result_issues.append(
                LocalSourceIssue(
                    LocalIssueCode.STUDY_NOT_FOUND,
                    LocalIssueSeverity.ERROR,
                    "The requested study is no longer present in this source.",
                )
            )
    if request.selected_series_uids and filtered:
        wanted = set(request.selected_series_uids)
        selected_studies: list[LocalStudyCandidate] = []
        found: set[str] = set()
        for study in filtered:
            selected = tuple(
                item for item in study.series if item.series_instance_uid in wanted
            )
            if selected:
                found.update(item.series_instance_uid for item in selected)
                selected_studies.append(replace(study, series=selected))
        filtered = tuple(selected_studies)
        missing = wanted - found
        if missing:
            result_issues.append(
                LocalSourceIssue(
                    LocalIssueCode.SERIES_NOT_FOUND,
                    LocalIssueSeverity.WARNING,
                    f"{len(missing)} requested series are no longer present.",
                )
            )
    return filtered, tuple(result_issues)


def index_dicom_folder(
    request: LocalOpenRequest,
    *,
    recursive: bool = True,
    include_extensionless: bool = True,
    strict_metadata: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> LocalIndexResult:
    """Read only DICOM headers in a folder and return a typed study index."""

    if request.kind is not LocalSourceKind.FOLDER:
        return _fatal_result(
            request,
            LocalIssueCode.INVALID_REQUEST,
            "Folder indexer received a non-folder request.",
        )
    folder = Path(request.source_path)
    if not folder.is_dir():
        return _fatal_result(
            request,
            LocalIssueCode.SOURCE_NOT_FOUND,
            "The selected folder is unavailable.",
        )

    suffixes = {".dcm", ".dicom", ".ima"}
    if include_extensionless:
        suffixes.add("")
    candidates = folder.rglob("*") if recursive else folder.glob("*")
    paths = tuple(
        sorted(
            (
                path
                for path in candidates
                if path.is_file() and path.suffix.casefold() in suffixes
            ),
            key=lambda value: str(value).casefold(),
        )
    )
    if cancelled and cancelled():
        return _cancelled_result(request, media_root=str(folder), candidate_count=len(paths))
    if not paths:
        return LocalIndexResult(
            request=request,
            issues=(
                LocalSourceIssue(
                    LocalIssueCode.EMPTY_SOURCE,
                    LocalIssueSeverity.WARNING,
                    "No candidate DICOM files were found.",
                ),
            ),
            media_root=canonical_source_path(folder),
        )

    import pydicom

    required_tags = (
        "SeriesInstanceUID",
        "StudyInstanceUID",
        "Modality",
        "Rows",
        "Columns",
        "PhotometricInterpretation",
    )
    tags = [
        *required_tags,
        "PatientName",
        "PatientID",
        "StudyDescription",
        "SeriesDescription",
        "AcquisitionDate",
        "AcquisitionTime",
        "StudyDate",
        "StudyTime",
        "ProtocolName",
        "BodyPartExamined",
        "NumberOfFrames",
        "SeriesNumber",
        "FrameOfReferenceUID",
        "ImageOrientationPatient",
    ]
    grouped: dict[str, list[tuple[str, object]]] = {}
    issues: list[LocalSourceIssue] = []
    for path in paths:
        if cancelled and cancelled():
            return _cancelled_result(
                request,
                media_root=str(folder),
                candidate_count=len(paths),
                issues=issues,
            )
        try:
            dataset = pydicom.dcmread(
                str(path),
                stop_before_pixels=True,
                force=True,
                specific_tags=tags,
            )
            series_uid = str(getattr(dataset, "SeriesInstanceUID", "") or "")
            if not series_uid:
                series_uid = f"missing:{canonical_source_path(path)}"
            grouped.setdefault(series_uid, []).append((str(path), dataset))
        except Exception:
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.UNREADABLE_INSTANCE,
                    LocalIssueSeverity.WARNING,
                    "A candidate file could not be read as DICOM.",
                    reference=path.name,
                )
            )

    sources: list[LocalSeriesSource] = []
    skipped = 0
    for grouped_items in grouped.values():
        first_path, first = grouped_items[0]
        missing = [tag for tag in required_tags if not getattr(first, tag, None)]
        if strict_metadata and missing:
            skipped += 1
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.MISSING_REQUIRED_METADATA,
                    LocalIssueSeverity.WARNING,
                    ", ".join(missing),
                    reference=Path(first_path).name,
                )
            )
            continue
        sources.append(_series_source_from_dataset(first, [item[0] for item in grouped_items]))

    studies = build_study_candidates(sources, source_seed=canonical_source_path(folder))
    studies, filtered_issues = apply_request_filters(request, studies, issues)
    return LocalIndexResult(
        request=request,
        studies=studies,
        issues=filtered_issues,
        candidate_count=len(paths),
        skipped_count=skipped + len(paths) - sum(len(value) for value in grouped.values()),
        media_root=canonical_source_path(folder),
    )


def index_local_source(
    request: LocalOpenRequest,
    *,
    recursive: bool = True,
    include_extensionless: bool = True,
    strict_metadata: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> LocalIndexResult:
    """Dispatch a worker-safe request to the matching read-only indexer."""

    if request.kind is LocalSourceKind.FOLDER:
        return index_dicom_folder(
            request,
            recursive=recursive,
            include_extensionless=include_extensionless,
            strict_metadata=strict_metadata,
            cancelled=cancelled,
        )
    if request.kind in {LocalSourceKind.DEMO, LocalSourceKind.SAMPLE}:
        folder_request = replace(request, kind=LocalSourceKind.FOLDER)
        result = index_dicom_folder(
            folder_request,
            recursive=recursive,
            include_extensionless=include_extensionless,
            strict_metadata=strict_metadata,
            cancelled=cancelled,
        )
        return replace(result, request=request)
    if request.kind is LocalSourceKind.DICOMDIR:
        # Local import keeps the shared contracts free of a module cycle.
        from medimager.core.dicomdir_index import index_dicomdir

        return index_dicomdir(request, cancelled=cancelled)
    if request.kind is LocalSourceKind.IMAGE:
        return index_image_source(request, cancelled=cancelled)
    return _fatal_result(
        request,
        LocalIssueCode.INVALID_REQUEST,
        f"Source kind '{request.kind.value}' does not provide a study index.",
    )


def index_image_source(
    request: LocalOpenRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> LocalIndexResult:
    """Represent one ordinary image as a local study without decoding pixels."""

    if request.kind is not LocalSourceKind.IMAGE:
        return _fatal_result(
            request,
            LocalIssueCode.INVALID_REQUEST,
            "Image indexer received a non-image request.",
        )
    path = Path(request.source_path)
    if not path.is_file():
        return _fatal_result(
            request,
            LocalIssueCode.SOURCE_NOT_FOUND,
            "The selected image is unavailable.",
        )
    if cancelled and cancelled():
        return LocalIndexResult(
            request=request,
            issues=(
                LocalSourceIssue(
                    LocalIssueCode.CANCELLED,
                    LocalIssueSeverity.INFO,
                    "Image inspection was cancelled.",
                ),
            ),
            candidate_count=1,
            media_root=canonical_source_path(path.parent),
            cancelled=True,
        )
    supported = {"", ".dcm", ".dicom", ".ima", ".npy", ".png", ".jpg", ".jpeg", ".bmp"}
    if path.suffix.casefold() not in supported:
        return _fatal_result(
            request,
            LocalIssueCode.UNSUPPORTED_INSTANCE,
            "The selected image format is not supported.",
        )
    source = LocalSeriesSource(
        series_description=path.name,
        modality="IMG",
        slice_count=1,
        series_number="1",
        file_paths=(canonical_source_path(path),),
    )
    studies = build_study_candidates(
        (source,),
        source_seed=f"image\0{canonical_source_path(path)}",
    )
    studies, issues = apply_request_filters(request, studies, ())
    return LocalIndexResult(
        request=request,
        studies=studies,
        issues=issues,
        candidate_count=1,
        media_root=canonical_source_path(path.parent),
    )


def _series_source_from_dataset(dataset, file_paths: Sequence[str]) -> LocalSeriesSource:
    if len(file_paths) == 1:
        try:
            slice_count = max(1, int(getattr(dataset, "NumberOfFrames", 1) or 1))
        except (TypeError, ValueError):
            slice_count = 1
    else:
        slice_count = len(file_paths)
    return LocalSeriesSource(
        patient_name=str(getattr(dataset, "PatientName", "") or ""),
        patient_id=str(getattr(dataset, "PatientID", "") or ""),
        study_description=str(getattr(dataset, "StudyDescription", "") or ""),
        series_description=str(getattr(dataset, "SeriesDescription", "") or ""),
        modality=str(getattr(dataset, "Modality", "") or ""),
        acquisition_date=str(getattr(dataset, "AcquisitionDate", "") or ""),
        acquisition_time=str(getattr(dataset, "AcquisitionTime", "") or ""),
        study_date=str(getattr(dataset, "StudyDate", "") or ""),
        study_time=str(getattr(dataset, "StudyTime", "") or ""),
        protocol_name=str(getattr(dataset, "ProtocolName", "") or ""),
        body_part_examined=str(getattr(dataset, "BodyPartExamined", "") or ""),
        slice_count=slice_count,
        series_number=str(getattr(dataset, "SeriesNumber", "") or ""),
        study_instance_uid=str(getattr(dataset, "StudyInstanceUID", "") or ""),
        series_instance_uid=str(getattr(dataset, "SeriesInstanceUID", "") or ""),
        frame_of_reference_uid=str(getattr(dataset, "FrameOfReferenceUID", "") or ""),
        orientation=classify_orientation(
            getattr(dataset, "ImageOrientationPatient", None)
        ).value,
        file_paths=tuple(canonical_source_path(path) for path in file_paths),
        sop_class_uid=str(getattr(dataset, "SOPClassUID", "") or ""),
    )


def _fatal_result(
    request: LocalOpenRequest,
    code: LocalIssueCode,
    detail: str,
) -> LocalIndexResult:
    return LocalIndexResult(
        request=request,
        issues=(LocalSourceIssue(code, LocalIssueSeverity.FATAL, detail),),
    )


def _cancelled_result(
    request: LocalOpenRequest,
    *,
    media_root: str = "",
    candidate_count: int = 0,
    issues: Sequence[LocalSourceIssue] = (),
) -> LocalIndexResult:
    return LocalIndexResult(
        request=request,
        issues=tuple(issues)
        + (
            LocalSourceIssue(
                LocalIssueCode.CANCELLED,
                LocalIssueSeverity.INFO,
                "Indexing was cancelled.",
            ),
        ),
        candidate_count=candidate_count,
        media_root=canonical_source_path(media_root) if media_root else "",
        cancelled=True,
    )


class SettingsStore(Protocol):
    def get_setting(self, key: str, default_value=None): ...

    def set_setting(self, key: str, value) -> None: ...


@dataclass(frozen=True)
class RecentStudyEntry:
    """A local pointer displayed by the startup center."""

    entry_id: str
    source_kind: LocalSourceKind
    source_path: str
    study_key: str
    display_label: str
    study_date: str
    modalities: tuple[str, ...]
    series_count: int
    last_opened_at: float
    pinned: bool = False
    patient_label: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["source_kind"] = self.source_kind.value
        payload["modalities"] = list(self.modalities)
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "RecentStudyEntry":
        return cls(
            entry_id=str(payload["entry_id"]),
            source_kind=LocalSourceKind(payload["source_kind"]),
            source_path=canonical_source_path(payload["source_path"]),
            study_key=str(payload["study_key"]),
            display_label=str(payload.get("display_label", "")),
            study_date=str(payload.get("study_date", "")),
            modalities=tuple(str(value) for value in payload.get("modalities", ())),
            series_count=max(0, int(payload.get("series_count", 0))),
            last_opened_at=float(payload.get("last_opened_at", 0.0)),
            pinned=bool(payload.get("pinned", False)),
            # v2.6 never persists PatientName or PatientID in recent-study
            # pointers.  Ignore labels written by development previews.
            patient_label="",
        )


class RecentStudyStore(QObject):
    """Versioned, bounded recent-study pointers backed by SettingsManager."""

    changed = Signal(object)

    DOCUMENT_KEY = "recent_studies.document"
    ENTRIES_KEY = "recent_studies.entries"
    SCHEMA_KEY = "recent_studies.schema"
    MAX_KEY = "recent_studies.max_items"
    PATIENT_LABELS_KEY = "recent_studies.persist_patient_labels"
    SCHEMA_VERSION = 1

    def __init__(self, settings: SettingsStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

    def entries(self) -> tuple[RecentStudyEntry, ...]:
        document = self._settings.get_setting(self.DOCUMENT_KEY, {})
        raw = (
            document.get("entries", [])
            if isinstance(document, dict)
            and int(document.get("schema_version", 0)) == self.SCHEMA_VERSION
            else self._settings.get_setting(self.ENTRIES_KEY, [])
        )
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = []
        if not isinstance(raw, (list, tuple)):
            return ()
        values: list[RecentStudyEntry] = []
        needs_privacy_scrub = False
        for payload in raw:
            if not isinstance(payload, dict):
                continue
            if any(
                str(payload.get(key, "") or "").strip()
                for key in ("patient_label", "patient_name", "patient_id")
            ):
                needs_privacy_scrub = True
            try:
                values.append(RecentStudyEntry.from_dict(payload))
            except (KeyError, TypeError, ValueError):
                continue
        ordered = tuple(
            sorted(values, key=lambda item: (not item.pinned, -item.last_opened_at))
        )
        if needs_privacy_scrub:
            self._write(ordered)
        return ordered

    def record_success(
        self,
        request: LocalOpenRequest,
        study: LocalStudyCandidate,
        *,
        successful_series: int,
        opened_at: float | None = None,
    ) -> RecentStudyEntry | None:
        if successful_series <= 0:
            return None
        source_path = canonical_source_path(request.source_path)
        entry_id = self._entry_id(request.kind, source_path, study.study_key)
        old = next((entry for entry in self.entries() if entry.entry_id == entry_id), None)
        label = study.study_description.strip() or Path(source_path).name or request.kind.value
        entry = RecentStudyEntry(
            entry_id=entry_id,
            source_kind=request.kind,
            source_path=source_path,
            study_key=study.study_key,
            display_label=label,
            study_date=study.study_date,
            modalities=study.modalities,
            series_count=study.series_count,
            last_opened_at=float(opened_at if opened_at is not None else time.time()),
            pinned=bool(old and old.pinned),
            patient_label="",
        )
        values = [candidate for candidate in self.entries() if candidate.entry_id != entry_id]
        values.append(entry)
        self._write(self._bounded(values))
        return entry

    def resolve_request(self, entry_id: str) -> LocalOpenRequest | None:
        entry = next((value for value in self.entries() if value.entry_id == entry_id), None)
        if entry is None:
            return None
        return LocalOpenRequest.create(
            entry.source_kind,
            entry.source_path,
            study_key=entry.study_key,
            origin=LocalOpenOrigin.RECENT,
        )

    def remove(self, entry_id: str) -> bool:
        values = [entry for entry in self.entries() if entry.entry_id != entry_id]
        if len(values) == len(self.entries()):
            return False
        self._write(values)
        return True

    def clear(self, *, include_pinned: bool = True) -> None:
        values = [] if include_pinned else [entry for entry in self.entries() if entry.pinned]
        self._write(values)

    def set_pinned(self, entry_id: str, pinned: bool) -> bool:
        changed = False
        values: list[RecentStudyEntry] = []
        for entry in self.entries():
            if entry.entry_id == entry_id:
                values.append(replace(entry, pinned=bool(pinned)))
                changed = entry.pinned != bool(pinned)
            else:
                values.append(entry)
        if changed:
            self._write(self._bounded(values))
        return changed

    def relocate(self, entry_id: str, source_path: str | Path) -> RecentStudyEntry | None:
        current = next((entry for entry in self.entries() if entry.entry_id == entry_id), None)
        if current is None:
            return None
        path = canonical_source_path(source_path)
        replacement = replace(
            current,
            entry_id=self._entry_id(current.source_kind, path, current.study_key),
            source_path=path,
        )
        values = [entry for entry in self.entries() if entry.entry_id != entry_id]
        values = [entry for entry in values if entry.entry_id != replacement.entry_id]
        values.append(replacement)
        self._write(self._bounded(values))
        return replacement

    @staticmethod
    def is_available(entry: RecentStudyEntry) -> bool:
        path = Path(entry.source_path)
        if entry.source_kind is LocalSourceKind.FOLDER:
            return path.is_dir()
        return path.is_file()

    def _bounded(self, values: Sequence[RecentStudyEntry]) -> list[RecentStudyEntry]:
        try:
            maximum = max(1, min(100, int(self._settings.get_setting(self.MAX_KEY, 20))))
        except (TypeError, ValueError):
            maximum = 20
        ordered = sorted(values, key=lambda item: (not item.pinned, -item.last_opened_at))
        pinned = [entry for entry in ordered if entry.pinned]
        unpinned = [entry for entry in ordered if not entry.pinned]
        return pinned + unpinned[: max(0, maximum - len(pinned))]

    def _write(self, values: Sequence[RecentStudyEntry]) -> None:
        ordered = sorted(
            (replace(entry, patient_label="") for entry in values),
            key=lambda item: (not item.pinned, -item.last_opened_at),
        )
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in ordered],
        }
        self._settings.set_setting(self.DOCUMENT_KEY, document)
        # Keep the v2.6 preview keys in sync for one release so development
        # builds written before the document schema remain readable.
        self._settings.set_setting(self.SCHEMA_KEY, self.SCHEMA_VERSION)
        self._settings.set_setting(self.ENTRIES_KEY, document["entries"])
        snapshot = tuple(ordered)
        self.changed.emit(snapshot)

    @staticmethod
    def _entry_id(
        kind: LocalSourceKind,
        source_path: str,
        study_key: str,
    ) -> str:
        seed = "\0".join((kind.value, canonical_source_path(source_path), study_key))
        return hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:24]


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = [
    "LocalIndexResult",
    "LocalIssueCode",
    "LocalIssueSeverity",
    "LocalOpenOrigin",
    "LocalOpenRequest",
    "LocalOpenSummary",
    "LocalSelection",
    "LocalSeriesSource",
    "LocalSourceIssue",
    "LocalSourceKind",
    "LocalStudyCandidate",
    "RecentStudyEntry",
    "RecentStudyStore",
    "apply_request_filters",
    "build_study_candidates",
    "canonical_source_path",
    "index_dicom_folder",
    "index_image_source",
    "index_local_source",
    "source_key",
    "study_key_for_uid",
]
