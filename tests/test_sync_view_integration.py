"""Focused regressions for safe synchronization and view/UI geometry.

These tests intentionally exercise public synchronization entry points where
possible.  Patient-space helpers are covered through slice and cross-reference
signals so a future implementation can change its internals without weakening
the behavioral contract.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QKeySequence, QTransform
from PySide6.QtTest import QTest
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.sync_manager import SyncGroup, SyncManager, SyncMode
from medimager.ui.image_viewer import ImageViewer
from medimager.ui.multi_viewer_grid import MultiViewerGrid
from medimager.ui.panels import dicom_tag_panel as dicom_tag_panel_module
from medimager.ui.panels.dicom_tag_panel import DicomTagPanel
from medimager.utils.i18n import t
from tests.dicom_fixtures import make_dicom_dataset


class _RecordingViewer:
    """Small viewer double that records the independently enabled operations."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.zoom = 1.0
        self.center = QPointF(0, 0)
        self.cross_reference_visible = False
        self.cross_reference_pos = QPointF(-1, -1)
        self.cross_reference_hide_count = 0

    def set_synced_view_state(
        self,
        zoom_factor: float,
        center_scene: QPointF | None = None,
        *,
        sync_zoom: bool = True,
        sync_pan: bool = True,
    ) -> None:
        self.calls.append(
            {
                "zoom_factor": zoom_factor,
                "center_scene": QPointF(center_scene) if center_scene is not None else None,
                "sync_zoom": sync_zoom,
                "sync_pan": sync_pan,
            }
        )
        if sync_zoom:
            self.zoom = zoom_factor
        if sync_pan and center_scene is not None:
            self.center = QPointF(center_scene)

    def hide_cross_reference(self) -> None:
        """Mirror the small part of ImageViewer used while changing modes."""
        self.cross_reference_visible = False
        self.cross_reference_pos = QPointF(-1, -1)
        self.cross_reference_hide_count += 1

    def show_cross_reference(self, position: QPointF) -> None:
        self.cross_reference_visible = True
        self.cross_reference_pos = QPointF(position)

class _PresentationViewer(_RecordingViewer):
    def __init__(self, model: ImageDataModel, slice_index: int = 0) -> None:
        super().__init__()
        self.model = model
        self.current_slice_index = slice_index
        self.window_width = float(model.window_width)
        self.window_level = float(model.window_level)

    def set_view_slice(self, slice_index: int, *, emit: bool = True) -> bool:
        self.current_slice_index = int(slice_index)
        return True

    def set_view_window(
        self, window_width: float, window_level: float, *, emit: bool = True
    ) -> None:
        self.window_width = float(window_width)
        self.window_level = float(window_level)


class _ViewerGrid:
    def __init__(self, viewers: dict[str, _RecordingViewer]) -> None:
        self._viewers = viewers

    def get_view_frame(self, view_id: str):
        viewer = self._viewers.get(view_id)
        return SimpleNamespace(image_viewer=viewer) if viewer is not None else None


def _model_with_geometry(
    positions: list[tuple[float, float, float]],
    *,
    shape: tuple[int, int] = (32, 32),
    spacing: tuple[float, float] = (1.0, 1.0),
    orientation: tuple[float, ...] = (1, 0, 0, 0, 1, 0),
    frame_uid: str,
) -> ImageDataModel:
    model = ImageDataModel()
    pixels = np.zeros((len(positions), *shape), dtype=np.float32)
    assert model.load_single_image(pixels, {"PixelSpacing": list(spacing)})

    datasets = []
    for index, position in enumerate(positions):
        dataset = make_dicom_dataset(
            np.zeros(shape, dtype=np.int16),
            position=position,
            orientation=orientation,
            pixel_spacing=spacing,
            instance_number=index + 1,
        )
        dataset.FrameOfReferenceUID = frame_uid
        datasets.append(dataset)
    model.dicom_files = datasets
    return model


def _bind_two_series(
    source_model: ImageDataModel,
    target_model: ImageDataModel,
    *,
    patient_id: str = "PATIENT-1",
    study_uid: str = "1.2.826.0.1.3680043.10.1000.1",
) -> tuple[MultiSeriesManager, SyncManager]:
    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    for series_id, model in (("source", source_model), ("target", target_model)):
        series_manager.add_series(
            SeriesInfo(
                series_id=series_id,
                patient_id=patient_id,
                study_instance_uid=study_uid,
                modality="CT",
            )
        )
        assert series_manager.load_series_data(series_id, model)
    assert series_manager.bind_series_to_view("view_0_0", "source")
    assert series_manager.bind_series_to_view("view_0_1", "target")
    return series_manager, SyncManager(series_manager)


@pytest.mark.parametrize(
    ("mode", "expected_zoom", "expected_pan"),
    [
        (SyncMode.ZOOM, True, False),
        (SyncMode.PAN, False, True),
    ],
)
def test_zoom_and_pan_modes_are_independent(mode, expected_zoom, expected_pan):
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((8, 8), dtype=np.float32))

    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    series_manager.add_series(
        SeriesInfo(
            series_id="shared",
            patient_id="PATIENT-1",
            study_instance_uid="1.2.826.0.1.3680043.10.1000.2",
        )
    )
    assert series_manager.load_series_data("shared", model)
    assert series_manager.bind_series_to_view("view_0_0", "shared")
    assert series_manager.bind_series_to_view("view_0_1", "shared")

    sync_manager = SyncManager(series_manager)
    target_viewer = _RecordingViewer()
    sync_manager.set_viewer_grid(_ViewerGrid({"view_0_1": target_viewer}))
    sync_manager.set_sync_mode(mode)
    sync_manager.sync_zoom_pan(
        "view_0_0",
        2.5,
        QPointF(7, 9),
        QTransform().scale(2.5, 2.5),
    )

    assert SyncMode.ZOOM_PAN == (SyncMode.ZOOM | SyncMode.PAN)
    assert len(target_viewer.calls) == 1
    assert target_viewer.calls[0]["sync_zoom"] is expected_zoom
    assert target_viewer.calls[0]["sync_pan"] is expected_pan
    assert target_viewer.zoom == (2.5 if expected_zoom else 1.0)
    assert target_viewer.center == (QPointF(7, 9) if expected_pan else QPointF(0, 0))


@pytest.mark.parametrize("unknown_value", ["", "Unknown", "N/A", "none"])
def test_default_same_study_does_not_match_unknown_identifiers(unknown_value):
    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    for series_id in ("one", "two"):
        series_manager.add_series(
            SeriesInfo(series_id=series_id, study_instance_uid=unknown_value)
        )
    assert series_manager.bind_series_to_view("view_0_0", "one")
    assert series_manager.bind_series_to_view("view_0_1", "two")

    sync_manager = SyncManager(series_manager)

    assert sync_manager.get_sync_group() is SyncGroup.SAME_STUDY
    assert sync_manager.get_sync_targets_for_view("view_0_0") == set()


def test_slice_sync_uses_nearest_patient_space_plane():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5), (0, 0, 10)], frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(0, 0, -1), (0, 0, 4), (0, 0, 9), (0, 0, 14)],
        frame_uid=frame_uid,
    )
    _, sync_manager = _bind_two_series(source_model, target_model)
    sync_manager.set_sync_mode(SyncMode.SLICE)

    sync_manager.sync_slice("view_0_0", 2)

    assert target_model.current_slice_index == 2

def test_sync_updates_pane_state_without_mutating_bound_model_presentation():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5), (0, 0, 10)], frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5), (0, 0, 10)], frame_uid=frame_uid
    )
    _, sync_manager = _bind_two_series(source_model, target_model)
    target_viewer = _PresentationViewer(target_model)
    sync_manager.set_viewer_grid(_ViewerGrid({"view_0_1": target_viewer}))
    sync_manager.set_sync_mode(SyncMode.SLICE | SyncMode.WINDOW_LEVEL)
    original_window = (target_model.window_width, target_model.window_level)

    sync_manager.sync_slice("view_0_0", 2)
    sync_manager.sync_window_level("view_0_0", 812.5, -123.25)

    assert target_viewer.current_slice_index == 2
    assert (target_viewer.window_width, target_viewer.window_level) == (812.5, -123.25)
    assert target_model.current_slice_index == 0
    assert (target_model.window_width, target_model.window_level) == original_window


def test_patient_coordinate_conversion_uses_each_pane_local_slice():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0), (10, 0, 5)], frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(0, 0, 0), (8, 0, 5)], frame_uid=frame_uid
    )
    _, sync_manager = _bind_two_series(source_model, target_model)
    source_viewer = _PresentationViewer(source_model, slice_index=1)
    target_viewer = _PresentationViewer(target_model, slice_index=1)
    sync_manager.set_viewer_grid(
        _ViewerGrid(
            {
                "view_0_0": source_viewer,
                "view_0_1": target_viewer,
            }
        )
    )
    updates: list[tuple[str, QPointF]] = []
    sync_manager.cross_reference_updated.connect(
        lambda view_id, point: updates.append((view_id, QPointF(point)))
    )
    sync_manager.set_sync_mode(SyncMode.CROSS_REFERENCE)

    sync_manager.update_cross_reference("view_0_0", QPointF(4, 3))

    assert len(updates) == 1
    assert updates[0][0] == "view_0_1"
    assert updates[0][1].x() == pytest.approx(6.0)
    assert updates[0][1].y() == pytest.approx(3.0)
    assert source_model.current_slice_index == 0
    assert target_model.current_slice_index == 0

@pytest.mark.parametrize("missing_side", ["source", "target"])
def test_cross_model_sync_requires_frame_of_reference_uid_on_both_sides(
    missing_side,
):
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5)], frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5)], frame_uid=frame_uid
    )
    missing_model = source_model if missing_side == "source" else target_model
    for dataset in missing_model.dicom_files:
        del dataset.FrameOfReferenceUID

    _, sync_manager = _bind_two_series(source_model, target_model)
    updates: list[tuple[str, QPointF]] = []
    sync_manager.cross_reference_updated.connect(
        lambda view_id, point: updates.append((view_id, QPointF(point)))
    )
    sync_manager.set_sync_mode(SyncMode.SLICE | SyncMode.CROSS_REFERENCE)

    sync_manager.sync_slice("view_0_0", 1)
    sync_manager.update_cross_reference("view_0_0", QPointF(4, 3))

    assert target_model.current_slice_index == 0
    assert updates == []


def test_slice_sync_does_not_snap_to_non_overlapping_stack():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0), (0, 0, 5), (0, 0, 10)], frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(0, 0, 100), (0, 0, 105), (0, 0, 110)], frame_uid=frame_uid
    )
    assert target_model.set_current_slice(1)
    _, sync_manager = _bind_two_series(source_model, target_model)
    sync_manager.set_sync_mode(SyncMode.SLICE)

    sync_manager.sync_slice("view_0_0", 2)

    assert target_model.current_slice_index == 1


def test_full_sync_excludes_annotation_copy_modes():
    assert not bool(SyncMode.FULL & SyncMode.ROI)
    assert not bool(SyncMode.FULL & SyncMode.MEASUREMENT)
    assert SyncMode.FULL == (SyncMode.ADVANCED | SyncMode.CROSS_REFERENCE)


def test_cross_reference_converts_pixels_through_patient_space():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry(
        [(0, 0, 0)], spacing=(2.0, 0.5), frame_uid=frame_uid
    )
    target_model = _model_with_geometry(
        [(1, 2, 0)], spacing=(1.0, 1.0), frame_uid=frame_uid
    )
    _, sync_manager = _bind_two_series(source_model, target_model)
    updates: list[tuple[str, QPointF]] = []
    sync_manager.cross_reference_updated.connect(
        lambda view_id, point: updates.append((view_id, QPointF(point)))
    )
    sync_manager.set_sync_mode(SyncMode.CROSS_REFERENCE)

    # Source pixel (x=4, y=3) is patient point (2, 6, 0).  Relative to the
    # target origin (1, 2, 0), that is target pixel (1, 4).
    sync_manager.update_cross_reference("view_0_0", QPointF(4, 3))

    assert len(updates) == 1
    assert updates[0][0] == "view_0_1"
    assert updates[0][1].x() == pytest.approx(1.0)
    assert updates[0][1].y() == pytest.approx(4.0)


def test_grid_routes_cross_reference_signal_only_to_named_target_view():
    viewers = {
        "view_0_0": _RecordingViewer(),
        "view_0_1": _RecordingViewer(),
        "view_0_2": _RecordingViewer(),
    }
    grid = SimpleNamespace(
        _view_frames={
            view_id: SimpleNamespace(image_viewer=viewer)
            for view_id, viewer in viewers.items()
        }
    )
    position = QPointF(7, 11)

    MultiViewerGrid._on_cross_reference_updated(grid, "view_0_1", position)

    assert viewers["view_0_1"].cross_reference_visible
    assert viewers["view_0_1"].cross_reference_pos == position
    assert not viewers["view_0_0"].cross_reference_visible
    assert not viewers["view_0_2"].cross_reference_visible


def test_clearing_source_cross_reference_hides_its_target_line():
    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    source_view_id, target_view_id = series_manager.get_all_view_ids()
    viewers = {
        source_view_id: _RecordingViewer(),
        target_view_id: _RecordingViewer(),
    }
    sync_manager = SyncManager(series_manager)
    sync_manager.set_viewer_grid(_ViewerGrid(viewers))
    sync_manager.set_sync_mode(SyncMode.CROSS_REFERENCE)
    state = sync_manager.get_cross_reference_state()
    state.source_view_id = source_view_id
    state.cursor_scene_pos = QPointF(4, 5)
    viewers[target_view_id].show_cross_reference(QPointF(4, 5))

    sync_manager.clear_cross_reference("unrelated-view")
    assert viewers[target_view_id].cross_reference_visible

    sync_manager.clear_cross_reference(source_view_id)

    assert not viewers[target_view_id].cross_reference_visible
    assert viewers[target_view_id].cross_reference_pos == QPointF(-1, -1)
    assert viewers[target_view_id].cross_reference_hide_count == 1


def test_slice_request_clears_stale_cross_reference_even_when_slice_sync_is_off():
    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    source_view_id, target_view_id = series_manager.get_all_view_ids()
    viewers = {
        source_view_id: _RecordingViewer(),
        target_view_id: _RecordingViewer(),
    }
    sync_manager = SyncManager(series_manager)
    sync_manager.set_viewer_grid(_ViewerGrid(viewers))
    sync_manager.set_sync_mode(SyncMode.CROSS_REFERENCE)
    state = sync_manager.get_cross_reference_state()
    state.source_view_id = source_view_id
    state.cursor_scene_pos = QPointF(3, 4)
    viewers[target_view_id].show_cross_reference(QPointF(3, 4))

    sync_manager.sync_slice(source_view_id, 0)

    assert sync_manager.get_cross_reference_state().source_view_id is None
    assert not viewers[target_view_id].cross_reference_visible
    assert viewers[target_view_id].cross_reference_hide_count == 1


def test_binding_change_clears_stale_cross_reference_lines():
    series_manager = MultiSeriesManager()
    assert series_manager.set_layout(1, 2)
    source_view_id, target_view_id = series_manager.get_all_view_ids()
    for series_id in ("series-one", "series-two"):
        series_manager.add_series(SeriesInfo(series_id=series_id))
    sync_manager = SyncManager(series_manager)
    viewers = {
        source_view_id: _RecordingViewer(),
        target_view_id: _RecordingViewer(),
    }
    sync_manager.set_viewer_grid(_ViewerGrid(viewers))
    assert series_manager.bind_series_to_view(source_view_id, "series-one")
    assert series_manager.bind_series_to_view(target_view_id, "series-two")

    state = sync_manager.get_cross_reference_state()
    state.enabled = True
    state.source_view_id = source_view_id
    state.cursor_scene_pos = QPointF(6, 7)
    viewers[target_view_id].show_cross_reference(QPointF(6, 7))
    hide_count_before = viewers[target_view_id].cross_reference_hide_count

    assert series_manager.bind_series_to_view(target_view_id, "series-one")

    assert sync_manager.get_cross_reference_state().source_view_id is None
    assert not viewers[target_view_id].cross_reference_visible
    assert viewers[target_view_id].cross_reference_hide_count == hide_count_before + 1


def test_cross_reference_rejects_point_far_from_target_current_slice_plane():
    frame_uid = pydicom.uid.generate_uid()
    source_model = _model_with_geometry([(0, 0, 0)], frame_uid=frame_uid)
    target_model = _model_with_geometry([(0, 0, 50)], frame_uid=frame_uid)
    _, sync_manager = _bind_two_series(source_model, target_model)
    updates: list[tuple[str, QPointF]] = []
    sync_manager.cross_reference_updated.connect(
        lambda view_id, point: updates.append((view_id, QPointF(point)))
    )
    sync_manager.set_sync_mode(SyncMode.CROSS_REFERENCE)

    sync_manager.update_cross_reference("view_0_0", QPointF(4, 3))

    assert updates == []


def _screen_axis_lengths(transform: QTransform) -> tuple[float, float]:
    origin = transform.map(QPointF(0, 0))
    x_point = transform.map(QPointF(1, 0))
    y_point = transform.map(QPointF(0, 1))
    return (
        math.hypot(x_point.x() - origin.x(), x_point.y() - origin.y()),
        math.hypot(y_point.x() - origin.x(), y_point.y() - origin.y()),
    )


def test_viewer_applies_pixel_spacing_aspect_ratio(qapp):
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((6, 10), dtype=np.float32), {"PixelSpacing": [2.0, 1.0]}
    )
    viewer = ImageViewer()
    viewer.resize(320, 240)
    viewer.set_model(model)
    image = QImage(10, 6, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    qapp.processEvents()

    x_length, y_length = _screen_axis_lengths(viewer.transform())

    assert x_length > 0
    assert y_length / x_length == pytest.approx(2.0)
    viewer.deleteLater()


def test_viewer_rotation_flip_keep_positive_scale_and_shared_scene_geometry(qapp):
    model = ImageDataModel()
    assert model.load_single_image(
        np.arange(60, dtype=np.float32).reshape(6, 10),
        {"PixelSpacing": [2.0, 1.0]},
    )
    viewer = ImageViewer()
    viewer.resize(320, 240)
    viewer.set_model(model)
    image = QImage(10, 6, QImage.Format.Format_Grayscale8)
    image.fill(0)
    viewer.display_qimage(image)
    viewer.set_synced_view_state(2.0, sync_zoom=True, sync_pan=False)
    viewer.rotate_right()
    viewer.flip_horizontal()
    qapp.processEvents()

    scene_point = QPointF(3, 2)
    viewport_point = viewer.mapFromScene(scene_point)
    round_trip = viewer.mapToScene(viewport_point)

    assert viewer.effective_scale() > 0
    assert viewer.image_item is not None
    assert viewer.image_item.sceneTransform().isIdentity()
    assert viewer.image_item.pixmap().size().width() == 10
    assert viewer.image_item.pixmap().size().height() == 6
    assert round_trip.x() == pytest.approx(scene_point.x(), abs=0.5)
    assert round_trip.y() == pytest.approx(scene_point.y(), abs=0.5)
    assert model.get_pixel_value(int(scene_point.x()), int(scene_point.y())) == 23.0
    viewer.deleteLater()


def _tree_items(panel: DicomTagPanel):
    def walk(item):
        yield item
        for child_index in range(item.childCount()):
            yield from walk(item.child(child_index))

    root = panel.tree_widget.invisibleRootItem()
    for index in range(root.childCount()):
        yield from walk(root.child(index))


def _find_tree_item(panel: DicomTagPanel, *, tag: str | None = None, value: str | None = None):
    for item in _tree_items(panel):
        if tag is not None and item.text(panel.TAG_COLUMN) != tag:
            continue
        if value is not None and value not in item.text(panel.VALUE_COLUMN):
            continue
        return item
    return None


def _metadata_dataset() -> Dataset:
    dataset = Dataset()
    dataset.PatientName = "Viewer^Patient"
    dataset.PatientID = "P-42"
    nested = Dataset()
    nested.ScheduledProcedureStepID = "NESTED-42"
    dataset.RequestAttributesSequence = Sequence([nested])
    dataset.add_new((0x0011, 0x0010), "LO", "MEDIMAGER")
    dataset.add_new((0x0011, 0x1010), "LO", "PRIVATE-SECRET")
    dataset.PixelData = b"bulk-pixel-bytes"
    return dataset


def test_dicom_tag_panel_searches_nested_values_and_hides_bulk_and_private(qapp):
    panel = DicomTagPanel()
    panel.update_tags(_metadata_dataset())

    assert _find_tree_item(panel, tag="(7FE0,0010)") is None
    assert _find_tree_item(panel, tag="(0011,1010)") is None

    panel.search_edit.setText("nested-42")
    qapp.processEvents()
    nested_item = _find_tree_item(panel, value="NESTED-42")

    assert nested_item is not None
    assert not nested_item.isHidden()
    parent = nested_item.parent()
    while parent is not None:
        assert not parent.isHidden()
        parent = parent.parent()

    panel.search_edit.clear()
    panel.show_private_checkbox.setChecked(True)
    qapp.processEvents()
    assert _find_tree_item(panel, tag="(0011,1010)", value="PRIVATE-SECRET") is not None
    panel.deleteLater()


def test_dicom_tag_panel_copy_row_includes_structured_columns(qapp, monkeypatch):
    panel = DicomTagPanel()
    panel.update_tags(_metadata_dataset())
    patient_name = _find_tree_item(panel, tag="(0010,0010)")
    assert patient_name is not None
    panel.tree_widget.setCurrentItem(patient_name)

    # The system clipboard can be locked by another Windows process. Capture
    # the exact payload without depending on mutable global desktop state.
    copied_text = {}

    class _Clipboard:
        def setText(self, text: str) -> None:
            copied_text["value"] = text

    class _Application:
        @staticmethod
        def clipboard():
            return _Clipboard()

    monkeypatch.setattr(dicom_tag_panel_module, "QApplication", _Application)

    panel._copy_current_row()
    copied = copied_text["value"].split("\t")

    assert copied[panel.TAG_COLUMN] == "(0010,0010)"
    assert copied[panel.KEYWORD_COLUMN] == "PatientName"
    assert copied[panel.VR_COLUMN] == "PN"
    assert copied[panel.VALUE_COLUMN] == "Viewer^Patient"
    panel.deleteLater()


def test_dicom_tag_copy_shortcut_is_scoped_to_tree_and_preserves_search_copy(
    qapp, monkeypatch
):
    copy_row_calls = []
    monkeypatch.setattr(
        DicomTagPanel,
        "_copy_current_row",
        lambda _panel: copy_row_calls.append(True),
    )
    panel = DicomTagPanel()
    panel.update_tags(_metadata_dataset())
    panel.resize(720, 420)
    panel.show()
    qapp.processEvents()

    action = panel.copy_row_action
    assert action.text() == t("dicomtagpanel.copy_row")
    assert action.parent() is panel.tree_widget
    assert action in panel.tree_widget.actions()
    assert action.shortcut() == QKeySequence(QKeySequence.StandardKey.Copy)
    assert action.shortcutContext() is Qt.ShortcutContext.WidgetShortcut

    panel.search_edit.setText("search text")
    panel.search_edit.selectAll()
    panel.search_edit.setFocus()
    qapp.clipboard().setText("clipboard sentinel")
    qapp.processEvents()
    if qapp.clipboard().text() != "clipboard sentinel":
        pytest.skip("Windows system clipboard is unavailable in this session")
    assert qapp.focusWidget() is panel.search_edit

    QTest.keyClick(panel.search_edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()

    assert qapp.clipboard().text() == "search text"
    assert copy_row_calls == []

    panel.tree_widget.setCurrentItem(
        _find_tree_item(panel, tag="(0010,0010)")
    )
    panel.tree_widget.setFocus()
    qapp.processEvents()
    assert qapp.focusWidget() is panel.tree_widget

    QTest.keyClick(panel.tree_widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()

    assert copy_row_calls == [True]
    panel.deleteLater()
    qapp.processEvents()
