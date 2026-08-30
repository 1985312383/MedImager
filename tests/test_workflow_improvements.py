from __future__ import annotations

import json
from types import SimpleNamespace
import uuid

import numpy as np
from PySide6.QtTest import QTest

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.series_view_binding import (
    BindingStrategy,
    SeriesViewBindingManager,
)
from medimager.ui.tools.base_tool import viewer_slice_index
from medimager.ui.panels.series_panel import SeriesListWidget
from medimager.ui.main_window import MainWindow
from medimager.core.roi import RectangleROI
from medimager.core.annotation_persistence import has_unsaved_annotations
from medimager.ui import main_window as main_window_module


def _loaded_series(manager: MultiSeriesManager, series_id: str) -> ImageDataModel:
    manager.add_series(
        SeriesInfo(
            series_id=series_id,
            series_description=series_id,
            series_number=series_id,
        )
    )
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((3, 8, 8), dtype=np.float32))
    assert manager.load_series_data(series_id, model)
    return model


def test_ask_user_strategy_uses_injected_pane_choice():
    manager = MultiSeriesManager()
    manager.set_layout(1, 2)
    binding_manager = SeriesViewBindingManager(manager)
    _loaded_series(manager, 'first')
    _loaded_series(manager, 'chosen')
    assert binding_manager.bind_series_to_view('view_0_0', 'first')

    calls = []

    def choose(series_id, candidates, preferred):
        calls.append((series_id, candidates, preferred))
        return 'view_0_0'

    binding_manager.set_target_view_selector(choose)
    binding_manager.set_binding_strategy(BindingStrategy.ASK_USER)
    assert binding_manager.smart_bind_series('chosen')
    assert calls == [('chosen', ['view_0_0', 'view_0_1'], None)]
    assert manager.get_view_binding('view_0_0').series_id == 'chosen'


def test_ask_user_cancellation_emits_visible_reason():
    manager = MultiSeriesManager()
    binding_manager = SeriesViewBindingManager(manager)
    _loaded_series(manager, 'series')
    failures = []
    binding_manager.binding_failed.connect(
        lambda series_id, reason: failures.append((series_id, reason))
    )
    binding_manager.set_target_view_selector(lambda *_: None)
    binding_manager.set_binding_strategy(BindingStrategy.ASK_USER)

    assert not binding_manager.smart_bind_series('series')
    assert failures == [('series', 'selection_cancelled')]


def test_replace_oldest_uses_binding_time_not_view_order():
    manager = MultiSeriesManager()
    manager.set_layout(1, 2)
    binding_manager = SeriesViewBindingManager(manager)
    for series_id in ('left', 'right', 'replacement'):
        _loaded_series(manager, series_id)
    assert binding_manager.bind_series_to_view('view_0_0', 'left')
    assert binding_manager.bind_series_to_view('view_0_1', 'right')
    binding_manager._binding_timestamps.update(
        {'view_0_0': 20.0, 'view_0_1': 10.0}
    )
    binding_manager.set_binding_strategy(BindingStrategy.REPLACE_OLDEST)

    assert binding_manager.smart_bind_series('replacement')
    assert manager.get_view_binding('view_0_0').series_id == 'left'
    assert manager.get_view_binding('view_0_1').series_id == 'replacement'


def test_viewer_slice_accessor_prefers_pane_presentation_state():
    model = SimpleNamespace(current_slice_index=1)
    viewer = SimpleNamespace(
        model=model,
        presentation_state=SimpleNamespace(slice_index=7),
    )
    assert viewer_slice_index(viewer) == 7


def test_series_thumbnail_uses_background_render_cache(qapp, monkeypatch):
    manager = MultiSeriesManager()
    series_id = f"thumbnail-{uuid.uuid4().hex}"
    model = _loaded_series(manager, series_id)
    calls = []

    def forbidden_gui_render(slice_index=None):
        calls.append(slice_index)
        raise AssertionError("GUI-thread get_display_slice must not render thumbnails")

    monkeypatch.setattr(model, 'get_display_slice', forbidden_gui_render)
    widget = SeriesListWidget(manager)
    for _ in range(100):
        qapp.processEvents()
        if series_id in widget._thumbnail_cache:
            break
        QTest.qWait(5)

    assert calls == []
    assert series_id in widget._thumbnail_cache
    assert not widget._series_items[series_id].icon(0).isNull()

    widget._refresh_tree()
    qapp.processEvents()
    assert calls == []
    widget.deleteLater()
    qapp.processEvents()


def test_failed_series_thumbnail_caches_placeholder(qapp, monkeypatch):
    manager = MultiSeriesManager()
    series_id = f"broken-thumbnail-{uuid.uuid4().hex}"
    model = _loaded_series(manager, series_id)
    calls = []
    original = model.get_slice_data

    def fail_once(slice_index):
        calls.append(slice_index)
        raise RuntimeError('snapshot failed')

    monkeypatch.setattr(model, 'get_slice_data', fail_once)
    widget = SeriesListWidget(manager)
    qapp.processEvents()
    widget._refresh_tree()
    qapp.processEvents()

    assert calls == [model.get_slice_count() // 2]
    assert series_id in widget._thumbnail_cache
    assert not widget._series_items[series_id].icon(0).isNull()
    monkeypatch.setattr(model, 'get_slice_data', original)
    widget.deleteLater()
    qapp.processEvents()


def _add_window_series(window, series_id, source_path, uid):
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((3, 8, 8), dtype=np.float32),
        {
            'PatientID': 'WORKFLOW-PATIENT',
            'StudyInstanceUID': '1.2.826.0.1.1',
            'SeriesInstanceUID': uid,
            'SeriesDescription': series_id,
        },
    )
    info = SeriesInfo(
        series_id=series_id,
        series_description=series_id,
        series_instance_uid=uid,
        study_instance_uid='1.2.826.0.1.1',
        slice_count=3,
        file_paths=[str(source_path)],
    )
    window.series_manager.add_series(info)
    assert window.series_manager.load_series_data(series_id, model)
    assert window.series_manager.bind_series_to_view('view_0_0', series_id)
    window.series_manager.set_active_view('view_0_0')
    return model


def _dispose_window(window, qapp):
    window._closing = True
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def test_annotation_draft_recovers_next_session_and_save_clears_it(
    qapp, monkeypatch, tmp_path
):
    source = tmp_path / 'source.dcm'
    source.write_bytes(b'test source identity')
    draft = tmp_path / 'recoverable-draft.json'
    sidecar = tmp_path / 'annotations.json'
    series_id = 'draft-series'
    uid = '1.2.826.0.1.3680043.10.900.7'

    first = MainWindow()
    monkeypatch.setattr(first, '_draft_path', lambda _sid, _model: draft)
    model = _add_window_series(first, series_id, source, uid)
    roi = RectangleROI((1, 1), (5, 5), 0)
    roi.id = 'recover-me'
    model.add_roi(roi)
    first._write_annotation_draft(series_id)

    document = json.loads(draft.read_text(encoding='utf-8'))
    assert document['draft_metadata']['session_id'] == (
        main_window_module._ANNOTATION_DRAFT_SESSION_ID
    )
    assert has_unsaved_annotations(model)

    # Simulate the next application process while retaining pytest's Qt app.
    monkeypatch.setattr(
        main_window_module, '_ANNOTATION_DRAFT_SESSION_ID', 'next-process'
    )
    second = MainWindow()
    monkeypatch.setattr(second, '_draft_path', lambda _sid, _model: draft)
    recovered = _add_window_series(second, series_id, source, uid)

    assert [item.id for item in recovered.rois] == ['recover-me']
    assert has_unsaved_annotations(recovered)
    second._annotation_sidecar_paths[series_id] = sidecar
    assert second._save_model_annotations(series_id, recovered)
    assert sidecar.is_file()
    assert not draft.exists()
    assert not has_unsaved_annotations(recovered)

    _dispose_window(first, qapp)
    _dispose_window(second, qapp)


def test_cine_locks_pane_and_uses_per_frame_interval(qapp, monkeypatch):
    window = MainWindow()
    model = _add_window_series(
        window,
        'cine-series',
        'cine-source.dcm',
        '1.2.826.0.1.3680043.10.900.8',
    )
    intervals = [100.0, 50.0, 25.0]
    monkeypatch.setattr(
        model, 'get_frame_interval_ms', lambda index=None: intervals[index or 0]
    )
    viewer = window.multi_viewer_grid.get_active_view_frame().image_viewer

    window._cine_start()
    assert window._cine_playing
    assert window._cine_source_model is model
    assert window._cine_timer.interval() == 100

    window._cine_advance()
    assert viewer.current_slice_index == 1
    assert model.current_slice_index == 0
    assert window._cine_timer.interval() == 50
    assert window._cine_fps == 20

    window._cine_stop()
    assert not window._cine_timer.isActive()
    assert window._cine_fps == window._cine_configured_fps
    _dispose_window(window, qapp)
