import logging

import numpy as np
import pytest

from medimager.core.dicom_parser import DicomParser
from tests.dicom_fixtures import make_dicom_dataset, write_dicom


@pytest.mark.parametrize(
    "modality,bits_allocated,photometric,pixel_spacing,slope,intercept,window_center,window_width",
    [
        ("CT", 16, "MONOCHROME2", [0.7, 0.7], 2.0, -1024.0, 40.0, 400.0),
        ("MR", 16, "MONOCHROME2", [0.9, 0.9], 1.0, 0.0, 500.0, 1000.0),
        ("CR", 16, "MONOCHROME1", [0.14, 0.14], 1.0, 0.0, 2048.0, 4096.0),
        ("US", 8, "MONOCHROME2", [0.3, 0.3], 1.0, 0.0, 128.0, 255.0),
        ("PT", 16, "MONOCHROME2", [2.0, 2.0], 0.5, 0.0, 5.0, 10.0),
    ],
)
def test_synthetic_modality_fixtures_load_metadata_and_pixels(
    modality,
    bits_allocated,
    photometric,
    pixel_spacing,
    slope,
    intercept,
    window_center,
    window_width,
    tmp_path,
):
    dtype = np.uint8 if bits_allocated == 8 else np.int16
    raw = np.full((3, 4), 10, dtype=dtype)
    ds = make_dicom_dataset(
        raw,
        modality=modality,
        bits_allocated=bits_allocated,
        photometric=photometric,
        pixel_spacing=pixel_spacing,
        slope=slope,
        intercept=intercept,
        window_center=window_center,
        window_width=window_width,
    )
    path = write_dicom(tmp_path / f"{modality}.dcm", ds)

    parser = DicomParser()

    assert parser.load_series([str(path)])
    assert parser.get_pixel_array().shape == (1, 3, 4)
    assert np.all(parser.get_pixel_array()[0] == raw.astype(np.float32) * slope + intercept)
    metadata = parser.get_metadata()
    assert metadata["Modality"] == modality
    assert metadata["PhotometricInterpretation"] == photometric
    assert [float(v) for v in metadata["PixelSpacing"]] == pixel_spacing
    assert float(metadata["WindowCenter"]) == window_center
    assert float(metadata["WindowWidth"]) == window_width


def test_reverse_file_order_uses_patient_space_sorting(tmp_path):
    orientation = [1, 0, 0, 0, 1, 0]
    paths = []
    for value, z in [(0, 0), (10, 1), (20, 2)]:
        ds = make_dicom_dataset(
            np.full((2, 2), value, dtype=np.int16),
            orientation=orientation,
            position=[0, 0, z],
            instance_number=3 - value // 10,
        )
        paths.append(write_dicom(tmp_path / f"slice_{value}.dcm", ds))

    parser = DicomParser()

    assert parser.load_series([str(path) for path in reversed(paths)])
    assert [int(frame[0, 0]) for frame in parser.get_pixel_array()] == [0, 10, 20]


def test_non_axial_orientation_uses_projection_sorting(tmp_path):
    orientation = [0, 1, 0, 0, 0, 1]  # normal points along patient X
    paths = []
    for value, x in [(20, 2), (0, 0), (10, 1)]:
        ds = make_dicom_dataset(
            np.full((2, 2), value, dtype=np.int16),
            orientation=orientation,
            position=[x, 0, 0],
        )
        paths.append(write_dicom(tmp_path / f"oblique_{value}.dcm", ds))

    parser = DicomParser()

    assert parser.load_series([str(path) for path in paths])
    assert [int(frame[0, 0]) for frame in parser.get_pixel_array()] == [0, 10, 20]


def test_missing_patient_position_falls_back_to_instance_number(tmp_path):
    paths = []
    for value, instance_number in [(20, 3), (0, 1), (10, 2)]:
        ds = make_dicom_dataset(
            np.full((2, 2), value, dtype=np.int16),
            position=None,
            instance_number=instance_number,
        )
        paths.append(write_dicom(tmp_path / f"missing_position_{value}.dcm", ds))

    parser = DicomParser()

    assert parser.load_series([str(path) for path in paths])
    assert [int(frame[0, 0]) for frame in parser.get_pixel_array()] == [0, 10, 20]


def test_inconsistent_pixel_spacing_warns_but_loads(caplog):
    parser = DicomParser()
    datasets = [
        make_dicom_dataset(np.zeros((2, 2), dtype=np.int16), position=[0, 0, 0], pixel_spacing=[0.5, 0.5]),
        make_dicom_dataset(np.ones((2, 2), dtype=np.int16), position=[0, 0, 1], pixel_spacing=[0.8, 0.5]),
    ]

    with caplog.at_level(logging.WARNING, logger="medimager.core.dicom_parser"):
        sorted_sets = parser._sort_dicom_slices(datasets)

    assert len(sorted_sets) == 2
    assert "Inconsistent PixelSpacing" in caplog.text


def test_single_file_multiframe_grayscale_expands_to_volume(tmp_path):
    raw = np.arange(12, dtype=np.int16).reshape(3, 2, 2)
    ds = make_dicom_dataset(raw)
    path = write_dicom(tmp_path / "multiframe.dcm", ds)

    parser = DicomParser()

    assert parser.load_series([str(path)])
    assert parser.get_pixel_array().shape == (3, 2, 2)
    assert np.array_equal(parser.get_pixel_array(), raw.astype(np.float32))
