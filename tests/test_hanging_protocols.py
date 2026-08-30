from medimager.core.hanging_protocols import (
    HangingProtocolId,
    build_hanging_plan,
)
from medimager.core.multi_series_manager import SeriesInfo


def _series(series_id, description, modality="MR", number="1"):
    return SeriesInfo(
        series_id=series_id,
        series_description=description,
        modality=modality,
        series_number=number,
        study_instance_uid="study-1",
        is_loaded=True,
    )


def test_mr_neuro_protocol_orders_named_contrasts_before_fallbacks():
    series = [
        _series("dwi", "DWI b1000", number="5"),
        _series("localizer", "Scout", number="1"),
        _series("flair", "Ax FLAIR", number="4"),
        _series("t2", "T2 TSE", number="3"),
        _series("t1", "3D T1 MPRAGE", number="2"),
    ]
    plan = build_hanging_plan(HangingProtocolId.MR_NEURO, series, "t1")
    assert plan.layout == (2, 2)
    assert plan.series_ids == ("t1", "t2", "flair", "dwi")


def test_ct_comparison_keeps_active_and_prefers_opposite_phase():
    series = [
        _series("plain", "Chest non contrast", "CT", "1"),
        _series("arterial", "Chest arterial contrast", "CT", "2"),
        _series("bone", "Bone recon", "CT", "3"),
    ]
    plan = build_hanging_plan(HangingProtocolId.CT_COMPARISON, series, "plain")
    assert plan.layout == (1, 2)
    assert plan.series_ids == ("plain", "arterial")


def test_protocol_never_crosses_the_active_study():
    active = _series("active", "T1")
    other = _series("other", "T2")
    other.study_instance_uid = "study-2"
    plan = build_hanging_plan(
        HangingProtocolId.STUDY_OVERVIEW, [active, other], "active"
    )
    assert plan.series_ids == ("active",)
