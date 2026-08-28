import numpy as np
import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QWheelEvent,
)

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import (
    MultiSeriesManager,
    SeriesInfo,
    ViewPosition,
)
from medimager.core.series_view_binding import BindingStrategy
from medimager.core.roi import RectangleROI
from medimager.ui.image_viewer import ImageViewer
from medimager.ui.main_window import MainWindow
from medimager.ui.multi_viewer_grid import MultiViewerGrid, ViewFrame
from medimager.ui.tools.default_tool import DefaultTool


def make_model(slice_count: int = 4) -> ImageDataModel:
    model = ImageDataModel()
    data = np.arange(slice_count * 5 * 5, dtype=np.float32).reshape(slice_count, 5, 5)
    assert model.load_single_image(data)
    return model


def add_loaded_series(manager: MultiSeriesManager, series_id: str) -> ImageDataModel:
    model = make_model()
    info = SeriesInfo(
        series_id=series_id,
        patient_name="Synthetic",
        series_description=series_id,
        modality="CT",
        series_number=series_id[-1],
        slice_count=model.get_slice_count(),
    )
    manager.add_series(info)
    assert manager.load_series_data(series_id, model)
    return model


def make_wheel_event(
    angle_delta: QPoint,
    modifiers: Qt.KeyboardModifier = Qt.NoModifier,
    *,
    pixel_delta: QPoint | None = None,
) -> QWheelEvent:
    event = QWheelEvent(
        QPointF(8, 8),
        QPointF(8, 8),
        pixel_delta or QPoint(),
        angle_delta,
        Qt.NoButton,
        modifiers,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    event.ignore()
    return event


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_pixel_wheel_accumulates_to_step_after_activating_inactive_view(
    qapp, modifiers
):
    frame = ViewFrame("view_0_1", ViewPosition.TOP_CENTER)
    model = make_model(slice_count=5)
    assert model.set_current_slice(2)
    frame.bind_series("pixel-wheel-series", model, "Pixel wheel")
    frame.resize(360, 300)
    frame.show()
    qapp.processEvents()
    viewer = frame.image_viewer
    sequence = []

    def activate(view_id):
        sequence.append(("activate", view_id))
        frame.set_active(True)

    frame.view_activated.connect(activate)
    viewer.slice_changed.connect(
        lambda index: sequence.append(("slice", index))
    )
    viewer.zoom_changed.connect(
        lambda zoom: sequence.append(("zoom", zoom))
    )
    initial_zoom = viewer.get_view_zoom()

    first = make_wheel_event(
        QPoint(), modifiers, pixel_delta=QPoint(0, 7)
    )
    second = make_wheel_event(
        QPoint(), modifiers, pixel_delta=QPoint(0, 8)
    )
    viewer.wheelEvent(first)

    assert frame.is_active
    assert sequence == [("activate", "view_0_1")]
    assert viewer.current_slice_index == 2
    assert model.current_slice_index == 2
    assert viewer.get_view_zoom() == pytest.approx(initial_zoom)
    assert first.isAccepted()

    viewer.wheelEvent(second)

    assert sequence[0] == ("activate", "view_0_1")
    if modifiers == Qt.NoModifier:
        assert viewer.current_slice_index == 1
        # Pane presentation is intentionally independent of shared pixels and
        # legacy model navigation state.
        assert model.current_slice_index == 2
        assert [item[0] for item in sequence] == ["activate", "slice"]
        assert viewer.get_view_zoom() == pytest.approx(initial_zoom)
    else:
        assert viewer.current_slice_index == 2
        assert model.current_slice_index == 2
        assert [item[0] for item in sequence] == ["activate", "zoom"]
        assert viewer.get_view_zoom() > initial_zoom
    assert second.isAccepted()
    frame.deleteLater()
    qapp.processEvents()


def test_pure_horizontal_pixel_wheel_remains_ignored_and_does_not_activate(qapp):
    frame = ViewFrame("view_0_1", ViewPosition.TOP_CENTER)
    model = make_model(slice_count=5)
    assert model.set_current_slice(2)
    frame.bind_series("horizontal-pixel-series", model, "Horizontal")
    activations = []
    frame.view_activated.connect(activations.append)
    initial_zoom = frame.image_viewer.get_view_zoom()
    event = make_wheel_event(
        QPoint(), Qt.NoModifier, pixel_delta=QPoint(12, 0)
    )

    frame.image_viewer.wheelEvent(event)

    assert activations == []
    assert not frame.is_active
    assert frame.image_viewer.current_slice_index == 2
    assert model.current_slice_index == 2
    assert frame.image_viewer.get_view_zoom() == pytest.approx(initial_zoom)
    assert not event.isAccepted()
    frame.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("key", "scrollbar_name", "direction"),
    [
        (Qt.Key.Key_Right, "horizontalScrollBar", 1),
        (Qt.Key.Key_PageUp, "verticalScrollBar", -1),
    ],
)
def test_unhandled_default_tool_keys_stay_ignored_and_viewer_falls_back_to_super(
    qapp, key, scrollbar_name, direction
):
    viewer = ImageViewer()
    viewer.resize(200, 160)
    viewer.scene.setSceneRect(0, 0, 2000, 2000)
    viewer.show()
    qapp.processEvents()
    tool = DefaultTool(viewer)
    viewer.set_tool(tool)
    direct_event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier)
    direct_event.accept()

    tool.key_press_event(direct_event)

    assert not direct_event.isAccepted()

    scrollbar = getattr(viewer, scrollbar_name)()
    scrollbar.setValue(scrollbar.maximum() // 2)
    before = scrollbar.value()
    viewer_event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier)
    viewer_event.ignore()

    viewer.keyPressEvent(viewer_event)

    after = scrollbar.value()
    assert (after - before) * direction > 0
    assert viewer_event.isAccepted()
    viewer.deleteLater()
    qapp.processEvents()


def test_default_tool_delete_remains_handled_and_accepted(qapp):
    model = make_model(slice_count=1)
    roi = RectangleROI((1, 1), (3, 3), 0)
    roi.id = "delete-me"
    model.add_roi(roi)
    model.select_roi(roi.id)
    viewer = ImageViewer()
    viewer.set_model(model)
    tool = DefaultTool(viewer)
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.NoModifier)
    event.ignore()

    tool.key_press_event(event)

    assert event.isAccepted()
    assert model.rois == []
    viewer.deleteLater()
    qapp.processEvents()


def test_image_viewer_accepts_series_drop_and_routes_it_through_view_frame(qapp):
    frame = ViewFrame("view_0_1", ViewPosition.TOP_CENTER)
    viewer = frame.image_viewer
    assert viewer.parent() is not frame
    dropped = []
    frame.drop_requested.connect(
        lambda view_id, series_id: dropped.append((view_id, series_id))
    )
    mime_data = QMimeData()
    mime_data.setData("application/x-medimager-series", b"series-from-tree")
    enter_event = QDragEnterEvent(
        QPoint(12, 12),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    viewer.dragEnterEvent(enter_event)

    assert enter_event.isAccepted()
    assert "dashed" in frame.styleSheet()

    drop_event = QDropEvent(
        QPointF(12, 12),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    viewer.dropEvent(drop_event)

    assert drop_event.isAccepted()
    assert "dashed" not in frame.styleSheet()
    assert dropped == [("view_0_1", "series-from-tree")]
    frame.deleteLater()
    qapp.processEvents()


def test_image_viewer_starts_interaction_for_vertical_wheel_and_mouse_only(qapp):
    viewer = ImageViewer()
    interactions = []
    viewer.interaction_started.connect(lambda: interactions.append(True))

    viewer.wheelEvent(make_wheel_event(QPoint(0, 120)))
    assert interactions == [True]

    viewer.wheelEvent(make_wheel_event(QPoint(120, 0)))
    assert interactions == [True]

    mouse_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(4, 4),
        QPointF(4, 4),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    viewer.mousePressEvent(mouse_event)
    assert interactions == [True, True]
    viewer.deleteLater()
    qapp.processEvents()


def test_inactive_view_frame_activates_itself_when_viewer_interaction_starts(qapp):
    frame = ViewFrame("view_0_1", ViewPosition.TOP_CENTER)
    activations = []
    frame.view_activated.connect(activations.append)

    assert not frame.is_active
    frame.image_viewer.interaction_started.emit()
    assert activations == ["view_0_1"]

    frame.set_active(True)
    frame.image_viewer.interaction_started.emit()
    assert activations == ["view_0_1"]
    frame.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_default_tool_ignores_horizontal_wheel_without_slice_or_zoom_change(
    modifiers,
):
    model = make_model()
    assert model.set_current_slice(1)

    class WheelViewer:
        def __init__(self):
            self.model = model
            self.zoom_calls = []
            self.last_mouse_scene_pos = None
            self._view_id = None
            self._sync_manager = None

        def zoom_in(self):
            self.zoom_calls.append("in")

        def zoom_out(self):
            self.zoom_calls.append("out")

    viewer = WheelViewer()
    tool = DefaultTool(viewer)
    event = make_wheel_event(QPoint(120, 0), modifiers)

    tool.wheel_event(event)

    assert model.current_slice_index == 1
    assert viewer.zoom_calls == []
    assert not event.isAccepted()


def _make_default_wheel_tool_for_step_tests():
    model = make_model(slice_count=12)
    assert model.set_current_slice(5)

    class WheelViewer:
        def __init__(self):
            self.model = model
            self.zoom_calls = []
            self.last_mouse_scene_pos = None
            self._view_id = None
            self._sync_manager = None

        def zoom_in(self):
            self.zoom_calls.append("in")

        def zoom_out(self):
            self.zoom_calls.append("out")

    viewer = WheelViewer()
    tool = DefaultTool(viewer)
    tool._bool_setting = lambda *_args, **_kwargs: False
    return model, viewer, tool


@pytest.mark.parametrize("angle_y", [240, -240])
@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_default_tool_standard_angle_240_consumes_two_steps(angle_y, modifiers):
    model, viewer, tool = _make_default_wheel_tool_for_step_tests()
    event = make_wheel_event(QPoint(0, angle_y), modifiers)

    tool.wheel_event(event)

    assert event.isAccepted()
    if modifiers == Qt.NoModifier:
        expected_slice = 3 if angle_y > 0 else 7
        assert model.current_slice_index == expected_slice
        assert viewer.zoom_calls == []
    else:
        assert model.current_slice_index == 5
        expected_zoom = "in" if angle_y > 0 else "out"
        assert viewer.zoom_calls == [expected_zoom, expected_zoom]


@pytest.mark.parametrize("angle_y", [15, -15])
@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_default_tool_small_standard_angles_accumulate_to_one_120_step(
    angle_y, modifiers
):
    model, viewer, tool = _make_default_wheel_tool_for_step_tests()

    for _ in range(7):
        event = make_wheel_event(QPoint(0, angle_y), modifiers)
        tool.wheel_event(event)
        assert event.isAccepted()
        assert model.current_slice_index == 5
        assert viewer.zoom_calls == []

    final_event = make_wheel_event(QPoint(0, angle_y), modifiers)
    tool.wheel_event(final_event)

    assert final_event.isAccepted()
    if modifiers == Qt.NoModifier:
        assert model.current_slice_index == (4 if angle_y > 0 else 6)
        assert viewer.zoom_calls == []
    else:
        assert model.current_slice_index == 5
        assert viewer.zoom_calls == ["in" if angle_y > 0 else "out"]


def test_drop_into_view_activates_target_view(qapp):
    manager = MultiSeriesManager()
    assert manager.set_layout(1, 2)
    grid = MultiViewerGrid(manager)

    assert manager.get_active_view_id() == "view_0_0"

    grid._on_view_frame_drop_requested("view_0_1", "series_2")

    assert manager.get_active_view_id() == "view_0_1"
    grid.deleteLater()
    qapp.processEvents()


def test_active_view_rebind_reconnects_main_window_slice_model(qapp):
    window = MainWindow()
    window.binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)

    model_1 = add_loaded_series(window.series_manager, "series_1")
    model_2 = add_loaded_series(window.series_manager, "series_2")

    assert window.series_manager.bind_series_to_view("view_0_0", "series_1")
    qapp.processEvents()
    assert window._current_active_model is model_1

    assert window.series_manager.bind_series_to_view("view_0_0", "series_2")
    qapp.processEvents()

    assert window._current_active_model is model_2
    model_2.set_current_slice(2)
    qapp.processEvents()
    assert model_2.current_slice_index == 2

    window.close()
    qapp.processEvents()


def test_inactive_view_wheel_activates_before_main_window_broadcasts_slice(
    qapp, monkeypatch
):
    window = MainWindow()
    window.binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)
    window._set_layout((1, 2))
    model_1 = add_loaded_series(window.series_manager, "series_1")
    model_2 = add_loaded_series(window.series_manager, "series_2")
    assert window.series_manager.bind_series_to_view("view_0_0", "series_1")
    assert window.series_manager.bind_series_to_view("view_0_1", "series_2")
    window.series_manager.set_active_view("view_0_0")
    qapp.processEvents()
    assert window._current_active_model is model_1
    broadcasts = []
    monkeypatch.setattr(
        window.sync_manager,
        "sync_slice",
        lambda view_id, slice_index: broadcasts.append((view_id, slice_index)),
    )
    target_frame = window.multi_viewer_grid.get_view_frame("view_0_1")
    assert target_frame is not None
    assert not target_frame.is_active
    assert target_frame.image_viewer.set_view_slice(1, emit=False)

    event = make_wheel_event(QPoint(0, -120))
    target_frame.image_viewer.wheelEvent(event)
    qapp.processEvents()

    assert window.series_manager.get_active_view_id() == "view_0_1"
    assert window._current_active_model is model_2
    assert target_frame.image_viewer.current_slice_index == 2
    assert model_2.current_slice_index == 0
    assert broadcasts == [("view_0_1", 2)]
    assert event.isAccepted()
    window.close()
    qapp.processEvents()
