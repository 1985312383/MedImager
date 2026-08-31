from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton

from medimager.core.local_source import (
    LocalIndexResult,
    LocalOpenRequest,
    LocalSeriesSource,
    LocalSourceKind,
    RecentStudyEntry,
    build_study_candidates,
)
from medimager.ui.media_browser import MediaBrowserPage
from medimager.ui.start_center import (
    RecentAvailability,
    StartCenter,
    StartCenterSample,
    StartCenterState,
)


def _index_result() -> LocalIndexResult:
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, "DICOMDIR")
    series = (
        LocalSeriesSource(
            patient_name="Fixture Patient",
            patient_id="P1",
            study_description="Fixture study",
            series_description="Axial",
            modality="CT",
            study_date="20260831",
            slice_count=12,
            series_number="1",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.1",
            file_paths=("one.dcm",),
        ),
        LocalSeriesSource(
            patient_name="Fixture Patient",
            patient_id="P1",
            study_description="Fixture study",
            series_description="Coronal",
            modality="CT",
            study_date="20260831",
            slice_count=8,
            series_number="2",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.2",
            file_paths=("two.dcm",),
        ),
    )
    return LocalIndexResult(
        request=request,
        studies=build_study_candidates(series),
        candidate_count=2,
        media_root="C:/media",
    )


def _recent(entry_id="recent-1") -> RecentStudyEntry:
    return RecentStudyEntry(
        entry_id=entry_id,
        source_kind=LocalSourceKind.FOLDER,
        source_path="C:/media/study",
        study_key="study-key",
        display_label="Chest follow-up",
        study_date="20260831",
        modalities=("CT",),
        series_count=2,
        last_opened_at=1.0,
    )


def test_start_center_exposes_actions_busy_state_and_samples(qapp):
    center = StartCenter()
    folder_spy = QSignalSpy(center.open_folder_requested)
    sample_spy = QSignalSpy(center.sample_requested)
    center.show()

    QTest.mouseClick(center.open_folder_button, Qt.MouseButton.LeftButton)
    center.set_samples((StartCenterSample("ct-demo", "CT demo", "Two phases"),))
    sample_button = next(
        button
        for button in center.samples_frame.findChildren(QPushButton)
        if "CT demo" in button.text()
    )
    QTest.mouseClick(sample_button, Qt.MouseButton.LeftButton)
    center.set_busy("Scanning", cancellable=True)

    assert folder_spy.count() == 1
    assert sample_spy.count() == 1
    assert sample_spy.at(0)[0] == "ct-demo"
    assert center.state is StartCenterState.BUSY
    assert center.status_frame.isVisible()
    assert not center.open_folder_button.isEnabled()

    center.set_error("Bad medium")
    assert center.state is StartCenterState.ERROR
    assert center.open_folder_button.isEnabled()
    center.set_idle()
    assert center.state is StartCenterState.IDLE
    center.close()


def test_start_center_routes_available_and_missing_recent_entries(qapp):
    center = StartCenter()
    open_spy = QSignalSpy(center.recent_requested)
    relocate_spy = QSignalSpy(center.recent_relocate_requested)
    entry = _recent()
    center.set_recent_entries(
        (entry,), {entry.entry_id: RecentAvailability.AVAILABLE}
    )
    item = center.recent_list.item(0)

    center._activate_recent_item(item)
    center.update_recent_availability(entry.entry_id, RecentAvailability.MISSING)
    item = center.recent_list.item(0)
    center._activate_recent_item(item)

    assert open_spy.count() == 1
    assert open_spy.at(0)[0] == entry.entry_id
    assert relocate_spy.count() == 1
    assert relocate_spy.at(0)[0] == entry.entry_id
    center.close()


def test_start_center_privacy_hides_recent_description_and_path(qapp):
    center = StartCenter()
    entry = _recent()
    center.set_recent_entries((entry,), {entry.entry_id: True})
    center.set_privacy_mode(True)

    item = center.recent_list.item(0)
    assert "Chest follow-up" not in item.text()
    assert "Study 01" in item.text()
    assert item.toolTip() == ""
    center.close()


def test_media_browser_defaults_to_first_study_and_emits_typed_selection(qapp):
    result = _index_result()
    browser = MediaBrowserPage()
    spy = QSignalSpy(browser.selection_confirmed)
    browser.set_index(result)
    browser.show()
    qapp.processEvents()

    selection = browser.selected_selection()
    assert selection.study_keys == (result.studies[0].study_key,)
    assert len(result.select(selection)) == 2
    assert browser.open_button.isEnabled()

    QTest.mouseClick(browser.open_button, Qt.MouseButton.LeftButton)

    assert spy.count() == 1
    emitted = spy.at(0)[0]
    assert emitted == selection
    browser.close()


def test_media_browser_partial_selection_emits_only_checked_series(qapp):
    result = _index_result()
    browser = MediaBrowserPage()
    browser.set_index(result)
    patient_item = browser.tree.topLevelItem(0)
    study_item = patient_item.child(0)
    study_item.child(1).setCheckState(0, Qt.CheckState.Unchecked)
    qapp.processEvents()

    selection = browser.selected_selection()

    assert selection.study_keys == ()
    assert selection.series_uids == ("1.2.3.1",)
    assert len(result.select(selection)) == 1
    browser.set_busy("Loading")
    assert not browser.open_button.isEnabled()
    browser.set_idle()
    assert browser.open_button.isEnabled()
    browser.close()


def test_media_browser_keeps_non_image_series_visible_but_disabled(qapp):
    result = _index_result()
    study = result.studies[0]
    unsupported = LocalSeriesSource(
        patient_name="Fixture Patient",
        patient_id="P1",
        study_description="Fixture study",
        series_description="Dose report",
        modality="SR",
        study_instance_uid="1.2.3",
        series_instance_uid="1.2.3.99",
        file_paths=("report.dcm",),
        is_viewable=False,
        unsupported_reason="Structured report is not viewable.",
    )
    result = LocalIndexResult(
        request=result.request,
        studies=build_study_candidates((*study.series, unsupported)),
        candidate_count=3,
        media_root=result.media_root,
    )
    browser = MediaBrowserPage()
    browser.set_index(result)

    study_item = browser.tree.topLevelItem(0).child(0)
    report_item = study_item.child(2)
    assert report_item.text(0) == "Dose report"
    assert not bool(report_item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert report_item.text(3)
    assert len(result.select(browser.selected_selection())) == 2
    browser.close()


def test_media_browser_privacy_uses_session_aliases(qapp):
    browser = MediaBrowserPage()
    browser.set_privacy_mode(True)
    browser.set_index(_index_result())

    patient = browser.tree.topLevelItem(0)
    study = patient.child(0)
    series = study.child(0)
    assert patient.text(0) == "Patient 01"
    assert study.text(0) == "Study 01"
    assert series.text(0) == "Series 01"
    assert "Fixture" not in " ".join((patient.text(0), study.text(0), series.text(0)))
    browser.close()
