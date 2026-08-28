from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPen
from PySide6.QtWidgets import QMessageBox
from pydicom.dataset import Dataset

from medimager.core.annotation_persistence import (
    AnnotationImportResult,
    AnnotationSeriesMismatchError,
    InvalidAnnotationError,
    export_annotations,
    has_unsaved_annotations,
    import_annotations,
    save_annotations,
)
from medimager.core.image_data_model import (
    AngleMeasurementData,
    ImageDataModel,
    MeasurementData,
)
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.roi import RectangleROI
from medimager.core.series_view_binding import SeriesViewBindingManager
from medimager.ui.image_viewer import ImageViewer
from medimager.ui.multi_viewer_grid import ViewFrame
from medimager.ui.panels.series_panel import SeriesListWidget, SeriesPanel
from medimager.ui.tools.angle_tool import AngleTool
from medimager.ui.tools.default_tool import DefaultTool, DragMode
from medimager.ui.tools.measurement_tool import MeasurementTool
from medimager.utils.i18n import t


def make_model(
    *,
    slices: int = 4,
    patient_id: str = "PATIENT-1",
    study_uid: str = "1.2.3",
    series_uid: str = "1.2.3.4",
) -> ImageDataModel:
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((slices, 8, 8), dtype=np.float32),
        {
            "PatientID": patient_id,
            "StudyInstanceUID": study_uid,
            "SeriesInstanceUID": series_uid,
            "SeriesDescription": "Safety test",
        },
    )
    return model


def add_all_annotation_types(model: ImageDataModel) -> None:
    roi = RectangleROI((1, 1), (4, 4), 0)
    roi.id = "roi-1"
    model.add_roi(roi)
    model.add_measurement(
        MeasurementData(
            id="measurement-1",
            slice_index=min(1, model.get_slice_count() - 1),
            start_point=QPointF(1, 1),
            end_point=QPointF(4, 1),
            distance=3.0,
            unit="px",
        )
    )
    model.add_angle_measurement(
        AngleMeasurementData(
            id="angle-1",
            slice_index=min(2, model.get_slice_count() - 1),
            point1=QPointF(1, 1),
            vertex=QPointF(2, 2),
            point3=QPointF(3, 1),
            angle_degrees=90.0,
        )
    )


def add_loaded_series(
    manager: MultiSeriesManager, series_id: str, model: ImageDataModel
) -> None:
    manager.add_series(
        SeriesInfo(
            series_id=series_id,
            patient_id=str(model.get_metadata("PatientID", "")),
            series_description=series_id,
            slice_count=model.get_slice_count(),
            study_instance_uid=str(model.get_metadata("StudyInstanceUID", "")),
            series_instance_uid=str(model.get_metadata("SeriesInstanceUID", "")),
        )
    )
    assert manager.load_series_data(series_id, model)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("patient_id", "OTHER-PATIENT"),
        ("study_instance_uid", "9.8.7"),
        ("series_instance_uid", "9.8.7.6"),
    ],
)
def test_import_rejects_identity_mismatch_without_mutating_target(field, replacement):
    source = make_model()
    add_all_annotation_types(source)
    document = export_annotations(source)
    document["series"][field] = replacement

    target = make_model()
    existing = RectangleROI((0, 0), (1, 1), 0)
    existing.id = "existing"
    target.add_roi(existing)

    with pytest.raises(AnnotationSeriesMismatchError) as error:
        import_annotations(target, document)

    assert field in error.value.mismatches
    assert [roi.id for roi in target.rois] == ["existing"]
    assert target.measurements == []
    assert target.angle_measurements == []


def test_import_identity_override_is_explicit_and_reported():
    source = make_model(patient_id="SOURCE")
    add_all_annotation_types(source)
    target = make_model(patient_id="TARGET")

    result = import_annotations(
        target,
        export_annotations(source),
        allow_identity_mismatch=True,
    )

    assert isinstance(result, AnnotationImportResult)
    assert result.total == 3
    assert result.mode == "replace"
    assert result.identity_mismatch_overridden is True
    assert result["rois"] == 1
    assert target.has_unsaved_annotations()


def test_import_rejects_out_of_bounds_slice_transactionally():
    source = make_model()
    add_all_annotation_types(source)
    document = export_annotations(source)
    document["annotations"]["rois"][0]["slice_index"] = 99
    target = make_model()
    existing = RectangleROI((0, 0), (1, 1), 0)
    existing.id = "existing"
    target.add_roi(existing)

    with pytest.raises(InvalidAnnotationError, match="outside the source volume"):
        import_annotations(target, document)

    assert [roi.id for roi in target.rois] == ["existing"]


def test_import_rejects_nonempty_document_without_source_slice_bounds():
    source = make_model()
    add_all_annotation_types(source)
    document = export_annotations(source)
    document["series"]["slice_count"] = 0

    with pytest.raises(InvalidAnnotationError, match="source volume bounds"):
        import_annotations(make_model(), document)


def test_merge_rejects_duplicate_ids_without_partial_append():
    source = make_model()
    add_all_annotation_types(source)
    target = make_model()
    existing = RectangleROI((0, 0), (1, 1), 0)
    existing.id = "roi-1"
    target.add_roi(existing)

    with pytest.raises(InvalidAnnotationError, match="duplicate ROI"):
        import_annotations(target, export_annotations(source), replace=False)

    assert [roi.id for roi in target.rois] == ["roi-1"]
    assert target.measurements == []


def test_atomic_save_preserves_existing_file_on_replace_failure(tmp_path, monkeypatch):
    model = make_model()
    add_all_annotation_types(model)
    destination = tmp_path / "annotations.json"
    destination.write_text("original", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("medimager.core.annotation_persistence.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        save_annotations(model, destination)

    assert destination.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".annotations.json.*.tmp")) == []


def test_saved_annotation_signature_tracks_later_edits(tmp_path):
    model = make_model()
    add_all_annotation_types(model)
    assert has_unsaved_annotations(model)

    save_annotations(model, tmp_path / "annotations.json")
    assert not has_unsaved_annotations(model)
    assert not model.has_unsaved_annotations()

    model.measurements[0].distance = 4.0
    assert has_unsaved_annotations(model)


def test_bind_unbind_and_layout_changes_preserve_all_annotations():
    manager = MultiSeriesManager()
    first = make_model()
    second = make_model(series_uid="1.2.3.5")
    add_all_annotation_types(first)
    add_loaded_series(manager, "series-1", first)
    add_loaded_series(manager, "series-2", second)

    assert manager.bind_series_to_view("view_0_0", "series-1")
    assert manager.bind_series_to_view("view_0_0", "series-2")
    assert manager.unbind_series_from_view("view_0_0")
    assert manager.bind_series_to_view("view_0_0", "series-1")
    assert manager.set_layout(2, 2)
    assert manager.set_layout(1, 1)

    assert [roi.id for roi in first.rois] == ["roi-1"]
    assert [item.id for item in first.measurements] == ["measurement-1"]
    assert [item.id for item in first.angle_measurements] == ["angle-1"]


def test_core_removal_requires_explicit_unsaved_annotation_authorization():
    manager = MultiSeriesManager()
    model = make_model()
    add_all_annotation_types(model)
    add_loaded_series(manager, "series-1", model)

    summary = manager.get_series_removal_summary("series-1")
    assert summary.annotation_count == 3
    assert summary.has_unsaved_annotations
    assert not manager.remove_series("series-1")
    assert manager.get_series_info("series-1") is not None
    assert manager.remove_series("series-1", allow_unsaved_annotations=True)


class CountingViewFrame(ViewFrame):
    def __init__(self, *args, **kwargs):
        self.render_count = 0
        self.annotation_repaint_count = 0
        super().__init__(*args, **kwargs)

    def _update_image_display(self):
        self.render_count += 1
        super()._update_image_display()

    def _on_model_data_changed(self):
        self.annotation_repaint_count += 1
        super()._on_model_data_changed()


def test_view_frame_preserves_annotations_and_renders_slice_once(qapp):
    from medimager.core.multi_series_manager import ViewPosition

    model = make_model()
    add_all_annotation_types(model)
    frame = CountingViewFrame("view_0_0", ViewPosition.TOP_LEFT)
    frame.resize(500, 500)
    frame.show()
    frame.bind_series("series-1", model, "Series 1")
    qapp.processEvents()
    frame._image_viewer.stats_box_positions["roi-1"] = QRect(2, 2, 80, 40)

    frame.render_count = 0
    assert frame.image_viewer.set_view_slice(1)
    qapp.processEvents()
    assert frame.render_count == 1
    assert model.current_slice_index == 0
    assert "/4" in frame._slice_label.text()

    frame.unbind_series()
    frame.bind_series("series-1", model, "Series 1")
    qapp.processEvents()
    assert [roi.id for roi in model.rois] == ["roi-1"]
    assert [item.id for item in model.measurements] == ["measurement-1"]
    assert [item.id for item in model.angle_measurements] == ["angle-1"]
    assert frame.image_viewer.set_view_slice(0)
    qapp.processEvents()
    assert "roi-1" in frame._image_viewer.stats_box_positions
    assert not hasattr(model, "_medimager_roi_stats_positions")
    frame.close()
    frame.deleteLater()


def test_view_frame_labels_ct_as_hu_but_not_mr(qapp):
    from medimager.core.multi_series_manager import ViewPosition

    frame = ViewFrame("view_0_0", ViewPosition.TOP_LEFT)
    frame.show()

    ct_model = make_model(slices=1)
    ct_dataset = Dataset()
    ct_dataset.Modality = "CT"
    ct_model.dicom_files = [ct_dataset]
    frame._image_viewer.set_model(ct_model)
    frame._update_pixel_info(2, 3, 42.0)
    ct_text = frame._pixel_value_label.text()

    mr_model = make_model(slices=1)
    mr_dataset = Dataset()
    mr_dataset.Modality = "MR"
    mr_model.dicom_files = [mr_dataset]
    frame._image_viewer.set_model(mr_model)
    frame._update_pixel_info(2, 3, 42.0)
    mr_text = frame._pixel_value_label.text()

    assert "HU" in ct_text
    assert "MR" in mr_text
    assert "HU" not in mr_text
    frame.deleteLater()
    qapp.processEvents()


def test_view_frame_overlay_tracks_empty_loading_and_failure_states(qapp):
    from medimager.core.multi_series_manager import ViewPosition

    frame = ViewFrame("view_0_0", ViewPosition.TOP_LEFT)
    frame.resize(320, 240)
    frame.show()
    qapp.processEvents()

    assert frame._state_overlay.isVisible()
    assert frame._viewer_stack.currentWidget() is frame._state_overlay
    assert frame._state_overlay.text() == t("viewframe.empty_hint")

    frame.show_loading_state("series-1", "Series 1")
    qapp.processEvents()
    assert frame._state_overlay.isVisible()
    assert frame._viewer_stack.currentWidget() is frame._state_overlay
    assert frame._state_overlay.text() == t("viewframe.loading_hint")

    frame.show_error_state("decoder unavailable")
    qapp.processEvents()
    assert frame._state_overlay.isVisible()
    assert frame._viewer_stack.currentWidget() is frame._state_overlay
    assert frame._state_overlay.text().startswith(t("viewframe.load_failed_hint"))
    assert "decoder unavailable" in frame._state_overlay.text()

    frame.unbind_series()
    qapp.processEvents()
    assert frame._state_overlay.isVisible()
    assert frame._viewer_stack.currentWidget() is frame._state_overlay
    assert frame._state_overlay.text() == t("viewframe.empty_hint")
    frame.deleteLater()


def test_shared_model_roi_drag_finalization_refreshes_both_view_frames(qapp):
    from medimager.core.multi_series_manager import ViewPosition

    model = make_model()
    roi = RectangleROI((1, 1), (4, 4), 0)
    roi.id = "shared-roi"
    model.add_roi(roi)
    first = CountingViewFrame("view_0_0", ViewPosition.TOP_LEFT)
    second = CountingViewFrame("view_0_1", ViewPosition.TOP_CENTER)
    first.bind_series("shared-series", model, "Shared")
    second.bind_series("shared-series", model, "Shared")
    tool = DefaultTool(first.image_viewer)
    first.image_viewer.set_tool(tool)
    model.mark_annotations_saved()
    roi.move(1, 1)
    tool._drag_mode = DragMode.ROI_MOVE
    tool._target_roi_id = roi.id
    tool._roi_interaction_changed = True
    data_changes = []
    model.data_changed.connect(lambda: data_changes.append(True))
    first.render_count = 0
    second.render_count = 0
    first.annotation_repaint_count = 0
    second.annotation_repaint_count = 0

    tool.finalize_interaction()
    qapp.processEvents()

    assert data_changes == [True]
    assert first.annotation_repaint_count == 1
    assert second.annotation_repaint_count == 1
    assert first.render_count == 0
    assert second.render_count == 0
    assert model.has_unsaved_annotations()
    first.deleteLater()
    second.deleteLater()


def test_tool_switch_clears_roi_distance_and_angle_selection(qapp):
    model = make_model()
    add_all_annotation_types(model)
    viewer = ImageViewer()
    viewer.set_model(model)
    assert viewer.set_view_slice(4, emit=False)
    model.select_roi("roi-1")
    assert model.select_measurement(0)
    assert model.select_angle_measurement("angle-1", multi=True)
    assert model.selected_indices == {0}
    assert model.selected_measurement_indices == {0}
    assert model.selected_angle_measurement_ids == {"angle-1"}

    viewer.set_tool(MeasurementTool(viewer))

    assert model.selected_indices == set()
    assert model.selected_measurement_indices == set()
    assert model.selected_angle_measurement_ids == set()
    viewer.deleteLater()
    qapp.processEvents()


def test_selected_angle_uses_selected_color_and_larger_outer_anchor_ring(
    qapp, monkeypatch
):
    model = make_model(slices=1)
    model.add_angle_measurement(
        AngleMeasurementData(
            id="selected-angle",
            slice_index=0,
            point1=QPointF(1, 4),
            vertex=QPointF(4, 4),
            point3=QPointF(4, 1),
            angle_degrees=90.0,
        )
    )
    assert model.select_angle_measurement("selected-angle")
    viewer = ImageViewer()
    viewer.set_model(model)
    viewer._measurement_theme_cache = {
        "line_color": "#00FF00",
        "anchor_color": "#00FF00",
        "selected_color": "#FF00FF",
        "text_color": "#FFFFFF",
        "background_color": "#00000080",
        "line_width": 2,
        "anchor_size": 8,
        "font_size": 14,
    }
    monkeypatch.setattr(
        AngleTool,
        "_draw_angle_arc_and_text",
        staticmethod(lambda *_args, **_kwargs: None),
    )

    class PainterSpy:
        def __init__(self):
            self.current_pen = None
            self.line_pens = []
            self.ellipses = []

        def save(self):
            pass

        def restore(self):
            pass

        def setPen(self, pen):
            self.current_pen = QPen(pen) if isinstance(pen, QPen) else pen

        def setBrush(self, _brush):
            pass

        def drawLine(self, *_args):
            self.line_pens.append(QPen(self.current_pen))

        def drawEllipse(self, _point, radius_x, radius_y):
            pen = QPen(self.current_pen) if isinstance(self.current_pen, QPen) else None
            self.ellipses.append((pen, float(radius_x), float(radius_y)))

    painter = PainterSpy()

    viewer._draw_all_angle_measurements(painter)

    assert len(painter.line_pens) == 2
    assert all(pen.color().name().upper() == "#FF00FF" for pen in painter.line_pens)
    selected_rings = [
        ellipse
        for ellipse in painter.ellipses
        if ellipse[0] is not None
        and ellipse[0].color().name().upper() == "#FF00FF"
    ]
    plain_anchors = [ellipse for ellipse in painter.ellipses if ellipse[0] is None]
    assert len(selected_rings) == 3
    assert len(plain_anchors) == 3
    assert min(item[1] for item in selected_rings) > max(
        item[1] for item in plain_anchors
    )
    viewer.deleteLater()
    qapp.processEvents()


def test_roi_stats_box_keeps_device_size_bounds_and_hit_after_view_transforms(qapp):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((100, 100), dtype=np.float32))
    roi = RectangleROI((80, 80), (98, 98), 0)
    roi.id = "bottom-right-roi"
    model.add_roi(roi)
    viewer = ImageViewer()
    viewer.resize(420, 320)
    viewer.show()
    viewer.set_model(model)
    image = QImage(100, 100, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    qapp.processEvents()
    tool = DefaultTool(viewer)
    requested_size = QSize(96, 52)

    def assert_stats_box_contract():
        created = viewer.create_stats_box_viewport_rect(roi, requested_size)
        assert created.size() == requested_size
        viewer.set_stats_box_viewport_rect(roi.id, created)
        first = viewer.get_stats_box_viewport_rect(roi.id)
        assert first.size() == requested_size
        assert viewer.stats_box_positions[roi.id].size() == requested_size
        assert viewer.visible_image_viewport_rect().contains(first)

        # Persisting the public viewport rect again must not convert its device
        # size into scene units or make hit-testing drift from what is drawn.
        viewer.set_stats_box_viewport_rect(roi.id, first)
        round_tripped = viewer.get_stats_box_viewport_rect(roi.id)
        assert round_tripped.size() == requested_size
        assert viewer.visible_image_viewport_rect().contains(round_tripped)
        roi.selected = False
        model.selected_indices.clear()
        tool._drag_mode = DragMode.NONE
        tool._target_roi_id = None
        scene_center = viewer.mapToScene(round_tripped.center())
        assert tool._check_roi_interactions(scene_center, Qt.NoModifier)
        assert tool._drag_mode is DragMode.INFO_BOX_MOVE
        assert tool._target_roi_id == roi.id

    viewer.fit_to_window()
    qapp.processEvents()
    assert_stats_box_contract()

    viewer.zoom_in()
    qapp.processEvents()
    assert_stats_box_contract()

    viewer.rotate_right()
    qapp.processEvents()
    assert viewer._rotation == 90
    assert_stats_box_contract()
    viewer.deleteLater()
    qapp.processEvents()


def _browse_mouse_move(x: int, y: int) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


def _left_mouse_event(event_type: QEvent.Type, position: QPoint) -> QMouseEvent:
    button = (
        Qt.LeftButton
        if event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
        else Qt.NoButton
    )
    buttons = Qt.NoButton if event_type is QEvent.Type.MouseButtonRelease else Qt.LeftButton
    return QMouseEvent(
        event_type,
        QPointF(position),
        QPointF(position),
        button,
        buttons,
        Qt.NoModifier,
    )


def test_default_browse_drag_accumulates_small_moves_and_preserves_remainder(qapp):
    model = make_model(slices=12)
    assert model.set_current_slice(4)
    viewer = ImageViewer()
    viewer.set_model(model)
    tool = DefaultTool(viewer)
    tool._drag_mode = DragMode.BROWSE_IMAGES
    tool._last_mouse_pos = QPoint(10, 10)

    for y in (12, 15, 17):  # +2, +3, +2 = 7 px
        tool.mouse_move_event(_browse_mouse_move(10, y))

    assert viewer.current_slice_index == 5
    assert model.current_slice_index == 4
    assert tool._browse_drag_remainder == 1

    for y in (20, 23):  # retained 1 + 3 + 3 = another 7 px
        tool.mouse_move_event(_browse_mouse_move(10, y))

    assert viewer.current_slice_index == 6
    assert model.current_slice_index == 4
    assert tool._browse_drag_remainder == 1
    viewer.deleteLater()
    qapp.processEvents()


def test_default_browse_drag_opposite_small_moves_cancel_before_threshold(qapp):
    model = make_model(slices=12)
    assert model.set_current_slice(4)
    viewer = ImageViewer()
    viewer.set_model(model)
    assert viewer.set_view_slice(4, emit=False)
    tool = DefaultTool(viewer)
    tool._drag_mode = DragMode.BROWSE_IMAGES
    tool._last_mouse_pos = QPoint(10, 10)

    for y in (13, 15, 13, 10):  # +3 +2 -2 -3 = 0 px
        tool.mouse_move_event(_browse_mouse_move(10, y))

    assert viewer.current_slice_index == 4
    assert model.current_slice_index == 4
    assert tool._browse_drag_remainder == 0
    viewer.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("initial_y", "target_y", "expected_slice"),
    [(10, 610, 11), (610, 10, 0)],
    ids=["large-positive-delta", "large-negative-delta"],
)
def test_default_browse_drag_large_delta_clamps_to_volume_boundary(
    qapp, initial_y, target_y, expected_slice
):
    model = make_model(slices=12)
    assert model.set_current_slice(5)
    viewer = ImageViewer()
    viewer.set_model(model)
    assert viewer.set_view_slice(5, emit=False)
    tool = DefaultTool(viewer)
    tool._drag_mode = DragMode.BROWSE_IMAGES
    tool._last_mouse_pos = QPoint(10, initial_y)

    tool.mouse_move_event(_browse_mouse_move(10, target_y))

    assert viewer.current_slice_index == expected_slice
    assert model.current_slice_index == 5
    assert tool._browse_drag_remainder == 0
    viewer.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("finish_method", ["release", "finalize"])
@pytest.mark.parametrize("moved", [False, True], ids=["no-move", "moved"])
def test_measurement_anchor_drag_only_marks_dirty_after_actual_move(
    qapp, finish_method, moved
):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((100, 100), dtype=np.float32))
    measurement = MeasurementData(
        id="anchor-drag-measurement",
        slice_index=0,
        start_point=QPointF(30, 50),
        end_point=QPointF(70, 50),
        distance=40.0,
        unit="px",
    )
    model.add_measurement(measurement)
    model.mark_annotations_saved()
    annotation_changes = []
    model.annotation_changed.connect(lambda: annotation_changes.append(True))

    viewer = ImageViewer()
    viewer.resize(420, 320)
    viewer.show()
    viewer.set_model(model)
    image = QImage(100, 100, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    qapp.processEvents()
    tool = MeasurementTool(viewer)
    viewer.set_tool(tool)
    anchor_position = viewer.mapFromScene(measurement.start_point)

    tool.mouse_press_event(
        _left_mouse_event(QEvent.Type.MouseButtonPress, anchor_position)
    )

    assert tool.dragging
    assert tool.dragging_anchor == "start"
    assert not model.has_unsaved_annotations()

    finish_position = QPoint(anchor_position)
    if moved:
        finish_position += QPoint(12, 0)
        tool.mouse_move_event(
            _left_mouse_event(QEvent.Type.MouseMove, finish_position)
        )
        assert measurement.start_point != QPointF(30, 50)
        assert not model.has_unsaved_annotations()

    if finish_method == "release":
        tool.mouse_release_event(
            _left_mouse_event(QEvent.Type.MouseButtonRelease, finish_position)
        )
    else:
        tool.finalize_interaction()

    assert model.has_unsaved_annotations() is moved
    assert annotation_changes == ([True] if moved else [])
    viewer.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("drag_mode", "move_positions", "expected_delta"),
    [
        (
            DragMode.ROI_MOVE,
            [(101, 100), (102, 100), (103, 100), (104, 100), (105, 100)],
            QPoint(5, 0),
        ),
        (
            DragMode.INFO_BOX_MOVE,
            [(100, 101), (100, 102), (100, 103), (100, 104), (100, 105)],
            QPoint(0, 5),
        ),
    ],
)
def test_stats_box_drag_accumulates_one_pixel_viewport_moves_at_ten_x_zoom(
    qapp, drag_mode, move_positions, expected_delta
):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((100, 100), dtype=np.float32))
    roi = RectangleROI((40, 40), (60, 60), 0)
    roi.id = "high-zoom-roi"
    model.add_roi(roi)
    viewer = ImageViewer()
    viewer.resize(420, 320)
    viewer.show()
    viewer.set_model(model)
    image = QImage(100, 100, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    viewer.set_synced_view_state(10.0, sync_zoom=True, sync_pan=False)
    qapp.processEvents()
    assert viewer.effective_scale() == pytest.approx(10.0)

    requested = QRect(160, 120, 80, 40)
    viewer.set_stats_box_viewport_rect(roi.id, requested)
    start = viewer.get_stats_box_viewport_rect(roi.id)
    assert viewer.visible_image_viewport_rect().contains(start)

    tool = DefaultTool(viewer)
    tool._drag_mode = drag_mode
    tool._target_roi_id = roi.id
    tool._last_mouse_pos = QPoint(100, 100)

    for step, (x, y) in enumerate(move_positions, start=1):
        tool.mouse_move_event(_browse_mouse_move(x, y))
        expected_step = QPoint(step, 0) if expected_delta.x() else QPoint(0, step)
        current = viewer.get_stats_box_viewport_rect(roi.id)
        assert current.topLeft() == start.topLeft() + expected_step

    assert (
        viewer.get_stats_box_viewport_rect(roi.id).topLeft()
        == start.topLeft() + expected_delta
    )
    viewer.deleteLater()
    qapp.processEvents()


def test_large_series_tree_materializes_only_selected_page(qapp):
    manager = MultiSeriesManager()
    model = make_model(slices=1000)
    add_loaded_series(manager, "large-series", model)
    widget = SeriesListWidget(manager)
    qapp.processEvents()

    series_item = widget._series_items["large-series"]
    assert series_item.childCount() == 10
    selected = widget.find_slice_item("large-series", 543)
    assert selected is not None
    assert selected.data(0, 0x0100) == ("slice", "large-series", 543)
    assert series_item.child(5).childCount() == 100
    assert series_item.child(0).childCount() == 1
    widget.deleteLater()


def test_series_panel_removal_confirmation_protects_and_then_allows(qapp, monkeypatch):
    manager = MultiSeriesManager()
    model = make_model()
    add_all_annotation_types(model)
    add_loaded_series(manager, "series-1", model)
    panel = SeriesPanel(manager, SeriesViewBindingManager(manager))

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    panel._remove_series("series-1")
    assert manager.get_series_info("series-1") is not None

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    panel._remove_series("series-1")
    assert manager.get_series_info("series-1") is None
    panel.deleteLater()
