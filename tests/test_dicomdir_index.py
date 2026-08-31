from __future__ import annotations

from pathlib import Path

import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.fileset import FileSet
from pydicom.uid import (
    BasicTextSRStorage,
    CTImageStorage,
    ExplicitVRLittleEndian,
    MediaStorageDirectoryStorage,
    generate_uid,
)

from medimager.core.dicomdir_index import (
    _is_supported_image_dataset,
    index_dicomdir,
    is_safe_media_reference,
)
from medimager.core.local_source import (
    LocalIssueCode,
    LocalOpenRequest,
    LocalSourceKind,
)


def _write_image(
    path: Path,
    *,
    patient_id: str,
    study_uid: str,
    series_uid: str,
    instance_number: int,
) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.PatientName = f"Fixture^{patient_id}"
    dataset.PatientID = patient_id
    dataset.StudyInstanceUID = study_uid
    dataset.StudyID = f"ST-{patient_id}"
    dataset.StudyDate = "20260831"
    dataset.StudyTime = "120000"
    dataset.StudyDescription = "DICOMDIR fixture"
    dataset.SeriesInstanceUID = series_uid
    dataset.SeriesNumber = 1
    dataset.SeriesDescription = "Axial CT"
    dataset.Modality = "CT"
    dataset.InstanceNumber = instance_number
    dataset.Rows = 2
    dataset.Columns = 3
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelRepresentation = 0
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.PixelData = b"\0" * 12
    dataset.save_as(path, enforce_file_format=True)


def _build_fileset(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    media = tmp_path / "media"
    inputs.mkdir()
    study_a = generate_uid()
    study_b = generate_uid()
    series_a = generate_uid()
    series_b = generate_uid()
    paths = []
    for index in (1, 2):
        path = inputs / f"a-{index}.dcm"
        _write_image(
            path,
            patient_id="P-A",
            study_uid=study_a,
            series_uid=series_a,
            instance_number=index,
        )
        paths.append(path)
    path = inputs / "b-1.dcm"
    _write_image(
        path,
        patient_id="P-B",
        study_uid=study_b,
        series_uid=series_b,
        instance_number=1,
    )
    paths.append(path)
    fileset = FileSet()
    for source in paths:
        fileset.add(source)
    fileset.write(media)
    return media / "DICOMDIR"


def _build_duplicate_series_uid_fileset(tmp_path: Path) -> Path:
    inputs = tmp_path / "duplicate-inputs"
    media = tmp_path / "duplicate-media"
    inputs.mkdir()
    reused_series_uid = generate_uid()
    for index, (patient_id, study_uid) in enumerate(
        (("P-A", generate_uid()), ("P-B", generate_uid())), start=1
    ):
        path = inputs / f"study-{index}.dcm"
        _write_image(
            path,
            patient_id=patient_id,
            study_uid=study_uid,
            series_uid=reused_series_uid,
            instance_number=1,
        )
    fileset = FileSet()
    for source in sorted(inputs.iterdir()):
        fileset.add(source)
    fileset.write(media)
    return media / "DICOMDIR"


def _write_malicious_dicomdir(path: Path, file_id: str) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = MediaStorageDirectoryStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.FileSetID = "SECURITY"
    dataset.OffsetOfTheFirstDirectoryRecordOfTheRootDirectoryEntity = 0
    dataset.OffsetOfTheLastDirectoryRecordOfTheRootDirectoryEntity = 0
    record = Dataset()
    record.OffsetOfTheNextDirectoryRecord = 0
    record.RecordInUseFlag = 0xFFFF
    record.OffsetOfReferencedLowerLevelDirectoryEntity = 0
    record.DirectoryRecordType = "IMAGE"
    record.ReferencedFileID = file_id
    dataset.DirectoryRecordSequence = [record]
    dataset.save_as(path, enforce_file_format=True)


def test_dicomdir_index_reads_real_fileset_and_groups_studies(tmp_path):
    dicomdir = _build_fileset(tmp_path)
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request)

    assert result.is_usable
    assert result.candidate_count == 3
    assert len(result.studies) == 2
    assert sorted(study.series_count for study in result.studies) == [1, 1]
    assert sorted(study.instance_count for study in result.studies) == [1, 2]
    assert all(Path(path).is_file() for series in result.iter_series() for path in series.file_paths)
    assert all(
        is_safe_media_reference(result.media_root, path)
        for series in result.iter_series()
        for path in series.file_paths
    )


def test_duplicate_series_uid_across_studies_is_reported_and_not_merged(tmp_path):
    dicomdir = _build_duplicate_series_uid_fileset(tmp_path)
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request)

    assert result.is_usable
    assert len(result.studies) == 2
    assert [study.series_count for study in result.studies] == [1, 1]
    assert [study.instance_count for study in result.studies] == [1, 1]
    assert any(issue.code is LocalIssueCode.DUPLICATE_UID for issue in result.issues)


def test_dicomdir_index_returns_structured_fatal_error_for_invalid_file(tmp_path):
    invalid = tmp_path / "DICOMDIR"
    invalid.write_text("not dicom", encoding="utf-8")
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, invalid)

    result = index_dicomdir(request)

    assert result.has_fatal_issue
    assert not result.studies
    assert result.issues[-1].code is LocalIssueCode.SOURCE_NOT_READABLE
    assert str(tmp_path) not in result.issues[-1].detail


def test_dicomdir_index_rejects_readable_dicom_with_wrong_sop_class(tmp_path):
    image = tmp_path / "looks-like-dicomdir"
    _write_image(
        image,
        patient_id="P-WRONG",
        study_uid=generate_uid(),
        series_uid=generate_uid(),
        instance_number=1,
    )
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, image)

    result = index_dicomdir(request)

    assert result.has_fatal_issue
    assert result.issues[-1].code is LocalIssueCode.INVALID_REQUEST
    assert "Media Storage Directory" in result.issues[-1].detail


def test_dicomdir_index_can_be_cancelled_without_returning_partial_studies(tmp_path):
    dicomdir = _build_fileset(tmp_path)
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request, cancelled=lambda: True)

    assert result.cancelled
    assert not result.studies
    assert result.issues[-1].code is LocalIssueCode.CANCELLED


def test_dicomdir_missing_reference_is_reported_and_other_series_remain_usable(tmp_path):
    dicomdir = _build_fileset(tmp_path)
    file_set = FileSet(dicomdir)
    missing_path = Path(next(iter(file_set)).path)
    missing_path.unlink()
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request)

    assert any(issue.code is LocalIssueCode.MISSING_REFERENCE for issue in result.issues)
    assert result.studies


def test_media_reference_rejects_parent_escape(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    inside = media_root / "PT000001" / "image.dcm"
    outside = tmp_path / "outside.dcm"

    assert is_safe_media_reference(media_root, inside)
    assert not is_safe_media_reference(media_root, outside)


def test_media_reference_rejects_symlink_escape(tmp_path):
    media_root = tmp_path / "media"
    outside = tmp_path / "outside"
    media_root.mkdir()
    outside.mkdir()
    (outside / "image.dcm").write_bytes(b"outside")
    link = media_root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {type(error).__name__}")

    assert not is_safe_media_reference(media_root, link / "image.dcm")


def test_media_reference_containment_is_case_insensitive_on_windows(tmp_path):
    media_root = tmp_path / "MixedCaseMedia"
    media_root.mkdir()
    differently_cased_root = Path(str(media_root).swapcase())
    candidate = media_root / "IMAGE.DCM"

    if differently_cased_root.drive:
        assert is_safe_media_reference(differently_cased_root, candidate)


@pytest.mark.parametrize(
    "file_id",
    (r"..\outside.dcm", r"C:\outside.dcm", r"\\server\share\outside.dcm"),
)
def test_dicomdir_rejects_unsafe_declared_reference_before_fileset_load(
    tmp_path, monkeypatch, file_id
):
    dicomdir = tmp_path / "DICOMDIR"
    _write_malicious_dicomdir(dicomdir, file_id)

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("unsafe DICOMDIR reached FileSet.load")

    monkeypatch.setattr(FileSet, "load", fail_if_loaded)
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request)

    assert result.has_fatal_issue
    assert any(issue.code is LocalIssueCode.UNSAFE_REFERENCE for issue in result.issues)


def test_sr_with_image_like_tags_remains_non_viewable():
    dataset = Dataset()
    dataset.SOPClassUID = BasicTextSRStorage
    dataset.Rows = 512
    dataset.Columns = 512
    dataset.PhotometricInterpretation = "MONOCHROME2"

    assert not _is_supported_image_dataset(dataset)


def test_only_first_series_instance_is_read_for_supplemental_metadata(
    tmp_path, monkeypatch
):
    dicomdir = _build_fileset(tmp_path)
    referenced = {
        str(Path(instance.path).resolve()) for instance in FileSet(dicomdir)
    }
    real_dcmread = __import__("pydicom").dcmread
    opened_instances: list[str] = []

    def tracking_dcmread(path, *args, **kwargs):
        resolved = str(Path(path).resolve())
        if resolved in referenced:
            opened_instances.append(resolved)
        return real_dcmread(path, *args, **kwargs)

    monkeypatch.setattr("pydicom.dcmread", tracking_dcmread)
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)

    result = index_dicomdir(request)

    assert result.is_usable
    assert len(opened_instances) == len(tuple(result.iter_series()))
