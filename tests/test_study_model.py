from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.study_model import SeriesOrientation, classify_orientation


def test_orientation_classifier_uses_lps_plane_normal():
    assert classify_orientation((1, 0, 0, 0, 1, 0)) is SeriesOrientation.AXIAL
    assert classify_orientation((1, 0, 0, 0, 0, -1)) is SeriesOrientation.CORONAL
    assert classify_orientation((0, 1, 0, 0, 0, -1)) is SeriesOrientation.SAGITTAL
    assert classify_orientation((0.8, 0.6, 0, 0, 0, -1)) is SeriesOrientation.OBLIQUE
    assert classify_orientation(None) is SeriesOrientation.UNKNOWN


def test_hierarchy_groups_by_stable_patient_and_study_uids(qapp):
    manager = MultiSeriesManager()
    manager.add_series(
        SeriesInfo(
            series_id="t2",
            patient_name="Example Person",
            patient_id="P-1",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.2",
            study_description="MR Brain",
            series_description="T2",
            modality="MR",
            study_date="20260102",
            series_number="2",
            slice_count=20,
            orientation="axial",
        )
    )
    manager.add_series(
        SeriesInfo(
            series_id="t1",
            patient_name="Example Person",
            patient_id="P-1",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.1",
            study_description="MR Brain",
            series_description="T1",
            modality="MR",
            study_date="20260102",
            series_number="1",
            slice_count=24,
            orientation="sagittal",
        )
    )

    hierarchy = manager.get_study_hierarchy()
    assert len(hierarchy.patients) == 1
    study = hierarchy.patients[0].studies[0]
    assert study.study_instance_uid == "1.2.3"
    assert study.modalities == ("MR",)
    assert [series.series_id for series in study.series] == ["t1", "t2"]
    assert hierarchy.study_for_series("t2") is study


def test_missing_uids_do_not_merge_unrelated_series(qapp):
    manager = MultiSeriesManager()
    manager.add_series(SeriesInfo(series_id="one", study_description="Unknown"))
    manager.add_series(SeriesInfo(series_id="two", study_description="Unknown"))

    hierarchy = manager.get_study_hierarchy()
    assert len(hierarchy.patients) == 2
    assert hierarchy.series_to_study["one"] != hierarchy.series_to_study["two"]
