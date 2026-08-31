from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTreeWidgetItem

from medimager.core.local_source import (
    LocalIndexResult,
    LocalOpenOrigin,
    LocalOpenRequest,
    LocalSeriesSource,
    LocalSourceKind,
    LocalStudyCandidate,
)
from medimager.core.multi_series_manager import SeriesInfo
from medimager.core.sync_manager import SyncMode
from medimager.demo import load_demo_catalog
from medimager.ui import main_window as main_window_module
from medimager.ui.main_window import LocalStudyController, MainWindow


def _dispose(window, qapp):
    window.close()
    qapp.processEvents()


def _series(series_id: str) -> SeriesInfo:
    return SeriesInfo(
        series_id=series_id,
        patient_name="Example",
        series_description=series_id,
        modality="CT",
        series_instance_uid=f"1.2.826.0.1.{series_id.removeprefix('series-')}",
        study_instance_uid="1.2.826.0.1.100",
        file_paths=[f"{series_id}.dcm"],
    )


def _local_study(
    study_key: str,
    study_uid: str,
    series_uid: str,
    file_path: Path,
) -> LocalStudyCandidate:
    source = LocalSeriesSource(
        patient_name="Example",
        series_description=f"Series {series_uid}",
        modality="CT",
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
        slice_count=1,
        file_paths=(str(file_path),),
    )
    return LocalStudyCandidate(
        study_key=study_key,
        study_instance_uid=study_uid,
        patient_name="Example",
        patient_id="EX",
        study_description=f"Study {study_key}",
        study_date="20260101",
        modalities=("CT",),
        series=(source,),
    )


def test_workspace_stack_uses_object_pages_and_empty_start_center(qapp):
    window = MainWindow()

    pages = (
        window.start_center,
        window.media_browser,
        window.multi_viewer_grid,
        window.mpr_workspace,
    )
    assert len({window.workspace_stack.indexOf(page) for page in pages}) == 4
    assert window.workspace_stack.currentWidget() is window.start_center

    series_id = window.series_manager.add_series(_series("series-1"))
    qapp.processEvents()
    assert window.workspace_stack.currentWidget() is window.multi_viewer_grid

    window.series_manager.remove_series(series_id)
    qapp.processEvents()
    assert window.workspace_stack.currentWidget() is window.start_center
    _dispose(window, qapp)


def test_local_study_controller_emits_stable_lifecycle_signals(
    qapp, monkeypatch, tmp_path
):
    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)
    expected = LocalIndexResult(request=request)

    monkeypatch.setattr(
        main_window_module,
        "index_local_source",
        lambda *_args, **_kwargs: expected,
    )
    events = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        controller = LocalStudyController(executor=executor)
        controller.started.connect(
            lambda request_id, _request: events.append(("started", request_id))
        )
        controller.progress.connect(
            lambda request_id, current, total: events.append(
                ("progress", request_id, current, total)
            )
        )
        controller.completed.connect(
            lambda request_id, result: events.append(
                ("completed", request_id, result)
            )
        )
        future = controller.submit(request)
        assert future.result() is expected
        qapp.processEvents()

    assert ("started", request.request_id) in events
    assert ("progress", request.request_id, 0, 0) in events
    assert ("progress", request.request_id, 1, 1) in events
    assert ("completed", request.request_id, expected) in events
    assert controller.pending_request_ids == ()


def test_dicomdir_request_opens_browser_before_decode(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    dicomdir = tmp_path / "DICOMDIR"
    dicomdir.write_bytes(b"index")
    request = LocalOpenRequest.create(LocalSourceKind.DICOMDIR, dicomdir)
    source = LocalSeriesSource(
        patient_name="Example",
        series_description="CT",
        modality="CT",
        study_instance_uid="1.2.3",
        series_instance_uid="1.2.3.4",
        file_paths=(str(tmp_path / "image.dcm"),),
    )
    study = LocalStudyCandidate(
        study_key="study-key",
        study_instance_uid="1.2.3",
        patient_name="Example",
        patient_id="EX",
        study_description="Example study",
        study_date="20260101",
        modalities=("CT",),
        series=(source,),
    )
    result = LocalIndexResult(request=request, studies=(study,), candidate_count=1)

    class DeferredFuture:
        def __init__(self):
            self.callback = None

        def add_done_callback(self, callback):
            self.callback = callback

        def result(self):
            return result

        def cancel(self):
            return False

    deferred = DeferredFuture()
    monkeypatch.setattr(
        window.local_study_controller,
        "submit",
        lambda *_args, **_kwargs: deferred,
    )

    assert window._submit_local_index(request, show_browser=True)
    assert window.workspace_stack.currentWidget() is window.media_browser
    assert deferred.callback is not None

    window._on_local_index_finished(request.request_id, deferred)
    assert window.media_browser.index_result == result
    assert window.workspace_stack.currentWidget() is window.media_browser
    _dispose(window, qapp)


def test_compare_selection_maps_count_to_grid(qapp):
    window = MainWindow()
    series_ids = [
        window.series_manager.add_series(_series(f"series-{index}"))
        for index in range(1, 9)
    ]

    window._on_compare_requested(series_ids[:3])
    assert window.series_manager.get_current_layout() == (1, 3)

    window._on_compare_requested(series_ids[:5])

    assert window.series_manager.get_current_layout() == (2, 3)
    bound = [
        window.series_manager.get_view_binding(view_id).series_id
        for view_id in window.series_manager.get_all_view_ids()[:5]
    ]
    assert bound == series_ids[:5]

    window._on_compare_requested(series_ids[:7])
    assert window.series_manager.get_current_layout() == (2, 4)
    window._on_compare_requested(series_ids)
    assert window.series_manager.get_current_layout() == (2, 4)
    assert window.workspace_stack.currentWidget() is window.multi_viewer_grid
    _dispose(window, qapp)


def test_layout_service_rolls_back_geometry_and_bindings(qapp, monkeypatch):
    window = MainWindow()
    series_id = window.series_manager.add_series(_series("series-1"))
    initial_layout = window.series_manager.get_current_layout()
    initial_view = window.series_manager.get_all_view_ids()[0]
    assert window.series_manager.bind_series_to_view(initial_view, series_id)

    def fail_after_mutation(_spec):
        window._set_layout((2, 2))
        return False

    monkeypatch.setattr(
        window._layout_application_service,
        "_apply_layout",
        fail_after_mutation,
    )

    assert not window._apply_layout_preset_by_id("study_overview")
    assert window.series_manager.get_current_layout() == initial_layout
    binding = window.series_manager.get_view_binding(initial_view)
    assert binding is not None and binding.series_id == series_id
    _dispose(window, qapp)


def test_demo_ready_reenters_folder_index_and_privacy_reaches_navigation(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    spec = load_demo_catalog()[0]
    captured = {}

    def capture(request, **kwargs):
        captured["request"] = request
        captured.update(kwargs)
        return True

    monkeypatch.setattr(window, "_submit_local_index", capture)
    window._active_demo_id = spec.id.value
    window._on_demo_ready(spec.id.value, SimpleNamespace(root=tmp_path))

    request = captured["request"]
    assert request.kind is LocalSourceKind.DEMO
    assert request.origin is LocalOpenOrigin.DEMO
    assert captured["demo_protocol"] is spec.default_hanging_protocol

    window._apply_privacy_mode(True)
    assert window.start_center._privacy_enabled
    assert window.media_browser._privacy_enabled
    assert window.series_panel._series_list._privacy_enabled
    _dispose(window, qapp)


def test_demo_cache_retention_setting_controls_next_load(qapp, monkeypatch):
    window = MainWindow()
    spec = load_demo_catalog()[0]
    calls = []

    class DemoServiceProbe:
        @staticmethod
        def ensure_ready(study_id, *, force=False):
            calls.append((study_id, force))

    window.demo_study_service = DemoServiceProbe()
    monkeypatch.setattr(
        window,
        "_bool_setting",
        lambda key, default: False if key == "cache.demo.keep" else default,
    )

    window._request_demo_study(spec.id.value)

    assert calls == [(spec.id, True)]
    _dispose(window, qapp)


def test_file_menu_exposes_only_the_three_v26_example_studies(
    qapp, monkeypatch
):
    window = MainWindow()
    requested = []
    monkeypatch.setattr(window, "_request_demo_study", requested.append)

    actions = [
        action
        for action in window.example_studies_menu.actions()
        if not action.isSeparator()
    ]
    catalog = load_demo_catalog()

    assert len(actions) == len(catalog) == 3
    assert not hasattr(window, "_load_test_series")
    for action in actions:
        action.trigger()
    assert requested == [spec.id.value for spec in catalog]
    _dispose(window, qapp)


def test_demo_reset_removes_only_indexed_synthetic_studies(qapp, tmp_path):
    window = MainWindow()
    removed = []

    class RecordingStore:
        @staticmethod
        def remove_by_key(study_key):
            removed.append(study_key)
            return SimpleNamespace(success=True, reason="")

    window._workspace_store = RecordingStore()
    demo_request = LocalOpenRequest.create(
        LocalSourceKind.DEMO,
        tmp_path,
        origin=LocalOpenOrigin.DEMO,
    )
    demo_result = LocalIndexResult(
        request=demo_request,
        studies=(
            _local_study(
                "demo-study", "1.2.demo", "1.2.demo.1", tmp_path / "demo.dcm"
            ),
        ),
    )
    normal_request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)
    normal_result = LocalIndexResult(
        request=normal_request,
        studies=(
            _local_study(
                "normal-study",
                "1.2.normal",
                "1.2.normal.1",
                tmp_path / "normal.dcm",
            ),
        ),
    )

    window._clear_demo_workspace_states(normal_result)
    window._clear_demo_workspace_states(demo_result)

    assert removed == ["demo-study"]
    _dispose(window, qapp)


def test_privacy_mode_locks_and_restores_empty_metadata_dock(qapp):
    window = MainWindow()
    window.info_dock.show()
    window.dicom_tag_panel.tree_widget.addTopLevelItem(
        QTreeWidgetItem(["(0010,0010)", "PatientName", "Patient Name", "PN", "PHI"])
    )
    window._pending_dicom_dataset = object()

    window._apply_privacy_mode(True)

    assert window.info_dock.isHidden()
    assert not window.toggle_info_panel_action.isEnabled()
    assert not window.dicom_tag_panel.isEnabled()
    assert not window.dicom_tag_panel.copy_row_action.isEnabled()
    assert (
        window.dicom_tag_panel.tree_widget.contextMenuPolicy()
        is Qt.ContextMenuPolicy.NoContextMenu
    )
    assert window.dicom_tag_panel.tree_widget.topLevelItemCount() == 0
    assert window._pending_dicom_dataset is None

    window._toggle_info_panel(True)
    assert window.info_dock.isHidden()
    assert not window.toggle_info_panel_action.isChecked()

    window._apply_privacy_mode(False)

    assert not window.info_dock.isHidden()
    assert window.toggle_info_panel_action.isEnabled()
    assert window.dicom_tag_panel.isEnabled()
    assert window.dicom_tag_panel.copy_row_action.isEnabled()
    assert window.dicom_tag_panel.tree_widget.topLevelItemCount() == 0
    assert window._pending_dicom_dataset is None
    _dispose(window, qapp)


def test_raw_slice_export_cancel_never_reads_or_opens_destination(
    qapp, monkeypatch
):
    window = MainWindow()

    class ExportModel:
        display_reads = 0

        @staticmethod
        def has_image():
            return True

        def get_display_slice(self):
            self.display_reads += 1
            raise AssertionError("cancelled export must not read source pixels")

    model = ExportModel()
    warning_calls = []
    monkeypatch.setattr(window, "_get_active_image_model", lambda: model)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_calls.append((args, kwargs))
        or QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled export must not open a save dialog")
        ),
    )

    window._export_current_slice_image()

    assert len(warning_calls) == 1
    assert model.display_reads == 0
    _dispose(window, qapp)


def test_runtime_settings_apply_toolbar_sync_and_overlay_preferences(
    qapp, monkeypatch
):
    window = MainWindow()
    original_font = qapp.font()
    overlay_calls = []
    settings = {
        "ui.density": "comfortable",
        "ui.icon_size": 30,
        "ui.font_scale": 120,
        "toolbar.show_labels": True,
        "toolbar.group_order": ["advanced", "compare", "browse", "measure"],
        "toolbar.visible_groups": ["advanced", "compare", "browse"],
        "sync.window_level": False,
        "sync.position_mode": "none",
        "sync.zoom": True,
        "sync.pan": True,
        "sync.reference_lines": False,
        "sync.shared_cursor": True,
        "privacy.screen_mode": False,
    }
    monkeypatch.setattr(
        window.settings_manager,
        "get_setting",
        lambda key, default=None: settings.get(key, default),
    )
    monkeypatch.setattr(
        window.multi_viewer_grid,
        "apply_runtime_settings",
        lambda: overlay_calls.append(True),
    )

    try:
        window._apply_runtime_settings(clear_cache=False)

        assert window.main_toolbar.iconSize().width() == 30
        assert (
            window.main_toolbar.toolButtonStyle()
            is Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        assert window.main_toolbar.property("groupOrder") == (
            "advanced,compare,browse,measure"
        )
        assert window.main_toolbar.property("visibleGroups") == (
            "advanced,browse,compare"
        )
        assert not window.main_toolbar.reference_lines_action.isChecked()
        assert window.main_toolbar.shared_cursor_action.isChecked()
        assert not window.sync_manager._reference_lines_visible
        assert window.sync_manager._shared_cursor_visible
        assert window.sync_manager.get_sync_mode() == (
            SyncMode.ZOOM | SyncMode.PAN | SyncMode.CROSS_REFERENCE
        )
        assert overlay_calls == [True]
        assert qapp.font().pointSizeF() > original_font.pointSizeF()
    finally:
        qapp.setFont(original_font)
        _dispose(window, qapp)


def test_settings_cleanup_protects_current_dirty_recovery_drafts(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    draft = tmp_path / "active-dirty.json"
    dirty_model = SimpleNamespace(has_unsaved_annotations=lambda: True)
    window._annotation_histories["dirty-series"] = {"model": dirty_model}
    monkeypatch.setattr(window, "_draft_path", lambda *_args: draft)
    created = []

    class SignalStub:
        @staticmethod
        def connect(_slot):
            return None

    class StorageStub:
        provider = None

        def set_protected_drafts_provider(self, provider):
            self.provider = provider

    class DialogStub:
        def __init__(self, *_args):
            self.settings_applied = SignalStub()
            self.storage_service = StorageStub()
            created.append(self)

        @staticmethod
        def exec_():
            return 0

    monkeypatch.setattr(main_window_module, "SettingsDialog", DialogStub)

    window._open_settings_dialog()

    assert len(created) == 1
    assert created[0].storage_service.provider() == (draft,)
    _dispose(window, qapp)


def test_multi_study_folder_waits_for_media_selection(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)
    result = LocalIndexResult(
        request=request,
        studies=(
            _local_study("study-a", "1.2.3.1", "1.2.3.1.1", tmp_path / "a.dcm"),
            _local_study("study-b", "1.2.3.2", "1.2.3.2.1", tmp_path / "b.dcm"),
        ),
        candidate_count=2,
    )
    queued = []

    class CompletedFuture:
        @staticmethod
        def result():
            return result

    window._local_index_requests[request.request_id] = request
    monkeypatch.setattr(
        window,
        "_queue_local_selection",
        lambda *args: queued.append(args),
    )

    window._on_local_index_finished(request.request_id, CompletedFuture())

    assert queued == []
    assert window.media_browser.index_result == result
    assert window.workspace_stack.currentWidget() is window.media_browser
    _dispose(window, qapp)


def test_multiple_folder_indexes_merge_once_and_preselect_all(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    requests = (
        LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path / "one"),
        LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path / "two"),
    )
    results = {
        requests[0].request_id: LocalIndexResult(
            request=requests[0],
            studies=(
                _local_study(
                    "study-one",
                    "1.2.840.1",
                    "1.2.840.1.1",
                    tmp_path / "one" / "a.dcm",
                ),
            ),
            candidate_count=1,
        ),
        requests[1].request_id: LocalIndexResult(
            request=requests[1],
            studies=(
                _local_study(
                    "study-two",
                    "1.2.840.2",
                    "1.2.840.2.1",
                    tmp_path / "two" / "b.dcm",
                ),
            ),
            candidate_count=1,
        ),
    }

    class DeferredFuture:
        def __init__(self, result):
            self._result = result
            self.callback = None

        def add_done_callback(self, callback):
            self.callback = callback

        def result(self):
            return self._result

        @staticmethod
        def cancel():
            return False

    futures = {
        request_id: DeferredFuture(result)
        for request_id, result in results.items()
    }
    monkeypatch.setattr(
        window.local_study_controller,
        "submit",
        lambda request, **_kwargs: futures[request.request_id],
    )

    assert window._submit_local_indexes(requests)
    window._on_local_index_finished(requests[0].request_id, futures[requests[0].request_id])
    assert window.media_browser.index_result is None
    window._on_local_index_finished(requests[1].request_id, futures[requests[1].request_id])

    aggregate = window.media_browser.index_result
    assert aggregate is not None
    assert {study.study_key for study in aggregate.studies} == {
        "study-one",
        "study-two",
    }
    assert set(window.media_browser.selected_selection().study_keys) == {
        "study-one",
        "study-two",
    }
    _dispose(window, qapp)


def test_existing_workspace_appends_multi_study_folder_without_page_switch(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    window.series_manager.add_series(_series("series-90"))
    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)
    result = LocalIndexResult(
        request=request,
        studies=(
            _local_study("study-a", "1.2.9.1", "1.2.9.1.1", tmp_path / "a.dcm"),
            _local_study("study-b", "1.2.9.2", "1.2.9.2.1", tmp_path / "b.dcm"),
        ),
        candidate_count=2,
    )
    queued = []

    class CompletedFuture:
        @staticmethod
        def result():
            return result

    monkeypatch.setattr(
        window,
        "_queue_local_selection",
        lambda index, selection: queued.append((index, selection)) or 2,
    )
    window._local_index_requests[request.request_id] = request
    window.workspace_stack.setCurrentWidget(window.multi_viewer_grid)

    window._on_local_index_finished(request.request_id, CompletedFuture())

    assert window.workspace_stack.currentWidget() is window.multi_viewer_grid
    assert len(queued) == 1
    assert set(queued[0][1].study_keys) == {"study-a", "study-b"}
    _dispose(window, qapp)


def test_existing_workspace_aggregates_multiple_folders_in_background(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    window.series_manager.add_series(_series("series-91"))
    window.workspace_stack.setCurrentWidget(window.multi_viewer_grid)
    requests = (
        LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path / "one"),
        LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path / "two"),
    )
    results = (
        LocalIndexResult(
            request=requests[0],
            studies=(
                _local_study(
                    "study-one", "1.2.91.1", "1.2.91.1.1", tmp_path / "a.dcm"
                ),
            ),
        ),
        LocalIndexResult(
            request=requests[1],
            studies=(
                _local_study(
                    "study-two", "1.2.91.2", "1.2.91.2.1", tmp_path / "b.dcm"
                ),
            ),
        ),
    )

    class DeferredFuture:
        def __init__(self, result):
            self._result = result

        @staticmethod
        def add_done_callback(_callback):
            return None

        def result(self):
            return self._result

        @staticmethod
        def cancel():
            return False

    futures = {
        request.request_id: DeferredFuture(result)
        for request, result in zip(requests, results)
    }
    queued = []
    monkeypatch.setattr(
        window.local_study_controller,
        "submit",
        lambda request, **_kwargs: futures[request.request_id],
    )
    monkeypatch.setattr(
        window,
        "_queue_local_selection",
        lambda result, selection: queued.append((result, selection)) or 2,
    )

    assert window._submit_local_indexes(requests)
    assert window.workspace_stack.currentWidget() is window.multi_viewer_grid
    for request in requests:
        window._on_local_index_finished(
            request.request_id, futures[request.request_id]
        )

    assert window.workspace_stack.currentWidget() is window.multi_viewer_grid
    assert len(queued) == 1
    assert set(queued[0][1].study_keys) == {"study-one", "study-two"}
    _dispose(window, qapp)


def test_workspace_startup_mode_controls_restore_and_hanging_policy(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    series_id = window.series_manager.add_series(_series("series-92"))
    values = {
        "workspace.startup_mode": "default_layout",
        "workspace.default_hanging_protocol": "ct_phase",
    }
    original_get = window.settings_manager.get_setting
    monkeypatch.setattr(
        window.settings_manager,
        "get_setting",
        lambda key, default=None: values.get(key, original_get(key, default)),
    )
    restored = []
    monkeypatch.setattr(
        window,
        "_restore_study_workspace_for_series",
        lambda current: restored.append(current) or True,
    )
    window.show()
    qapp.processEvents()

    window._on_series_loaded(series_id)
    assert restored == []
    values["workspace.startup_mode"] = "restore"
    window._on_series_loaded(series_id)
    assert restored == [series_id]
    values["workspace.startup_mode"] = "hanging_protocol"
    assert (
        window._configured_startup_hanging_protocol()
        is main_window_module.HangingProtocolId.CT_COMPARISON
    )

    request = LocalOpenRequest.create(LocalSourceKind.FOLDER, tmp_path)

    class DeferredFuture:
        @staticmethod
        def add_done_callback(_callback):
            return None

        @staticmethod
        def cancel():
            return False

    monkeypatch.setattr(
        window.local_study_controller,
        "submit",
        lambda *_args, **_kwargs: DeferredFuture(),
    )
    assert window._submit_local_index(request)
    assert (
        window._local_request_demo_protocols[request.request_id]
        is main_window_module.HangingProtocolId.CT_COMPARISON
    )
    window._local_index_futures.clear()
    window._local_index_requests.clear()
    window._local_request_demo_protocols.clear()
    window.hide()
    _dispose(window, qapp)
