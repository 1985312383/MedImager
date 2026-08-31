"""Safe, read-only DICOMDIR indexing for local removable media."""

from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Sequence

from medimager.core.local_source import (
    LocalIndexResult,
    LocalIssueCode,
    LocalIssueSeverity,
    LocalOpenRequest,
    LocalSeriesSource,
    LocalSourceIssue,
    LocalSourceKind,
    _series_source_from_dataset,
    apply_request_filters,
    build_study_candidates,
    canonical_source_path,
)


def is_safe_media_reference(media_root: str | Path, reference: str | Path) -> bool:
    """Return whether a resolved File-set reference remains inside its media root."""

    try:
        root = Path(media_root).resolve(strict=False)
        candidate = Path(reference).resolve(strict=False)
        candidate.relative_to(root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def inspect_declared_references(
    dicomdir_path: str | Path,
    media_root: str | Path,
) -> tuple[int, tuple[LocalSourceIssue, ...]]:
    """Inspect public DirectoryRecordSequence references, including missing files.

    ``FileSet`` intentionally omits missing instances while iterating. Reading
    the directory records separately lets the UI report incomplete removable
    media instead of silently presenting a smaller study.
    """

    import pydicom

    dataset = pydicom.dcmread(
        str(dicomdir_path), stop_before_pixels=True, force=False
    )
    records = getattr(dataset, "DirectoryRecordSequence", ()) or ()
    issues: list[LocalSourceIssue] = []
    seen: set[str] = set()
    count = 0
    root = Path(media_root).resolve(strict=False)
    for record in records:
        file_id = getattr(record, "ReferencedFileID", None)
        if not file_id:
            continue
        reference, reference_name = _declared_reference_path(root, file_id)
        if reference is None:
            count += 1
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.UNSAFE_REFERENCE,
                    LocalIssueSeverity.ERROR,
                    "A directory record contains an absolute or traversing file reference.",
                    reference=reference_name,
                )
            )
            continue
        count += 1
        if not is_safe_media_reference(root, reference):
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.UNSAFE_REFERENCE,
                    LocalIssueSeverity.ERROR,
                    "A directory record points outside the media root.",
                    reference=reference.name,
                )
            )
            continue
        canonical = canonical_source_path(reference)
        if canonical in seen:
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.DUPLICATE_REFERENCE,
                    LocalIssueSeverity.INFO,
                    "A duplicate file reference was found in DICOMDIR.",
                    reference=reference.name,
                )
            )
            continue
        seen.add(canonical)
        if not reference.is_file():
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.MISSING_REFERENCE,
                    LocalIssueSeverity.WARNING,
                    "A referenced media file is missing.",
                    reference=reference.name,
                )
            )
    return count, tuple(issues)


def _declared_reference_path(
    media_root: Path, file_id,
) -> tuple[Path | None, str]:
    """Convert a DICOM File ID without laundering absolute Windows paths.

    A File ID is a relative list of components.  Splitting first and dropping
    empty components would turn ``\\\\server\\share`` or ``\\image.dcm`` into
    an apparently safe path below the media root, so reject drive-qualified,
    rooted, empty, and dot components before joining.
    """

    raw_values = (file_id,) if isinstance(file_id, str) else tuple(file_id)
    components: list[str] = []
    reference_name = ""
    for value in raw_values:
        raw = str(value)
        reference_name = raw.replace("\\", "/").rsplit("/", 1)[-1]
        windows_path = PureWindowsPath(raw)
        if (
            not raw
            or raw.startswith(("/", "\\"))
            or windows_path.drive
            or windows_path.is_absolute()
        ):
            return None, reference_name
        parts = raw.replace("\\", "/").split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return None, reference_name
        components.extend(parts)
    if not components:
        return None, reference_name
    return media_root.joinpath(*components), reference_name


def index_dicomdir(
    request: LocalOpenRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> LocalIndexResult:
    """Index one DICOMDIR without reading pixel data or mutating the File-set.

    Invalid directory records are reported as structured issues. Fatal parsing
    failures are returned as a result rather than raised across a worker-thread
    boundary.
    """

    if request.kind is not LocalSourceKind.DICOMDIR:
        return _fatal(
            request,
            LocalIssueCode.INVALID_REQUEST,
            "DICOMDIR indexer received a non-DICOMDIR request.",
        )
    dicomdir = Path(request.source_path)
    if not dicomdir.is_file():
        return _fatal(
            request,
            LocalIssueCode.SOURCE_NOT_FOUND,
            "The selected DICOMDIR is unavailable.",
        )
    media_root = dicomdir.parent.resolve(strict=False)

    directory_sop_status = _directory_storage_sop_status(dicomdir)
    if directory_sop_status is not True:
        return _fatal(
            request,
            (
                LocalIssueCode.SOURCE_NOT_READABLE
                if directory_sop_status is None
                else LocalIssueCode.INVALID_REQUEST
            ),
            (
                "The selected file is not readable as DICOM."
                if directory_sop_status is None
                else "The selected file is not a DICOM Media Storage Directory."
            ),
            media_root=media_root,
        )

    try:
        declared_count, declared_issues = inspect_declared_references(
            dicomdir, media_root
        )
    except Exception as error:
        return _fatal(
            request,
            LocalIssueCode.SOURCE_NOT_READABLE,
            _non_phi_exception_detail(error, "DICOMDIR records could not be read."),
            media_root=media_root,
        )

    # Validate every declared path before pydicom constructs a FileSet.  Its
    # default orphan handling may otherwise call ``FileSet.add()`` and read an
    # orphaned file outside the media root before the application can reject
    # the reference.
    if any(issue.code is LocalIssueCode.UNSAFE_REFERENCE for issue in declared_issues):
        return _fatal(
            request,
            LocalIssueCode.UNSAFE_REFERENCE,
            "The DICOMDIR contains a file reference outside its media root.",
            media_root=media_root,
            issues=declared_issues,
            candidate_count=declared_count,
        )

    try:
        from pydicom.fileset import FileSet

        with _suppress_fileset_missing_reference_warnings():
            file_set = FileSet()
            # Never ask pydicom to materialize orphan records: doing so may
            # read their target files.  Declared records are inspected above.
            file_set.load(str(dicomdir), include_orphans=False)
    except Exception as error:
        return _fatal(
            request,
            LocalIssueCode.SOURCE_NOT_READABLE,
            _non_phi_exception_detail(error, "The selected file is not a readable DICOMDIR."),
            media_root=media_root,
            issues=declared_issues,
            candidate_count=declared_count,
        )

    issues: list[LocalSourceIssue] = list(declared_issues)
    # A Series Instance UID is globally unique in a valid file-set, but damaged
    # removable media occasionally reuses one below two studies.  Keying only
    # by SeriesInstanceUID would silently mix those instances into one series.
    references: dict[tuple[str, str], list[Path]] = {}
    studies_by_series_uid: dict[str, set[str]] = {}
    seen_paths: set[str] = set()
    instance_count = 0

    try:
        with _suppress_fileset_missing_reference_warnings():
            instances: Iterable = file_set
            for instance in instances:
                if cancelled and cancelled():
                    return _cancelled(
                        request, media_root, max(instance_count, declared_count), issues
                    )
                instance_count += 1
                try:
                    referenced = Path(instance.path)
                except Exception:
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.MISSING_REFERENCE,
                            LocalIssueSeverity.WARNING,
                            "A directory record has no resolvable file reference.",
                        )
                    )
                    continue
                if not is_safe_media_reference(media_root, referenced):
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.UNSAFE_REFERENCE,
                            LocalIssueSeverity.ERROR,
                            "A directory record points outside the media root.",
                            reference=referenced.name,
                        )
                    )
                    continue
                canonical = canonical_source_path(referenced)
                if canonical in seen_paths:
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.DUPLICATE_REFERENCE,
                            LocalIssueSeverity.INFO,
                            "A duplicate file reference was ignored.",
                            reference=referenced.name,
                        )
                    )
                    continue
                seen_paths.add(canonical)
                if not referenced.is_file():
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.MISSING_REFERENCE,
                            LocalIssueSeverity.WARNING,
                            "A referenced media file is missing.",
                            reference=referenced.name,
                        )
                    )
                    continue
                series_uid = _instance_value(instance, "SeriesInstanceUID")
                if not series_uid:
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.MISSING_REQUIRED_METADATA,
                            LocalIssueSeverity.WARNING,
                            "A referenced instance has no Series Instance UID.",
                            reference=referenced.name,
                        )
                    )
                    continue
                study_uid = _instance_value(instance, "StudyInstanceUID")
                if not study_uid:
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.MISSING_REQUIRED_METADATA,
                            LocalIssueSeverity.WARNING,
                            "A directory record has no Study Instance UID.",
                            reference=referenced.name,
                        )
                    )
                    continue
                seen_studies = studies_by_series_uid.setdefault(series_uid, set())
                if study_uid and seen_studies and study_uid not in seen_studies:
                    issues.append(
                        LocalSourceIssue(
                            LocalIssueCode.DUPLICATE_UID,
                            LocalIssueSeverity.WARNING,
                            "A Series Instance UID is reused by multiple studies; "
                            "the series were kept separate.",
                            reference=referenced.name,
                        )
                    )
                if study_uid:
                    seen_studies.add(study_uid)
                references.setdefault((study_uid, series_uid), []).append(
                    referenced
                )
    except Exception as error:
        return _fatal(
            request,
            LocalIssueCode.SOURCE_NOT_READABLE,
            _non_phi_exception_detail(error, "DICOMDIR records could not be enumerated."),
            media_root=media_root,
            issues=issues,
            candidate_count=instance_count,
        )
    instance_count = max(instance_count, declared_count)

    sources: list[LocalSeriesSource] = []
    skipped = 0
    for (_study_uid, series_uid), paths in sorted(
        references.items(), key=lambda item: item[0]
    ):
        if cancelled and cancelled():
            return _cancelled(request, media_root, instance_count, issues)
        dataset, representative = _read_representative_header(paths)
        if dataset is None:
            skipped += 1
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.UNREADABLE_INSTANCE,
                    LocalIssueSeverity.WARNING,
                    "No readable instance was found for a referenced series.",
                    reference=representative,
                )
            )
            continue
        if not _is_supported_image_dataset(dataset):
            skipped += 1
            issues.append(
                LocalSourceIssue(
                    LocalIssueCode.UNSUPPORTED_INSTANCE,
                    LocalIssueSeverity.INFO,
                    "A non-image DICOM series is not viewable in this version.",
                    reference=representative,
                )
            )
            source = replace(
                _series_source_from_dataset(dataset, [str(path) for path in paths]),
                is_viewable=False,
                unsupported_reason=(
                    "Structured report, presentation state, key object, or another "
                    "non-image DICOM object is not viewable in this version."
                ),
            )
        else:
            source = _series_source_from_dataset(dataset, [str(path) for path in paths])
        # Directory records define the hierarchy; the first instance header
        # only supplements display and image metadata.
        source = replace(
            source,
            study_instance_uid=_study_uid,
            series_instance_uid=series_uid,
        )
        sources.append(source)

    studies = build_study_candidates(sources, source_seed=canonical_source_path(dicomdir))
    studies, filtered_issues = apply_request_filters(request, studies, issues)
    if not studies and not filtered_issues:
        filtered_issues = (
            LocalSourceIssue(
                LocalIssueCode.EMPTY_SOURCE,
                LocalIssueSeverity.WARNING,
                "The DICOMDIR contains no supported image series.",
            ),
        )
    return LocalIndexResult(
        request=request,
        studies=studies,
        issues=filtered_issues,
        candidate_count=instance_count,
        skipped_count=skipped + sum(
            1
            for issue in issues
            if issue.code
            in {
                LocalIssueCode.MISSING_REFERENCE,
                LocalIssueCode.UNSAFE_REFERENCE,
                LocalIssueCode.MISSING_REQUIRED_METADATA,
            }
        ),
        media_root=canonical_source_path(media_root),
    )


def _directory_storage_sop_status(path: Path) -> bool | None:
    """Validate the media-storage SOP class instead of trusting the filename."""

    try:
        import pydicom
        from pydicom.uid import MediaStorageDirectoryStorage

        dataset = pydicom.dcmread(
            str(path),
            stop_before_pixels=True,
            force=False,
            specific_tags=["SOPClassUID"],
        )
        declared = str(getattr(dataset, "SOPClassUID", "") or "")
        file_meta = getattr(dataset, "file_meta", None)
        media_storage = str(
            getattr(file_meta, "MediaStorageSOPClassUID", "") or ""
        )
        expected = str(MediaStorageDirectoryStorage)
        # PS3.10 requires the Media Storage SOP Class in file meta.  An
        # unrelated object must not pass by spoofing only dataset SOPClassUID.
        return media_storage == expected and (not declared or declared == expected)
    except Exception:
        return None


def _instance_value(instance, keyword: str) -> str:
    try:
        return str(getattr(instance, keyword, "") or "")
    except Exception:
        return ""


def _read_representative_header(paths: Sequence[Path]):
    import pydicom

    tags = [
        "PatientName",
        "PatientID",
        "StudyDescription",
        "SeriesDescription",
        "Modality",
        "AcquisitionDate",
        "AcquisitionTime",
        "StudyDate",
        "StudyTime",
        "ProtocolName",
        "BodyPartExamined",
        "NumberOfFrames",
        "SeriesNumber",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "FrameOfReferenceUID",
        "ImageOrientationPatient",
        "Rows",
        "Columns",
        "SamplesPerPixel",
        "PhotometricInterpretation",
        "SOPClassUID",
    ]
    if not paths:
        return None, ""
    path = paths[0]
    try:
        return (
            pydicom.dcmread(
                str(path),
                stop_before_pixels=True,
                force=False,
                specific_tags=tags,
            ),
            path.name,
        )
    except Exception:
        return None, path.name


def _is_supported_image_dataset(dataset) -> bool:
    sop_class_uid = str(getattr(dataset, "SOPClassUID", "") or "")
    if sop_class_uid.startswith(
        (
            "1.2.840.10008.5.1.4.1.1.11.",  # Presentation States
            "1.2.840.10008.5.1.4.1.1.88.",  # SR and Key Object documents
        )
    ):
        return False
    try:
        rows = int(getattr(dataset, "Rows", 0) or 0)
        columns = int(getattr(dataset, "Columns", 0) or 0)
    except (TypeError, ValueError):
        return False
    return rows > 0 and columns > 0 and bool(
        getattr(dataset, "PhotometricInterpretation", None)
    )


def _non_phi_exception_detail(error: Exception, fallback: str) -> str:
    """Keep fatal diagnostics useful without echoing media paths or datasets."""

    name = type(error).__name__
    return f"{fallback} ({name})" if name else fallback


class _MissingReferenceLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith(
            "The referenced SOP Instance for the directory record"
        )


@contextmanager
def _suppress_fileset_missing_reference_warnings():
    """Replace pydicom's path-bearing warning with our structured issue."""

    logger = logging.getLogger("pydicom")
    log_filter = _MissingReferenceLogFilter()
    logger.addFilter(log_filter)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"The referenced SOP Instance for the directory record.*",
                category=UserWarning,
            )
            yield
    finally:
        logger.removeFilter(log_filter)


def _fatal(
    request: LocalOpenRequest,
    code: LocalIssueCode,
    detail: str,
    *,
    media_root: str | Path = "",
    issues: Sequence[LocalSourceIssue] = (),
    candidate_count: int = 0,
) -> LocalIndexResult:
    return LocalIndexResult(
        request=request,
        issues=tuple(issues)
        + (LocalSourceIssue(code, LocalIssueSeverity.FATAL, detail),),
        candidate_count=candidate_count,
        media_root=canonical_source_path(media_root) if media_root else "",
    )


def _cancelled(
    request: LocalOpenRequest,
    media_root: str | Path,
    candidate_count: int,
    issues: Sequence[LocalSourceIssue],
) -> LocalIndexResult:
    return LocalIndexResult(
        request=request,
        issues=tuple(issues)
        + (
            LocalSourceIssue(
                LocalIssueCode.CANCELLED,
                LocalIssueSeverity.INFO,
                "DICOMDIR indexing was cancelled.",
            ),
        ),
        candidate_count=candidate_count,
        media_root=canonical_source_path(media_root),
        cancelled=True,
    )


__all__ = [
    "index_dicomdir",
    "inspect_declared_references",
    "is_safe_media_reference",
]
