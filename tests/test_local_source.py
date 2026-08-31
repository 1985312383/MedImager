from __future__ import annotations

import json
from pathlib import Path

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from medimager.core.local_source import (
    LocalIssueCode,
    LocalOpenOrigin,
    LocalOpenRequest,
    LocalSelection,
    LocalSeriesSource,
    LocalSourceKind,
    RecentStudyStore,
    apply_request_filters,
    build_study_candidates,
    index_dicom_folder,
    index_local_source,
    study_key_for_uid,
)


class _MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def _source(
    series_uid: str,
    *,
    study_uid: str = "1.2.3",
    patient: str = "Patient One",
    number: str = "1",
) -> LocalSeriesSource:
    return LocalSeriesSource(
        patient_name=patient,
        patient_id="P001",
        study_description="Chest follow-up",
        series_description=f"Series {number}",
        modality="CT",
        study_date="20260831",
        slice_count=8,
        series_number=number,
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
        file_paths=(f"C:/media/{series_uid}.dcm",),
    )


def _write_dicom(path: Path, *, study_uid: str, series_uid: str, instance: int) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.PatientName = "Fixture^Patient"
    dataset.PatientID = "FIXTURE-1"
    dataset.StudyInstanceUID = study_uid
    dataset.StudyID = "STUDY1"
    dataset.StudyDate = "20260831"
    dataset.StudyTime = "101010"
    dataset.StudyDescription = "Fixture study"
    dataset.SeriesInstanceUID = series_uid
    dataset.SeriesNumber = 3
    dataset.SeriesDescription = "Axial fixture"
    dataset.Modality = "CT"
    dataset.InstanceNumber = instance
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelRepresentation = 0
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.PixelData = b"\0" * 8
    dataset.save_as(path, enforce_file_format=True)


def test_study_candidates_are_stable_and_series_number_sorted():
    studies = build_study_candidates(
        (_source("1.2.3.2", number="20"), _source("1.2.3.1", number="2")),
        source_seed="media-a",
    )

    assert len(studies) == 1
    assert studies[0].study_key == study_key_for_uid("1.2.3")
    assert [item.series_number for item in studies[0].series] == ["2", "20"]
    assert studies[0].modalities == ("CT",)
    assert studies[0].instance_count == 16


def test_request_filters_study_and_series_without_mutating_source():
    studies = build_study_candidates(
        (_source("series-a"), _source("series-b"), _source("series-c", study_uid="9.8.7"))
    )
    request = LocalOpenRequest.create(
        LocalSourceKind.FOLDER,
        ".",
        study_key=study_key_for_uid("1.2.3"),
        selected_series_uids=("series-b", "missing"),
    )

    filtered, issues = apply_request_filters(request, studies)

    assert len(filtered) == 1
    assert [item.series_instance_uid for item in filtered[0].series] == ["series-b"]
    original = next(study for study in studies if study.study_key == request.study_key)
    assert len(original.series) == 2
    assert any(issue.code is LocalIssueCode.SERIES_NOT_FOUND for issue in issues)
    assert LocalSelection(series_uids=("series-b",)).is_empty is False


def test_recent_store_records_only_success_and_never_persists_patient_label(tmp_path):
    settings = _MemorySettings(
        {
            RecentStudyStore.MAX_KEY: 4,
            RecentStudyStore.PATIENT_LABELS_KEY: True,
        }
    )
    store = RecentStudyStore(settings)
    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)
    study = build_study_candidates((_source("series-a"),))[0]

    assert store.record_success(request, study, successful_series=0) is None
    entry = store.record_success(request, study, successful_series=1, opened_at=10.0)

    assert entry is not None
    assert entry.patient_label == ""
    assert store.entries() == (entry,)
    assert settings.values[RecentStudyStore.SCHEMA_KEY] == 1
    assert settings.values[RecentStudyStore.ENTRIES_KEY][0]["patient_label"] == ""
    reopened = store.resolve_request(entry.entry_id)
    assert reopened is not None
    assert reopened.kind is LocalSourceKind.FOLDER
    assert reopened.origin is LocalOpenOrigin.RECENT
    assert reopened.study_key == study.study_key


def test_recent_store_scrubs_patient_labels_from_legacy_documents(tmp_path):
    settings = _MemorySettings(
        {
            RecentStudyStore.DOCUMENT_KEY: {
                "schema_version": RecentStudyStore.SCHEMA_VERSION,
                "entries": [
                    {
                        "entry_id": "legacy-entry",
                        "source_kind": "folder",
                        "source_path": str(tmp_path),
                        "study_key": "safe-study-key",
                        "display_label": "Chest CT",
                        "study_date": "20260831",
                        "modalities": ["CT"],
                        "series_count": 1,
                        "last_opened_at": 1.0,
                        "patient_label": "Sensitive^Patient / P-123",
                    }
                ],
            }
        }
    )
    store = RecentStudyStore(settings)

    entries = store.entries()

    assert len(entries) == 1
    assert entries[0].patient_label == ""
    serialized = json.dumps(settings.values[RecentStudyStore.DOCUMENT_KEY])
    assert "Sensitive" not in serialized
    assert "P-123" not in serialized


def test_recent_store_pinning_bounding_relocation_and_removal(tmp_path):
    settings = _MemorySettings({RecentStudyStore.MAX_KEY: 2})
    store = RecentStudyStore(settings)
    entries = []
    for index, uid in enumerate(("1.2.1", "1.2.2"), start=1):
        folder = tmp_path / f"source-{index}"
        folder.mkdir()
        request = LocalOpenRequest.create(LocalSourceKind.FOLDER, folder)
        study = build_study_candidates((_source(f"series-{index}", study_uid=uid),))[0]
        entries.append(
            store.record_success(request, study, successful_series=1, opened_at=float(index))
        )
    assert entries[0] is not None
    assert store.set_pinned(entries[0].entry_id, True)

    third_folder = tmp_path / "source-3"
    third_folder.mkdir()
    third_study = build_study_candidates((_source("series-3", study_uid="1.2.3"),))[0]
    third = store.record_success(
        LocalOpenRequest.create(LocalSourceKind.FOLDER, third_folder),
        third_study,
        successful_series=1,
        opened_at=3.0,
    )

    current = store.entries()
    assert len(current) == 2
    assert current[0].pinned
    assert third in current
    relocated_folder = tmp_path / "relocated"
    relocated_folder.mkdir()
    relocated = store.relocate(third.entry_id, relocated_folder)
    assert relocated is not None
    assert relocated.source_path == str(relocated_folder.resolve())
    assert store.remove(relocated.entry_id)
    assert len(store.entries()) == 1


def test_folder_index_returns_typed_studies_and_honors_cancel(tmp_path):
    study_uid = generate_uid()
    series_uid = generate_uid()
    _write_dicom(tmp_path / "one.dcm", study_uid=study_uid, series_uid=series_uid, instance=1)
    _write_dicom(tmp_path / "two.ima", study_uid=study_uid, series_uid=series_uid, instance=2)
    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)

    result = index_dicom_folder(request)

    assert result.is_usable
    assert result.candidate_count == 2
    assert len(result.studies) == 1
    series = result.studies[0].series[0]
    assert series.series_instance_uid == series_uid
    assert series.slice_count == 2
    assert series.orientation == "axial"
    assert len(series.file_paths) == 2

    cancelled = index_dicom_folder(request, cancelled=lambda: True)
    assert cancelled.cancelled
    assert not cancelled.studies
    assert cancelled.issues[-1].code is LocalIssueCode.CANCELLED


def test_local_source_dispatch_indexes_image_without_decoding_pixels(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"not decoded during indexing")
    request = LocalOpenRequest.create(LocalSourceKind.IMAGE, image)

    result = index_local_source(request)

    assert result.is_usable
    assert result.candidate_count == 1
    series = result.studies[0].series[0]
    assert series.modality == "IMG"
    assert series.series_description == "image.png"
    assert series.file_paths == (str(image.resolve()),)


def test_demo_source_reuses_folder_indexer_but_preserves_source_kind(tmp_path):
    request = LocalOpenRequest.create(LocalSourceKind.DEMO, tmp_path)

    result = index_local_source(request)

    assert result.request.kind is LocalSourceKind.DEMO
    assert not result.has_fatal_issue
