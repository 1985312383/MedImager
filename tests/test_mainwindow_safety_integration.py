from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, QPointF, QThread, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from medimager.core.annotation_persistence import save_annotations
from medimager.core.image_data_model import ImageDataModel, MeasurementData
from medimager.core.local_source import LocalSourceKind, index_local_source
from medimager.core.multi_series_manager import SeriesInfo
from medimager.core.roi import RectangleROI
from medimager.core.series_view_binding import BindingStrategy
from medimager.core.sync_manager import SyncMode
from medimager.ui import main_window as main_window_module
from medimager.ui.main_toolbar import SyncDropdownWidget
from medimager.ui.main_window import (
    MainWindow,
    _SeriesLoadResult,
    _load_series_task,
    _load_single_image_task,
    _scan_dicom_folder_task,
)
from medimager.ui.tools.default_tool import DefaultTool, DragMode
from medimager.ui.tools.measurement_tool import MeasurementTool
from medimager.utils.i18n import t
from tests.dicom_fixtures import make_dicom_dataset, write_dicom


def _make_model() -> ImageDataModel:
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((2, 8, 8), dtype=np.float32),
        {
            "PatientID": "SAFETY-PATIENT",
            "StudyInstanceUID": "1.2.840.10008.1",
            "SeriesInstanceUID": "1.2.840.10008.1.1",
            "SeriesDescription": "Main-window safety test",
        },
    )
    return model


def _add_loaded_series(window: MainWindow, series_id: str, model: ImageDataModel) -> None:
    window.series_manager.add_series(
        SeriesInfo(
            series_id=series_id,
            patient_id="SAFETY-PATIENT",
            series_description=series_id,
            slice_count=model.get_slice_count(),
            study_instance_uid="1.2.840.10008.1",
            series_instance_uid="1.2.840.10008.1.1",
        )
    )
    assert window.series_manager.load_series_data(series_id, model)
    assert window.series_manager.bind_series_to_view("view_0_0", series_id)


def _dispose_window(window: MainWindow, qapp) -> None:
    # Avoid close-event prompts in tests that intentionally leave dirty annotations.
    window._closing = True
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def test_load_series_task_moves_qobject_back_to_gui_thread(qapp, monkeypatch):
    class WorkerModel(QObject):
        def __init__(self):
            super().__init__()
            self.loaded_on_gui_thread = None

        def load_dicom_series(self, _file_paths):
            self.loaded_on_gui_thread = QThread.currentThread() == qapp.thread()
            return True

    monkeypatch.setattr(main_window_module, "ImageDataModel", WorkerModel)

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(_load_series_task, ["synthetic.dcm"], "series-1").result()

    assert result.success
    assert result.image_model is not None
    assert result.image_model.loaded_on_gui_thread is False
    assert result.image_model.thread() == qapp.thread()


def test_single_file_entry_submits_worker_without_loading_inline(
    qapp, monkeypatch, tmp_path
):
    image_path = tmp_path / "deferred.npy"
    np.save(image_path, np.zeros((4, 4), dtype=np.float32))
    window = MainWindow()

    def worker_callable(*_args, **_kwargs):
        raise AssertionError("worker callable must not run on the UI call stack")

    class DeferredDecodeFuture:
        def __init__(self):
            self.callback = None

        def add_done_callback(self, callback):
            self.callback = callback

    class RecordingPool:
        def __init__(self):
            self.submissions = []
            self.future = DeferredDecodeFuture()

        def submit(self, function, *args):
            self.submissions.append((function, args))
            return self.future

    pool = RecordingPool()
    performance_manager = SimpleNamespace(get_thread_pool=lambda: pool)
    monkeypatch.setattr(main_window_module, "_load_single_image_task", worker_callable)
    monkeypatch.setattr(
        main_window_module,
        "get_performance_manager",
        lambda: performance_manager,
    )

    class DeferredIndexFuture:
        def __init__(self):
            self.callback = None
            self.request = None

        def add_done_callback(self, callback):
            self.callback = callback

        def result(self):
            return index_local_source(self.request)

    index_future = DeferredIndexFuture()

    def submit_index(request, **_kwargs):
        index_future.request = request
        return index_future

    monkeypatch.setattr(window.local_study_controller, "submit", submit_index)

    window._load_single_image_file(str(image_path))

    assert index_future.request.kind is LocalSourceKind.IMAGE
    assert window.series_manager.get_series_count() == 0
    assert index_future.callback is not None
    window._on_local_index_finished(index_future.request.request_id, index_future)

    assert len(pool.submissions) == 1
    submitted_function, submitted_args = pool.submissions[0]
    assert submitted_function is worker_callable
    assert submitted_args[0] == str(image_path)
    submitted_series_id = submitted_args[1]
    assert isinstance(submitted_args[2], bool)
    assert window.series_manager.get_series_info(submitted_series_id) is not None
    assert window.series_manager.get_series_model(submitted_series_id) is None
    assert window._loading_futures[submitted_series_id] is pool.future
    assert pool.future.callback is not None

    window._loading_futures.clear()
    _dispose_window(window, qapp)


def test_multiframe_dicom_result_backfills_series_metadata(qapp, tmp_path):
    pixels = np.arange(48, dtype=np.int16).reshape(3, 4, 4)
    dataset = make_dicom_dataset(pixels, modality="MR")
    dataset.PatientName = "Backfill^Patient"
    dataset.PatientID = "BACKFILL-PATIENT"
    dataset.StudyInstanceUID = "1.2.826.0.1.3680043.10.900.1"
    dataset.SeriesInstanceUID = "1.2.826.0.1.3680043.10.900.1.1"
    dataset.SeriesDescription = "Three-frame MR"
    dicom_path = write_dicom(tmp_path / "multiframe.dcm", dataset)

    result = _load_single_image_task(str(dicom_path), "dicom-series")

    assert result.success
    assert result.image_model is not None
    assert result.metadata["slice_count"] == 3
    assert result.metadata["patient_id"] == "BACKFILL-PATIENT"
    assert result.metadata["study_instance_uid"] == dataset.StudyInstanceUID
    assert result.metadata["series_instance_uid"] == dataset.SeriesInstanceUID
    assert result.metadata["modality"] == "MR"

    class CompletedFuture:
        def result(self):
            return result

    window = MainWindow()
    window.series_manager.add_series(
        SeriesInfo(
            series_id="dicom-series",
            patient_name="placeholder",
            patient_id="",
            series_description=dicom_path.name,
            modality="IMG",
            slice_count=0,
            study_instance_uid="",
            series_instance_uid="",
            file_paths=[str(dicom_path)],
        )
    )
    future = CompletedFuture()
    window._loading_futures["dicom-series"] = future

    window._on_series_loading_finished("dicom-series", future)

    info = window.series_manager.get_series_info("dicom-series")
    assert info is not None
    assert info.is_loaded
    assert info.patient_name == "Backfill^Patient"
    assert info.patient_id == "BACKFILL-PATIENT"
    assert info.study_instance_uid == dataset.StudyInstanceUID
    assert info.series_instance_uid == dataset.SeriesInstanceUID
    assert info.series_description == "Three-frame MR"
    assert info.modality == "MR"
    assert info.slice_count == 3
    assert window.series_manager.get_series_model("dicom-series") is result.image_model

    _dispose_window(window, qapp)


def test_folder_scan_accepts_ima_dicom_files(tmp_path):
    dataset = make_dicom_dataset(np.arange(16, dtype=np.int16).reshape(4, 4))
    dataset.SeriesDescription = "IMA series"
    ima_path = write_dicom(tmp_path / "slice001.IMA", dataset)

    result = _scan_dicom_folder_task(
        str(tmp_path),
        recursive=False,
        include_extensionless=False,
        strict_metadata=False,
    )

    assert result.error == ""
    assert result.candidate_count == 1
    assert result.skipped_count == 0
    assert len(result.series) == 1
    assert result.series[0]["series_description"] == "IMA series"
    assert result.series[0]["file_paths"] == [str(ima_path)]


def test_strict_metadata_check_returns_a_boolean_for_every_mode():
    complete = SimpleNamespace(
        SeriesInstanceUID="1.2.3",
        StudyInstanceUID="1.2",
        Modality="CT",
        Rows=512,
        Columns=512,
        PhotometricInterpretation="MONOCHROME2",
    )
    incomplete = SimpleNamespace(**vars(complete))
    incomplete.SeriesInstanceUID = ""

    enabled = SimpleNamespace(_bool_setting=lambda *_args: True)
    disabled = SimpleNamespace(_bool_setting=lambda *_args: False)

    complete_result = MainWindow._warn_if_strict_metadata_incomplete(
        enabled, complete, "complete.dcm"
    )
    incomplete_result = MainWindow._warn_if_strict_metadata_incomplete(
        enabled, incomplete, "incomplete.dcm"
    )
    disabled_result = MainWindow._warn_if_strict_metadata_incomplete(
        disabled, incomplete, "incomplete.dcm"
    )

    assert complete_result is True
    assert incomplete_result is False
    assert disabled_result is True
    assert all(
        isinstance(value, bool)
        for value in (complete_result, incomplete_result, disabled_result)
    )


def test_failed_series_are_rolled_back_and_errors_are_summarized_once(
    qapp, monkeypatch
):
    window = MainWindow()
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, text, *_args, **_kwargs: messages.append((title, text))
        or QMessageBox.StandardButton.Ok,
    )

    class CompletedFuture:
        def __init__(self, result):
            self._result = result

        def result(self):
            return self._result

    futures = {}
    for series_id, error in (
        ("failed-one", "missing JPEG decoder"),
        ("failed-two", "corrupt pixel stream"),
    ):
        window.series_manager.add_series(
            SeriesInfo(series_id=series_id, series_description=series_id)
        )
        result = _SeriesLoadResult(series_id)
        result.error = error
        futures[series_id] = CompletedFuture(result)

    window._loading_futures.update(futures)
    window.loading_progress.setRange(0, 0)
    window.loading_progress.setVisible(True)

    window._on_series_loading_finished("failed-one", futures["failed-one"])

    assert window.series_manager.get_series_info("failed-one") is None
    assert window.series_manager.get_series_info("failed-two") is not None
    # isVisible() also depends on the (intentionally hidden) test window;
    # isHidden() reflects the progress widget's own explicit visibility state.
    assert not window.loading_progress.isHidden()
    assert messages == []

    window._on_series_loading_finished("failed-two", futures["failed-two"])

    assert window.series_manager.get_series_info("failed-two") is None
    assert not window._loading_futures
    assert window.loading_progress.isHidden()
    assert window.loading_progress.maximum() == 1
    assert window.loading_progress.value() == 1
    assert len(messages) == 1
    assert "failed-one: missing JPEG decoder" in messages[0][1]
    assert "failed-two: corrupt pixel stream" in messages[0][1]
    assert window._loading_errors == []

    _dispose_window(window, qapp)


def test_annotation_history_register_change_undo_redo_and_saved_baseline(qapp):
    window = MainWindow()
    model = _make_model()
    _add_loaded_series(window, "history-series", model)
    qapp.processEvents()

    history = window._annotation_histories["history-series"]
    assert history["undo"] == []
    assert history["redo"] == []
    assert not model.has_unsaved_annotations()

    first = RectangleROI((1, 1), (3, 3), 0)
    first.id = "roi-first"
    model.add_roi(first)

    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert len(history["undo"]) == 1
    assert history["redo"] == []
    assert model.has_unsaved_annotations()
    assert window.undo_annotation_action.isEnabled()

    window._undo_annotation_change()
    assert model.rois == []
    assert not model.has_unsaved_annotations()
    assert window.redo_annotation_action.isEnabled()

    window._redo_annotation_change()
    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert model.has_unsaved_annotations()

    model.mark_annotations_saved()
    window._mark_annotation_history_saved(model)
    saved_snapshot = history["saved"]
    assert saved_snapshot == history["current"]
    assert not model.has_unsaved_annotations()

    second = RectangleROI((4, 4), (6, 6), 0)
    second.id = "roi-second"
    model.add_roi(second)
    assert [roi.id for roi in model.rois] == ["roi-first", "roi-second"]
    assert model.has_unsaved_annotations()

    window._undo_annotation_change()
    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert history["current"] == saved_snapshot
    assert not model.has_unsaved_annotations()

    window._redo_annotation_change()
    assert [roi.id for roi in model.rois] == ["roi-first", "roi-second"]
    assert model.has_unsaved_annotations()

    _dispose_window(window, qapp)


def test_open_actions_have_distinct_standard_shortcuts(qapp):
    window = MainWindow()
    portable = QKeySequence.SequenceFormat.PortableText
    shortcuts = [
        action.shortcut().toString(portable)
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]

    assert shortcuts.count("Ctrl+O") == 1
    assert shortcuts.count("Ctrl+D") == 1
    assert shortcuts.count("Ctrl+Shift+D") == 1
    assert len({"Ctrl+O", "Ctrl+D", "Ctrl+Shift+D"}) == 3

    _dispose_window(window, qapp)


def test_close_finalizes_all_roi_and_measurement_edits_before_unsaved_check(
    qapp, monkeypatch
):
    window = MainWindow()
    window.binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)
    window._set_layout((1, 2))
    model = _make_model()
    _add_loaded_series(window, "close-series", model)
    assert window.series_manager.bind_series_to_view("view_0_1", "close-series")
    qapp.processEvents()

    roi = RectangleROI((1, 1), (3, 3), 0)
    roi.id = "in-progress-roi"
    model.add_roi(roi)
    measurement = MeasurementData(
        id="in-progress-distance",
        slice_index=0,
        start_point=QPointF(1, 1),
        end_point=QPointF(4, 1),
        distance=3.0,
        unit="px",
    )
    model.add_measurement(measurement)

    roi_frame = window.multi_viewer_grid.get_view_frame("view_0_0")
    distance_frame = window.multi_viewer_grid.get_view_frame("view_0_1")
    assert roi_frame is not None and distance_frame is not None
    roi_tool = DefaultTool(roi_frame.image_viewer)
    distance_tool = MeasurementTool(distance_frame.image_viewer)
    roi_frame.image_viewer.set_tool(roi_tool)
    distance_frame.image_viewer.set_tool(distance_tool)

    # Model the state after mouseMove changed persistent geometry but before
    # mouseRelease had a chance to mark the edit dirty.
    roi.move(1, 1)
    measurement.start_point = QPointF(2, 1)
    measurement.distance = 2.0
    model.mark_annotations_saved()
    assert not model.has_unsaved_annotations()
    roi_tool._drag_mode = DragMode.ROI_MOVE
    roi_tool._target_roi_id = roi.id
    roi_tool._roi_interaction_changed = True
    distance_tool.dragging = True
    distance_tool.dragging_anchor = "start"
    distance_tool.measurement_completed = True
    distance_tool.editing_measurement_id = measurement.id
    distance_tool.start_point = QPointF(measurement.start_point)
    distance_tool.end_point = QPointF(measurement.end_point)

    finalized = []
    roi_finalizer = roi_tool.finalize_interaction
    distance_finalizer = distance_tool.finalize_interaction

    def finalize_roi():
        finalized.append("roi")
        roi_finalizer()

    def finalize_distance():
        finalized.append("distance")
        distance_finalizer()

    monkeypatch.setattr(roi_tool, "finalize_interaction", finalize_roi)
    monkeypatch.setattr(distance_tool, "finalize_interaction", finalize_distance)
    confirmations = []

    def confirm_close():
        confirmations.append((list(finalized), model.has_unsaved_annotations()))
        return False

    monkeypatch.setattr(window, "_confirm_close_with_unsaved_annotations", confirm_close)
    event = QCloseEvent()

    window.closeEvent(event)

    assert finalized == ["roi", "distance"]
    assert confirmations == [(["roi", "distance"], True)]
    assert not event.isAccepted()
    _dispose_window(window, qapp)


def test_sync_dropdown_both_state_round_trips(qapp):
    widget = SyncDropdownWidget()

    widget.set_sync_states(
        position_mode="both",
        pan=True,
        zoom=False,
        window_level=True,
    )

    assert widget.get_sync_states() == {
        "position_mode": "both",
        "pan": True,
        "zoom": False,
        "window_level": True,
    }
    widget.deleteLater()
    qapp.processEvents()


def test_mainwindow_combined_sync_modes_update_position_control_to_both(qapp):
    window = MainWindow()

    for mode in (
        SyncMode.FULL,
        SyncMode.SLICE | SyncMode.CROSS_REFERENCE,
    ):
        window.sync_manager.set_sync_mode(mode)
        window._update_sync_button_states()
        assert window._sync_button.get_sync_states()["position_mode"] == "both"

    _dispose_window(window, qapp)


def test_user_switch_from_both_to_auto_clears_cross_reference_bit(qapp):
    window = MainWindow()
    sync_widget = window.findChild(SyncDropdownWidget)
    assert sync_widget is not None
    window.sync_manager.set_sync_mode(SyncMode.NONE)
    window._update_sync_button_states()

    sync_widget._position_both_radio.click()

    combined_mode = window.sync_manager.get_sync_mode()
    assert SyncMode.SLICE in combined_mode
    assert SyncMode.CROSS_REFERENCE in combined_mode

    sync_widget._position_auto_radio.click()

    automatic_mode = window.sync_manager.get_sync_mode()
    assert SyncMode.SLICE in automatic_mode
    assert SyncMode.CROSS_REFERENCE not in automatic_mode
    _dispose_window(window, qapp)


def test_auto_assign_has_no_ctrl_a_and_dicom_search_keeps_select_all(qapp):
    window = MainWindow()
    triggered = []
    window.auto_assign_action.triggered.connect(
        lambda *_args: triggered.append(True)
    )
    window.auto_assign_action.setEnabled(True)

    assert window.auto_assign_action.shortcut().isEmpty()
    assert (
        window.auto_assign_action.shortcut().toString(
            QKeySequence.SequenceFormat.PortableText
        )
        != "Ctrl+A"
    )

    window.show()
    window.dicom_tag_panel.show()
    search_edit = window.dicom_tag_panel.search_edit
    search_edit.setText("select all text")
    search_edit.deselect()
    search_edit.setCursorPosition(4)
    search_edit.setFocus()
    qapp.processEvents()
    assert qapp.focusWidget() is search_edit

    QTest.keyClick(search_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()

    assert search_edit.selectedText() == "select all text"
    assert triggered == []
    _dispose_window(window, qapp)


def test_enabled_annotation_undo_redo_route_to_focused_search_editor(qapp):
    window = MainWindow()
    model = _make_model()
    _add_loaded_series(window, "shortcut-history-series", model)
    for roi_id, start in (("roi-first", 1), ("roi-second", 4)):
        roi = RectangleROI((start, start), (start + 2, start + 2), 0)
        roi.id = roi_id
        model.add_roi(roi)

    window._undo_annotation_change()
    history = window._annotation_histories["shortcut-history-series"]
    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert window.undo_annotation_action.isEnabled()
    assert window.redo_annotation_action.isEnabled()
    history_before = copy.deepcopy(
        {
            "undo": history["undo"],
            "redo": history["redo"],
            "current": history["current"],
        }
    )

    window.show()
    window.dicom_tag_panel.show()
    search_edit = window.dicom_tag_panel.search_edit
    search_edit.setFocus()
    QTest.keyClicks(search_edit, "native text edit")
    qapp.processEvents()
    assert qapp.focusWidget() is search_edit
    edited_text = search_edit.text()

    window.undo_annotation_action.trigger()

    assert search_edit.text() != edited_text
    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert {
        "undo": history["undo"],
        "redo": history["redo"],
        "current": history["current"],
    } == history_before

    window.redo_annotation_action.trigger()

    assert search_edit.text() == edited_text
    assert [roi.id for roi in model.rois] == ["roi-first"]
    assert {
        "undo": history["undo"],
        "redo": history["redo"],
        "current": history["current"],
    } == history_before
    _dispose_window(window, qapp)


def test_close_waiting_for_pending_load_stops_cine_and_dicom_tag_timers(
    qapp, monkeypatch
):
    window = MainWindow()
    monkeypatch.setattr(
        window,
        "_confirm_close_with_unsaved_annotations",
        lambda: True,
    )

    window._cine_timer.start(10_000)
    window.dicom_tag_panel.setVisible(True)
    window._queue_dicom_tag_update(SimpleNamespace())
    dicom_tag_timer = window._dicom_tag_update_timer
    dicom_tag_timer.start(10_000)
    assert window._cine_timer.isActive()
    assert dicom_tag_timer.isActive()

    class PendingFuture:
        def __init__(self):
            self.cancel_calls = 0

        def cancel(self):
            self.cancel_calls += 1
            return False

    future = PendingFuture()
    window._loading_futures["pending-series"] = future
    event = QCloseEvent()

    window.closeEvent(event)

    assert future.cancel_calls == 1
    assert not window._cine_timer.isActive()
    assert not dicom_tag_timer.isActive()
    assert window._close_after_loading is True
    assert window._closing is True
    assert not event.isAccepted()
    window._loading_futures.clear()
    _dispose_window(window, qapp)


@pytest.mark.parametrize(
    ("occupied_suffixes", "expected_suffix"),
    [([""], "_2"), (["", "_2"], "_3")],
)
def test_close_save_preserves_existing_annotation_files_and_increments_name(
    qapp, monkeypatch, tmp_path, occupied_suffixes, expected_suffix
):
    window = MainWindow()
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((2, 8, 8), dtype=np.float32),
        {
            "PatientID": "COLLISION-PATIENT",
            "StudyInstanceUID": "1.2.3",
            "SeriesInstanceUID": "1.2.3.4",
            "SeriesDescription": "Collision",
        },
    )
    _add_loaded_series(window, "collision-series", model)
    roi = RectangleROI((1, 1), (3, 3), 0)
    roi.id = "collision-roi"
    model.add_roi(roi)

    base_name = "Collision_1234"
    original_contents = {}
    for suffix in occupied_suffixes:
        path = tmp_path / f"{base_name}{suffix}.json"
        content = f"pre-existing {suffix or 'base'}"
        path.write_text(content, encoding="utf-8")
        original_contents[path] = content

    monkeypatch.setattr(QMessageBox, "exec", lambda _box: 0)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda box: box.defaultButton(),
    )
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    assert window._confirm_close_with_unsaved_annotations()

    for path, content in original_contents.items():
        assert path.read_text(encoding="utf-8") == content
    created = tmp_path / f"{base_name}{expected_suffix}.json"
    assert created.is_file()
    assert '"collision-roi"' in created.read_text(encoding="utf-8")
    _dispose_window(window, qapp)


def test_replace_import_undo_redo_immediately_rebuilds_stats_in_all_shared_views(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    window.binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)
    window._set_layout((1, 2))
    model = _make_model()
    old_roi = RectangleROI((1, 1), (4, 4), 0)
    old_roi.id = "roi-old"
    model.add_roi(old_roi)
    model.mark_annotations_saved()
    _add_loaded_series(window, "shared-stats-series", model)
    assert window.series_manager.bind_series_to_view(
        "view_0_1", "shared-stats-series"
    )
    window.series_manager.set_active_view("view_0_0")
    window.show()
    qapp.processEvents()

    frames = [
        window.multi_viewer_grid.get_view_frame(view_id)
        for view_id in ("view_0_0", "view_0_1")
    ]
    assert all(frame is not None for frame in frames)
    assert all(frame.image_viewer.model is model for frame in frames)
    assert all(
        set(frame.image_viewer.stats_box_positions) == {"roi-old"}
        for frame in frames
    )

    source = _make_model()
    for roi_id, start, end in (
        ("roi-import-a", (1, 1), (3, 3)),
        ("roi-import-b", (4, 4), (7, 7)),
    ):
        roi = RectangleROI(start, end, 0)
        roi.id = roi_id
        source.add_roi(roi)
    replacement_path = tmp_path / "replacement.json"
    save_annotations(source, replacement_path)
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(replacement_path), ""),
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: 0)

    def destructive_button(box):
        return next(
            button
            for button in box.buttons()
            if box.buttonRole(button) is QMessageBox.ButtonRole.DestructiveRole
            and button.text() == t("mainwindow.replace_existing_annotations")
        )

    monkeypatch.setattr(QMessageBox, "clickedButton", destructive_button)
    data_changes = []
    model.data_changed.connect(
        lambda: data_changes.append(tuple(roi.id for roi in model.rois))
    )

    def assert_all_stats(expected_ids):
        assert {roi.id for roi in model.rois} == expected_ids
        assert all(
            set(frame.image_viewer.stats_box_positions) == expected_ids
            for frame in frames
        )

    window._import_annotations()
    assert_all_stats({"roi-import-a", "roi-import-b"})
    assert data_changes == [("roi-import-a", "roi-import-b")]

    frames[0].image_viewer.setFocus()
    qapp.processEvents()
    window._undo_annotation_change()
    assert_all_stats({"roi-old"})
    assert data_changes == [
        ("roi-import-a", "roi-import-b"),
        ("roi-old",),
    ]

    window._redo_annotation_change()
    assert_all_stats({"roi-import-a", "roi-import-b"})
    assert data_changes == [
        ("roi-import-a", "roi-import-b"),
        ("roi-old",),
        ("roi-import-a", "roi-import-b"),
    ]
    _dispose_window(window, qapp)
