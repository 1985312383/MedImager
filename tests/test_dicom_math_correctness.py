import math

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QTransform
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from medimager.core.analysis import calculate_roi_statistics
from medimager.core.dicom_parser import DicomParser
from medimager.core.image_data_model import (
    AngleMeasurementData,
    ImageDataModel,
    MeasurementData,
)
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI
from medimager.ui.tools.angle_tool import AngleTool
from medimager.ui.tools.default_tool import DefaultTool
from medimager.ui.tools.measurement_tool import MeasurementTool
from medimager.utils.settings import PerformanceManager, get_performance_manager
from tests.dicom_fixtures import make_dicom_dataset, write_dicom


class _FakeViewport:
    def __init__(self):
        self.update_count = 0

    def update(self):
        self.update_count += 1


class _FakeViewer:
    def __init__(self, model):
        self.model = model
        self._viewport = _FakeViewport()

    def viewport(self):
        return self._viewport

    def effective_scale(self):
        return 2.0

    def transform(self):
        return QTransform()

    def setCursor(self, _cursor):
        pass


def _enhanced_multiframe_dataset():
    raw = np.asarray([[[1, 1]], [[2, 2]]], dtype=np.int16)
    ds = make_dicom_dataset(raw, pixel_spacing=None, slope=1, intercept=0)
    del ds.RescaleSlope
    del ds.RescaleIntercept

    shared = Dataset()
    shared_measures = Dataset()
    shared_measures.PixelSpacing = [0.5, 1.0]
    shared.PixelMeasuresSequence = Sequence([shared_measures])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    frame_groups = []
    for index, (spacing, slope, intercept) in enumerate(
        [([0.5, 1.0], 2.0, 10.0), ([2.0, 3.0], 3.0, 20.0)]
    ):
        group = Dataset()

        measures = Dataset()
        measures.PixelSpacing = spacing
        group.PixelMeasuresSequence = Sequence([measures])

        transform = Dataset()
        transform.RescaleSlope = slope
        transform.RescaleIntercept = intercept
        group.PixelValueTransformationSequence = Sequence([transform])

        position = Dataset()
        position.ImagePositionPatient = [0.0, 0.0, float(index)]
        group.PlanePositionSequence = Sequence([position])

        content = Dataset()
        content.InStackPositionNumber = index + 1
        group.FrameContentSequence = Sequence([content])
        frame_groups.append(group)

    ds.PerFrameFunctionalGroupsSequence = Sequence(frame_groups)
    return ds


def test_standard_pixel_spacing_produces_mm_distance():
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((4, 4), dtype=np.float32),
        {"PixelSpacing": [0.5, 2.0]},
    )
    tool = MeasurementTool(_FakeViewer(model))

    distance, unit = tool._calculate_real_distance(QPointF(0, 0), QPointF(2, 2))

    assert unit == "mm"
    assert distance == pytest.approx(math.sqrt(17.0))


def test_imager_pixel_spacing_alias_is_supported():
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((2, 2), dtype=np.float32),
        {"ImagerPixelSpacing": [0.25, 0.75]},
    )

    assert model.get_pixel_spacing() == (0.25, 0.75)
    assert model.get_pixel_aspect_ratio() == 3.0


def test_angle_uses_physical_pixel_spacing():
    p1 = QPointF(1, 1)
    vertex = QPointF(0, 0)
    p3 = QPointF(1, 0)

    pixel_angle = AngleTool._calculate_angle(p1, vertex, p3)
    physical_angle = AngleTool._calculate_angle(
        p1, vertex, p3, pixel_spacing=(2.0, 1.0)
    )

    assert pixel_angle == pytest.approx(45.0)
    assert physical_angle == pytest.approx(math.degrees(math.atan2(2.0, 1.0)))


@pytest.mark.parametrize(
    "roi",
    [
        RectangleROI((-10, -10), (-5, -5), 0),
        RectangleROI((20, 20), (30, 30), 0),
        CircleROI((-10, -10), 2, 0),
        EllipseROI((20, 20), 2, 3, 0),
    ],
)
def test_fully_outside_roi_mask_is_empty(roi):
    assert not np.any(roi.get_mask(10, 10))


def test_roi_area_uses_spacing_for_its_own_multiframe_slice(tmp_path):
    path = write_dicom(tmp_path / "enhanced.dcm", _enhanced_multiframe_dataset())
    model = ImageDataModel()
    assert model.load_dicom_series([str(path)])
    roi = RectangleROI((0, 0), (0, 1), 1)

    stats = calculate_roi_statistics(model, roi)

    assert model.get_pixel_spacing(0) == (0.5, 1.0)
    assert model.get_pixel_spacing(1) == (2.0, 3.0)
    assert stats["count"] == 2
    assert stats["area_mm2"] == 12.0


def test_multiframe_metadata_and_modality_transform_map_per_frame():
    parser = DicomParser()
    ds = _enhanced_multiframe_dataset()

    pixels = parser._extract_pixel_data([ds])

    assert pixels.shape == (2, 1, 2)
    assert np.all(pixels[0] == 12.0)
    assert np.all(pixels[1] == 26.0)
    assert len(parser.get_datasets()) == 2
    assert [float(v) for v in parser.get_metadata(1)["ImagePositionPatient"]] == [
        0.0,
        0.0,
        1.0,
    ]
    assert parser.get_pixel_spacing(1) == (2.0, 3.0)
    assert parser.get_frame_source(1) == (ds, 1)


def test_failed_reload_clears_previous_dicom_state(tmp_path):
    path = write_dicom(
        tmp_path / "valid.dcm",
        make_dicom_dataset(np.ones((2, 2), dtype=np.int16)),
    )
    parser = DicomParser()
    assert parser.load_series([str(path)])

    assert not parser.load_series([str(tmp_path / "missing.dcm")])

    assert parser.get_pixel_array() is None
    assert parser.get_datasets() == []
    assert parser.get_source_datasets() == []


def test_dicom_linear_window_formula_and_width_one_threshold():
    model = ImageDataModel()
    assert model.load_single_image(
        np.asarray([[0.0, 0.5, 1.0, 2.0]], dtype=np.float32)
    )
    model.set_window(2, 1)

    assert model.apply_window_level(model.get_current_slice_data()).tolist() == [
        [0, 127, 255, 255]
    ]

    model.set_window(1, 1)
    values = np.asarray([[0.5, 0.5001]], dtype=np.float32)
    assert model.apply_window_level(values).tolist() == [[0, 255]]


def test_dicom_voi_lut_is_display_only_and_preserves_quantitative_pixels(tmp_path):
    raw = np.asarray([[0, 1, 2, 3]], dtype=np.int16)
    ds = make_dicom_dataset(
        raw,
        window_center=None,
        window_width=None,
        slope=2.0,
        intercept=0.0,
    )
    voi = Dataset()
    voi.LUTDescriptor = [7, 0, 8]
    voi.add_new((0x0028, 0x3006), "US", [0, 20, 40, 80, 120, 180, 255])
    ds.VOILUTSequence = Sequence([voi])
    path = write_dicom(tmp_path / "voi_lut.dcm", ds)
    model = ImageDataModel()

    assert model.load_dicom_series([str(path)])

    assert model.get_current_slice_data().tolist() == [[0.0, 2.0, 4.0, 6.0]]
    assert model.get_display_slice().tolist() == [[0, 40, 120, 255]]


@pytest.mark.parametrize(
    "width,level",
    [(0, 1), (-1, 1), (float("nan"), 1), (2, float("inf"))],
)
def test_invalid_window_values_are_rejected(width, level):
    model = ImageDataModel()
    with pytest.raises(ValueError):
        model.set_window(width, level)


def test_instance_number_zero_is_sorted_as_a_valid_value():
    parser = DicomParser()
    datasets = [
        make_dicom_dataset(np.full((2, 2), 2, dtype=np.int16), position=None, instance_number=2),
        make_dicom_dataset(np.full((2, 2), 0, dtype=np.int16), position=None, instance_number=0),
        make_dicom_dataset(np.full((2, 2), 1, dtype=np.int16), position=None, instance_number=1),
    ]

    sorted_datasets = parser._sort_dicom_slices(datasets)

    assert [int(ds.InstanceNumber) for ds in sorted_datasets] == [0, 1, 2]


def test_series_grouping_separates_stack_and_temporal_position(tmp_path):
    paths = []
    series_uid = pydicom.uid.generate_uid()
    for stack, temporal in [("A", 1), ("A", 2), ("B", 1)]:
        ds = make_dicom_dataset(np.zeros((2, 2), dtype=np.int16))
        ds.SeriesInstanceUID = series_uid
        ds.StackID = stack
        ds.TemporalPositionIdentifier = temporal
        paths.append(
            str(write_dicom(tmp_path / f"{stack}_{temporal}.dcm", ds))
        )

    groups = DicomParser()._group_files_by_series(paths)

    assert len(groups) == 3
    assert all(len(files) == 1 for files in groups.values())


def test_missing_series_uid_uses_stable_noncolliding_fallback(tmp_path):
    shared_study_uid = pydicom.uid.generate_uid()
    paths = []
    for folder_name in ("one", "two"):
        folder = tmp_path / folder_name
        folder.mkdir()
        ds = make_dicom_dataset(np.zeros((2, 2), dtype=np.int16))
        ds.StudyInstanceUID = shared_study_uid
        del ds.SeriesInstanceUID
        paths.append(str(write_dicom(folder / "image.dcm", ds)))

    groups = DicomParser()._group_files_by_series(paths)

    assert len(groups) == 2
    assert all(key.startswith("missing-series-") for key in groups)


def test_display_cache_is_byte_bounded_and_lru():
    manager = PerformanceManager()
    manager._cache_size_mb = 1

    def entry(value):
        return np.full(400 * 1024, value, dtype=np.uint8)

    manager.add_to_cache("a", entry(1))
    manager.add_to_cache("b", entry(2))
    assert manager.get_from_cache("a") is not None
    manager.add_to_cache("c", entry(3))

    assert manager.get_from_cache("a") is not None
    assert manager.get_from_cache("b") is None
    assert manager.get_from_cache("c") is not None
    info = manager.get_cache_info()
    assert info["usage_bytes"] <= info["limit_bytes"]
    assert info["estimated_usage_mb"] == pytest.approx(
        info["usage_bytes"] / (1024 * 1024)
    )


def test_display_cache_key_changes_when_model_reloads():
    performance = get_performance_manager()
    performance.clear_cache()
    model = ImageDataModel()

    assert model.load_single_image(np.zeros((2, 2), dtype=np.float32))
    model.set_window(100, 50)
    first = model.get_display_slice().copy()

    assert model.load_single_image(np.full((2, 2), 100, dtype=np.float32))
    model.set_window(100, 50)
    second = model.get_display_slice().copy()

    assert np.all(first == 0)
    assert np.all(second == 255)


def test_annotation_dirty_and_selected_angle_delete_lifecycle():
    model = ImageDataModel()
    model.add_angle_measurement(
        AngleMeasurementData(
            id="current",
            slice_index=0,
            point1=QPointF(0, 0),
            vertex=QPointF(1, 1),
            point3=QPointF(2, 0),
            angle_degrees=90.0,
        )
    )
    model.add_angle_measurement(
        AngleMeasurementData(
            id="other-slice",
            slice_index=1,
            point1=QPointF(0, 0),
            vertex=QPointF(1, 1),
            point3=QPointF(2, 0),
            angle_degrees=90.0,
        )
    )
    assert model.has_unsaved_annotations()
    model.mark_annotations_saved()
    assert not model.has_unsaved_annotations()

    model.select_angle_measurement("current")
    tool = AngleTool(_FakeViewer(model))
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    tool.key_press_event(event)

    assert [measurement.id for measurement in model.angle_measurements] == [
        "other-slice"
    ]
    assert model.has_unsaved_annotations()


def test_default_delete_removes_all_selected_annotation_types_in_one_change():
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((8, 8), dtype=np.float32))
    roi = RectangleROI((1, 1), (3, 3), 0)
    roi.id = "selected-roi"
    model.add_roi(roi)
    model.add_measurement(
        MeasurementData(
            id="selected-distance",
            slice_index=0,
            start_point=QPointF(1, 1),
            end_point=QPointF(4, 1),
            distance=3.0,
            unit="px",
        )
    )
    model.add_angle_measurement(
        AngleMeasurementData(
            id="selected-angle",
            slice_index=0,
            point1=QPointF(0, 0),
            vertex=QPointF(1, 1),
            point3=QPointF(2, 0),
            angle_degrees=90.0,
        )
    )
    model.select_roi("selected-roi")
    assert model.select_measurement(0)
    assert model.select_angle_measurement("selected-angle", multi=True)
    model.mark_annotations_saved()
    changes = []
    model.annotation_changed.connect(lambda: changes.append(True))
    viewer = _FakeViewer(model)
    viewer.stats_box_positions = {"selected-roi": object()}
    tool = DefaultTool(viewer)
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)

    tool.key_press_event(event)

    assert model.rois == []
    assert model.measurements == []
    assert model.angle_measurements == []
    assert changes == [True]
    assert model.has_unsaved_annotations()
    assert viewer._viewport.update_count == 1
    assert "selected-roi" not in viewer.stats_box_positions
