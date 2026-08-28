from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import ViewPosition
from medimager.core.roi import RectangleROI
from medimager.core.view_presentation_state import (
    ViewPresentationState,
    render_display_slice,
)
from medimager.ui import image_viewer as image_viewer_module
from medimager.ui import multi_viewer_grid as grid_module
from medimager.ui.image_viewer import ImageViewer
from medimager.ui.main_window import MainWindow
from medimager.ui.multi_viewer_grid import MultiViewerGrid, ViewFrame
from medimager.ui.tools.default_tool import DefaultTool, DragMode
from medimager.utils.theme_manager import MEDICAL_CANVAS_COLOR


class _PresentationProbe:
    def __init__(self) -> None:
        self.current_slice_index = 3
        self.window_width = 400.0
        self.window_level = 40.0
        self._use_dicom_voi_lut = False
        self._voi_lut_index = 0

    def get_slice_count(self) -> int:
        return 4

    def get_display_slice(self, index: int):
        return (
            index,
            self.window_width,
            self.window_level,
            self._use_dicom_voi_lut,
            self._voi_lut_index,
        )


def _axis_lengths(viewer: ImageViewer) -> tuple[float, float]:
    transform = viewer.transform()
    origin = transform.map(QPointF())
    x_point = transform.map(QPointF(1.0, 0.0))
    y_point = transform.map(QPointF(0.0, 1.0))
    return (
        abs(x_point.x() - origin.x()) + abs(x_point.y() - origin.y()),
        abs(y_point.x() - origin.x()) + abs(y_point.y() - origin.y()),
    )


def test_render_context_preserves_fractional_window_values():
    model = _PresentationProbe()
    state = ViewPresentationState(
        slice_index=1,
        window_width=80.5,
        window_level=20.25,
    )

    assert render_display_slice(model, state) == (1, 80.5, 20.25, False, 0)
    assert (model.current_slice_index, model.window_width, model.window_level) == (
        3,
        400.0,
        40.0,
    )


def test_actual_size_is_true_pixel_one_to_one_with_anisotropic_spacing(qapp):
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((8, 12), dtype=np.float32),
        {"PixelSpacing": [2.0, 1.0]},
    )
    viewer = ImageViewer()
    viewer.resize(320, 240)
    viewer.set_model(model)
    image = QImage(12, 8, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)

    viewer.actual_size()

    x_length, y_length = _axis_lengths(viewer)
    assert x_length == pytest.approx(1.0)
    assert y_length == pytest.approx(1.0)
    assert not viewer.presentation_state.use_physical_pixel_aspect
    viewer.fit_to_window()
    assert viewer.presentation_state.use_physical_pixel_aspect
    viewer.deleteLater()


def test_drag_zoom_clamps_the_real_transform(qapp):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((8, 8), dtype=np.float32))
    viewer = ImageViewer()
    viewer.resize(300, 240)
    viewer.set_model(model)
    image = QImage(8, 8, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    tool = DefaultTool(viewer)
    viewer.set_tool(tool)
    tool._drag_mode = DragMode.ZOOM
    tool._last_mouse_pos = QPoint(10, 10)
    viewer.last_mouse_scene_pos = viewer.mapToScene(tool._last_mouse_pos)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(10, 10010),
        QPointF(10, 10010),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    tool.mouse_move_event(event)

    assert viewer.get_view_zoom() == ViewPresentationState.MAX_ZOOM
    x_length, y_length = _axis_lengths(viewer)
    assert x_length <= ViewPresentationState.MAX_ZOOM
    assert y_length <= ViewPresentationState.MAX_ZOOM
    viewer.deleteLater()


def test_custom_orientation_markers_follow_rotation(qapp):
    viewer = ImageViewer()
    viewer.set_orientation_markers(
        {"top": "A", "right": "B", "bottom": "C", "left": "D"}
    )
    assert viewer._orientation_markers({}) == {
        "top": "A",
        "right": "B",
        "bottom": "C",
        "left": "D",
    }

    viewer.rotate_right()

    assert viewer._orientation_markers({}) == {
        "right": "A",
        "bottom": "B",
        "left": "C",
        "top": "D",
    }
    viewer.deleteLater()


def test_light_theme_keeps_neutral_medical_canvas(qapp):
    viewer = ImageViewer()
    viewer.update_theme("light")

    assert MEDICAL_CANVAS_COLOR.lower() in viewer.styleSheet().lower()
    viewer.deleteLater()


def test_roi_statistics_cache_invalidates_on_geometry_and_pixels(qapp, monkeypatch):
    model = ImageDataModel()
    assert model.load_single_image(np.arange(64, dtype=np.float32).reshape(8, 8))
    roi = RectangleROI(top_left=(1, 1), bottom_right=(5, 5), slice_index=0)
    model.add_roi(roi)
    viewer = ImageViewer()
    viewer.set_model(model)
    calls = []

    def fake_statistics(current_model, current_roi):
        calls.append((current_model, current_roi.top_left, current_roi.bottom_right))
        return {"mean": float(len(calls))}

    monkeypatch.setattr(image_viewer_module, "calculate_roi_statistics", fake_statistics)

    assert viewer._statistics_for_roi(roi)["mean"] == 1.0
    assert viewer._statistics_for_roi(roi)["mean"] == 1.0
    roi.move(1, 0)
    assert viewer._statistics_for_roi(roi)["mean"] == 2.0
    model._data_revision += 1
    assert viewer._statistics_for_roi(roi)["mean"] == 3.0
    viewer.deleteLater()


def test_annotation_repaint_reuses_cached_pixel_layer(qapp, monkeypatch):
    model = ImageDataModel()
    assert model.load_single_image(np.arange(64, dtype=np.float32).reshape(8, 8))
    calls = []
    original_render = grid_module.render_display_slice

    def counting_render(current_model, state):
        calls.append((state.slice_index, state.window_width, state.window_level))
        return original_render(current_model, state)

    monkeypatch.setattr(grid_module, "render_display_slice", counting_render)
    frame = ViewFrame("view_0_0", ViewPosition.TOP_LEFT)
    frame.bind_series("series-1", model, "Series 1")
    qapp.processEvents()
    initial_count = len(calls)

    frame._update_image_display()
    model.data_changed.emit()
    qapp.processEvents()

    assert len(calls) == initial_count
    frame.image_viewer.set_view_window(25.5, 10.25)
    qapp.processEvents()
    assert len(calls) == initial_count + 1
    frame.unbind_series()
    frame.deleteLater()


def test_restore_geometry_preserves_manual_pan_zoom(qapp):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((20, 20), dtype=np.float32))
    viewer = ImageViewer()
    viewer.resize(320, 240)
    viewer.set_model(model)
    image = QImage(20, 20, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    viewer.set_view_zoom(3.0)
    viewer.centerOn(QPointF(7.0, 9.0))
    viewer.presentation_state.pan_center = QPointF(7.0, 9.0)

    MultiViewerGrid._restore_view_geometry(viewer)

    assert viewer.get_view_zoom() == pytest.approx(3.0)
    assert not viewer.presentation_state.fit_mode
    assert viewer.presentation_state.pan_center == QPointF(7.0, 9.0)
    viewer.deleteLater()


def test_toolbar_voi_selection_changes_only_the_active_viewer():
    option = {"kind": "lut", "index": 1, "label": "Soft tissue"}

    class Model:
        current_slice_index = 0
        _use_dicom_voi_lut = False
        _voi_lut_index = 0

        def get_dicom_voi_options(self, slice_index):
            assert slice_index == 2
            return [option]

    class Viewer:
        def __init__(self) -> None:
            self.calls = []

        def set_view_voi_lut(self, enabled, index):
            self.calls.append((enabled, index))

    model = Model()
    viewer = Viewer()
    refreshed = []
    host = SimpleNamespace(
        _get_active_image_model=lambda: model,
        _active_viewer=lambda: viewer,
        _active_view_slice_index=lambda: 2,
        _refresh_toolbar_dicom_voi_options=lambda: refreshed.append(True),
    )

    MainWindow._on_toolbar_voi_option_requested(host, option)

    assert viewer.calls == [(True, 1)]
    assert not model._use_dicom_voi_lut
    assert model._voi_lut_index == 0
    assert refreshed == [True]
