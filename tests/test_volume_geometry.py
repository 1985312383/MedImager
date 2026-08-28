from __future__ import annotations

import numpy as np
import pytest
from pydicom.dataset import Dataset

from medimager.core.render_pipeline import RenderRequest, render_frame
from medimager.core.volume_geometry import (
    GeometryStatus,
    MprPlane,
    OrthogonalMprResampler,
    VolumeBuilder,
    VolumeGeometry,
)


class _Model:
    def __init__(
        self,
        positions,
        *,
        orientation=(1, 0, 0, 0, 1, 0),
        spacing=(2.0, 1.0),
        modality="CT",
        temporal=None,
        stack=None,
    ):
        self.image_mode = "grayscale_volume"
        self.pixel_array = np.stack(
            [np.full((4, 5), index, dtype=np.float32) for index in range(len(positions))]
        )
        self.datasets = []
        for index, position in enumerate(positions):
            ds = Dataset()
            ds.Modality = modality
            ds.Rows = 4
            ds.Columns = 5
            ds.ImagePositionPatient = list(position)
            ds.ImageOrientationPatient = list(orientation)
            ds.PixelSpacing = list(spacing)
            ds.FrameOfReferenceUID = "1.2.3"
            ds.SeriesInstanceUID = "1.2.3.4"
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            if temporal is not None:
                ds.TemporalPositionIndex = temporal[index]
            if stack is not None:
                ds.StackID = stack[index]
            self.datasets.append(ds)

    def get_slice_count(self):
        return len(self.datasets)

    def get_metadata(self, key, default=None):
        return getattr(self.datasets[0], key, default)

    def get_dicom_file(self, index):
        return self.datasets[index]

    def get_image_shape(self):
        return self.pixel_array.shape

    def get_slice_data(self, index):
        return self.pixel_array[index]


def test_volume_geometry_affine_round_trip():
    geometry = VolumeGeometry(
        origin_lps=(10.0, -4.0, 2.0),
        direction=(0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        spacing_xyz=(0.5, 0.75, 2.0),
        shape_zyx=(8, 6, 5),
        frame_of_reference_uid="1.2.3",
        source_frame_indices=tuple(range(8)),
    )
    voxel = np.array([2.25, 3.5, 4.75])
    patient = geometry.voxel_to_patient(*voxel)
    assert np.allclose(geometry.patient_to_voxel(patient), voxel)


def test_builder_creates_regular_float_volume_and_sorts_positions():
    model = _Model([(0, 0, 4), (0, 0, 0), (0, 0, 2)])
    result = VolumeBuilder.build(model)
    assert result.status is GeometryStatus.COMPATIBLE
    assert result.volume is not None
    assert result.volume.pixels_zyx.dtype == np.float32
    assert result.volume.geometry.spacing_xyz == (1.0, 2.0, 2.0)
    assert result.volume.geometry.source_frame_indices == (1, 2, 0)
    assert np.all(result.volume.pixels_zyx[:, 0, 0] == [1, 2, 0])


@pytest.mark.parametrize(
    ("positions", "expected"),
    [
        ([(0, 0, 0), (0, 0, 0), (0, 0, 1)], GeometryStatus.DUPLICATE_SLICES),
        ([(0, 0, 0), (0, 0, 1), (0, 0, 3)], GeometryStatus.NON_UNIFORM_SPACING),
        ([(0, 0, 0), (0.2, 0, 1), (0.4, 0, 2)], GeometryStatus.GANTRY_TILT),
    ],
)
def test_builder_rejects_unsafe_slice_geometry(positions, expected):
    assert VolumeBuilder.inspect(_Model(positions)).status is expected


def test_builder_rejects_temporal_and_stack_mixing():
    positions = [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
    assert (
        VolumeBuilder.inspect(_Model(positions, temporal=[1, 2, 1])).status
        is GeometryStatus.MULTI_TEMPORAL
    )
    assert (
        VolumeBuilder.inspect(_Model(positions, stack=["A", "B", "A"])).status
        is GeometryStatus.MULTI_STACK
    )


def test_builder_accepts_regular_oblique_geometry():
    root = np.sqrt(0.5)
    orientation = (root, root, 0, -root, root, 0)
    result = VolumeBuilder.inspect(
        _Model([(0, 0, 0), (0, 0, 1), (0, 0, 2)], orientation=orientation)
    )
    assert result.status is GeometryStatus.COMPATIBLE


def test_render_request_is_deterministic_and_inverts_without_mutation():
    pixels = np.asarray([[0.0, 50.0, 100.0]], dtype=np.float32)
    before = pixels.copy()
    normal = render_frame(RenderRequest(pixels, 100, 50)).pixels_uint8
    inverse = render_frame(RenderRequest(pixels, 100, 50, inverted=True)).pixels_uint8
    assert np.array_equal(pixels, before)
    assert np.array_equal(inverse, 255 - normal)


def test_simpleitk_reconstruction_keeps_patient_cursor_on_each_plane():
    pytest.importorskip("SimpleITK")
    result = VolumeBuilder.build(_Model([(0, 0, 0), (0, 0, 2), (0, 0, 4)]))
    resampler = OrthogonalMprResampler(result.volume)
    cursor = result.volume.geometry.center_lps
    for plane in MprPlane:
        reconstruction = resampler.reconstruct(plane, cursor)
        x, y = reconstruction.geometry.patient_to_pixel(cursor)
        round_trip = reconstruction.geometry.pixel_to_patient(x, y)
        delta = np.asarray(cursor) - round_trip
        normal = np.asarray(reconstruction.geometry.normal_lps)
        assert np.linalg.norm(delta - normal * np.dot(delta, normal)) < 1e-6



def test_builder_rejects_missing_or_mixed_frame_of_reference():
    positions = [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
    missing = _Model(positions)
    del missing.datasets[1].FrameOfReferenceUID
    assert VolumeBuilder.inspect(missing).status is GeometryStatus.MISSING_GEOMETRY

    mixed = _Model(positions)
    mixed.datasets[1].FrameOfReferenceUID = "9.8.7"
    assert (
        VolumeBuilder.inspect(mixed).status
        is GeometryStatus.INCONSISTENT_FRAME_OF_REFERENCE
    )


def test_builder_rejects_rgb_metadata_even_when_model_mode_is_stale():
    model = _Model([(0, 0, 0), (0, 0, 1)])
    for dataset in model.datasets:
        dataset.SamplesPerPixel = 3
        dataset.PhotometricInterpretation = "RGB"
    assert VolumeBuilder.inspect(model).status is GeometryStatus.COLOR
