from __future__ import annotations

import numpy as np
from pydicom.dataset import Dataset

from medimager.core.volume_geometry import MprPlane, VolumeBuilder
from medimager.ui.mpr_workspace import MprWorkspace


class _MprModel:
    image_mode = "grayscale_volume"
    window_width = 400.0
    window_level = 40.0

    def __init__(self):
        self.rois = []
        self.measurements = []
        self.angle_measurements = []
        self.pixels = np.stack(
            [np.arange(48, dtype=np.float32).reshape(6, 8) + index * 100 for index in range(5)]
        )
        self.datasets = []
        for index in range(5):
            dataset = Dataset()
            dataset.Modality = "CT"
            dataset.Rows = 6
            dataset.Columns = 8
            dataset.ImagePositionPatient = [0.0, 0.0, index * 2.0]
            dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            dataset.PixelSpacing = [1.5, 1.0]
            dataset.FrameOfReferenceUID = "1.2.3"
            dataset.SeriesInstanceUID = "1.2.3.4"
            dataset.SamplesPerPixel = 1
            dataset.PhotometricInterpretation = "MONOCHROME2"
            self.datasets.append(dataset)

    def get_slice_count(self):
        return len(self.datasets)

    def get_metadata(self, key, default=None):
        return getattr(self.datasets[0], key, default)

    def get_dicom_file(self, index):
        return self.datasets[index]

    def get_image_shape(self):
        return self.pixels.shape

    def get_slice_data(self, index):
        return self.pixels[index]

    def get_slice_metadata(self, index):
        dataset = self.datasets[index]
        return {
            "ImagePositionPatient": dataset.ImagePositionPatient,
            "ImageOrientationPatient": dataset.ImageOrientationPatient,
        }

    def get_pixel_spacing(self, index):
        return tuple(float(value) for value in self.datasets[index].PixelSpacing)

    def has_image(self):
        return True

    def add_roi(self, item):
        self.rois.append(item)

    def add_measurement(self, item):
        self.measurements.append(item)

    def add_angle_measurement(self, item):
        self.angle_measurements.append(item)


def test_mpr_workspace_builds_three_linked_patient_space_views(qtbot):
    model = _MprModel()
    workspace = MprWorkspace()
    qtbot.addWidget(workspace)
    workspace.show()

    workspace.start_build(model, "series", 128 * 1024 * 1024)
    qtbot.waitUntil(lambda: workspace.is_ready, timeout=5000)

    assert set(workspace.viewports) == set(MprPlane)
    assert all(viewport.scene().sceneRect().width() > 0 for viewport in workspace.viewports.values())
    cursor = workspace._state.cursor_lps.copy()
    for viewport in workspace.viewports.values():
        x, y = viewport._plane_geometry.patient_to_pixel(cursor)
        round_trip = viewport._plane_geometry.pixel_to_patient(x, y)
        normal = np.asarray(viewport._plane_geometry.normal_lps)
        delta = cursor - round_trip
        assert np.linalg.norm(delta - normal * np.dot(delta, normal)) < 1e-6


def test_mpr_scroll_moves_cursor_along_active_plane_normal(qtbot):
    workspace = MprWorkspace()
    qtbot.addWidget(workspace)
    workspace.start_build(_MprModel(), "series", 128 * 1024 * 1024)
    qtbot.waitUntil(lambda: workspace.is_ready, timeout=5000)
    before = workspace._state.cursor_lps.copy()

    workspace.scroll_plane(MprPlane.AXIAL, 1)
    qtbot.waitUntil(lambda: not np.allclose(workspace._state.cursor_lps, before), timeout=1000)

    delta = workspace._state.cursor_lps - before
    assert delta[2] > 0
    assert abs(delta[0]) < 1e-6
    assert abs(delta[1]) < 1e-6


def test_mpr_workspace_cancel_result_does_not_replace_2d_data(qtbot):
    workspace = MprWorkspace()
    qtbot.addWidget(workspace)
    model = _MprModel()
    inspection = VolumeBuilder.inspect(model, memory_budget_bytes=1)
    assert not inspection.compatible
    workspace.start_build(model, "series", 1)
    qtbot.waitUntil(lambda: workspace._future is None, timeout=3000)
    assert not workspace.is_ready
    assert model.has_image()



def test_mpr_creates_all_patient_space_annotation_types_and_projects_them(qtbot):
    workspace = MprWorkspace()
    qtbot.addWidget(workspace)
    model = _MprModel()
    workspace.start_build(model, "series", 128 * 1024 * 1024)
    qtbot.waitUntil(lambda: workspace.is_ready, timeout=5000)
    geometry = workspace.viewports[MprPlane.CORONAL]._plane_geometry
    assert geometry is not None
    first = geometry.pixel_to_patient(1, 1)
    second = geometry.pixel_to_patient(4, 3)
    third = geometry.pixel_to_patient(5, 1)

    workspace._create_annotation("measurement", MprPlane.CORONAL, [first, second])
    workspace._create_annotation("angle", MprPlane.CORONAL, [first, second, third])
    workspace._create_annotation("rectangle_roi", MprPlane.CORONAL, [first, second])
    workspace._create_annotation("circle_roi", MprPlane.CORONAL, [first, second])
    workspace._create_annotation("ellipse_roi", MprPlane.CORONAL, [first, second])

    assert len(model.measurements) == 1
    assert len(model.angle_measurements) == 1
    assert len(model.rois) == 3
    assert model.measurements[0].points_lps["end"] == second.tolist()
    assert model.measurements[0].creation_plane["normal_lps"] == [0.0, 1.0, 0.0]
    overlays = workspace._annotation_overlays()
    assert len(overlays) == 5
    measurement = model.measurements[0]
    moved_end = geometry.pixel_to_patient(6, 4)
    workspace._edit_annotation(measurement.id, "end", moved_end)
    assert measurement.points_lps["end"] == moved_end.tolist()
    assert measurement.distance == np.linalg.norm(moved_end - first)
    for viewport in workspace.viewports.values():
        viewport.set_annotation_overlays(overlays)
        assert len(viewport._annotation_overlays) == 5
