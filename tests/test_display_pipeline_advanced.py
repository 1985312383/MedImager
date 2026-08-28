import numpy as np
import pytest

from medimager.core.analysis import calculate_roi_statistics
from medimager.core.dicom_parser import DicomParser
from medimager.core.image_data_model import ImageDataModel
from medimager.core.lazy_pixel_volume import LazyPixelVolume
from medimager.core.roi import RectangleROI
from tests.dicom_fixtures import make_dicom_dataset, write_dicom


def test_path_loaded_dicom_uses_lazy_frame_store_without_pixeldata(tmp_path):
    paths = []
    for index in range(4):
        dataset = make_dicom_dataset(
            np.full((4, 5), index, dtype=np.int16),
            position=[0, 0, index],
            instance_number=index + 1,
        )
        paths.append(str(write_dicom(tmp_path / f"slice-{index}.dcm", dataset)))

    parser = DicomParser()
    assert parser.load_series(paths)

    volume = parser.get_pixel_array()
    assert isinstance(volume, LazyPixelVolume)
    assert volume.shape == (4, 4, 5)
    assert int(volume[3][0, 0]) == 3
    assert all("PixelData" not in dataset for dataset in parser.get_source_datasets())
    cache = parser.get_pixel_cache_info()
    assert 0 < cache["usage_bytes"] <= cache["limit_bytes"]


def test_lazy_volume_is_array_compatible_and_byte_bounded():
    calls = []

    def decode(index):
        calls.append(index)
        return np.full((4, 4), index, dtype=np.uint8)

    volume = LazyPixelVolume(
        3,
        decode,
        cache_limit_bytes=20,
        prefetch_radius=0,
    )
    try:
        assert volume.shape == (3, 4, 4)
        assert np.array_equal(np.asarray(volume)[:, 0, 0], [0, 1, 2])
        assert volume.cache_bytes <= 20
        assert set(calls) == {0, 1, 2}
    finally:
        volume.close()


def test_rgb_dicom_decodes_as_color_volume(tmp_path):
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    rgb[..., 0] = 12
    rgb[..., 1] = 34
    rgb[..., 2] = 56
    dataset = make_dicom_dataset(
        np.zeros((2, 3), dtype=np.uint8),
        modality="US",
        bits_allocated=8,
        window_center=None,
        window_width=None,
    )
    dataset.SamplesPerPixel = 3
    dataset.PhotometricInterpretation = "RGB"
    dataset.PlanarConfiguration = 0
    dataset.PixelData = rgb.tobytes()
    path = write_dicom(tmp_path / "rgb.dcm", dataset)

    model = ImageDataModel()
    assert model.load_dicom_series([str(path)])

    assert model.image_mode == "rgb_volume"
    assert model.get_display_slice().shape == (2, 3, 3)
    assert tuple(model.get_display_slice()[0, 0]) == (12, 34, 56)


def test_imager_spacing_preserves_aspect_but_not_mm_measurement():
    model = ImageDataModel()
    assert model.load_single_image(
        np.ones((2, 2), dtype=np.float32),
        {"ImagerPixelSpacing": [0.25, 0.75]},
    )

    info = model.get_pixel_spacing_info()
    assert info.source == "ImagerPixelSpacing"
    assert not info.measurement_calibrated
    assert model.get_pixel_aspect_ratio() == 3.0
    assert model.get_measurement_pixel_spacing() is None

    stats = calculate_roi_statistics(model, RectangleROI((0, 0), (1, 1), 0))
    assert "area_mm2" not in stats


def test_padding_is_excluded_from_auto_window_and_roi_statistics():
    model = ImageDataModel()
    pixels = np.asarray([[0.0, 0.0], [100.0, 200.0]], dtype=np.float32)
    assert model.load_single_image(
        pixels,
        {"PixelPaddingValue": 0, "PixelSpacing": [1.0, 1.0]},
    )

    valid = model.get_valid_pixel_mask()
    assert valid.tolist() == [[False, False], [True, True]]
    stats = calculate_roi_statistics(model, RectangleROI((0, 0), (1, 1), 0))
    assert stats["count"] == 2
    assert stats["mean"] == pytest.approx(150.0)
    assert stats["area_mm2"] == pytest.approx(2.0)
    assert model.window_level > 100.0


def test_fractional_windows_and_all_dicom_window_options_are_preserved():
    model = ImageDataModel()
    assert model.load_single_image(
        np.arange(4, dtype=np.float32).reshape(2, 2),
        {
            "WindowCenter": [0.25, 1.75],
            "WindowWidth": [1.5, 3.25],
            "WindowCenterWidthExplanation": ["Fine", "Wide"],
        },
    )

    options = model.get_dicom_voi_options()
    assert [(item["label"], item["width"], item["center"]) for item in options] == [
        ("Fine", 1.5, 0.25),
        ("Wide", 3.25, 1.75),
    ]
    assert model.activate_dicom_voi_option(options[1])
    assert model.window_width == pytest.approx(3.25)
    assert model.window_level == pytest.approx(1.75)


def test_frame_timing_lossy_badge_and_presentation_inverse_metadata():
    model = ImageDataModel()
    assert model.load_single_image(
        np.asarray([[0.0, 100.0]], dtype=np.float32),
        {
            "FrameTime": 40.0,
            "LossyImageCompression": "01",
            "LossyImageCompressionRatio": "12.5",
            "LossyImageCompressionMethod": "ISO_10918_1",
            "PresentationLUTShape": "INVERSE",
            "PhotometricInterpretation": "MONOCHROME2",
        },
    )
    model.set_window(100.0, 50.0)

    assert model.get_frame_interval_ms() == pytest.approx(40.0)
    assert model.get_lossy_compression_info() == {
        "ratio": "12.5",
        "method": "ISO_10918_1",
    }
    assert model.get_display_slice().tolist() == [[255, 0]]
