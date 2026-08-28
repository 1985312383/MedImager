import numpy as np

from medimager.core.image_data_model import ImageDataModel
from medimager.utils.settings import get_settings_manager


def test_rgb_image_loads_as_single_rgb_slice():
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgb[..., 0] = 255
    model = ImageDataModel()

    assert model.load_single_image(rgb)

    assert model.image_mode == "rgb_image"
    assert model.get_slice_count() == 1
    assert model.pixel_array.shape == (1, 4, 5, 3)
    assert model.get_display_slice().shape == (4, 5, 3)


def test_rgb_pixel_value_returns_channel_tuple():
    rgb = np.zeros((3, 4, 3), dtype=np.uint8)
    rgb[1, 2] = [12, 34, 56]
    model = ImageDataModel()

    assert model.load_single_image(rgb)

    assert model.get_pixel_value(2, 1) == (12.0, 34.0, 56.0)


def test_rgba_image_loads_as_single_rgb_slice_with_alpha():
    rgba = np.zeros((4, 5, 4), dtype=np.uint8)
    rgba[..., 3] = 128
    model = ImageDataModel()

    assert model.load_single_image(rgba)

    assert model.image_mode == "rgb_image"
    assert model.get_slice_count() == 1
    assert model.pixel_array.shape == (1, 4, 5, 4)
    assert model.get_display_slice().shape == (4, 5, 4)


def test_grayscale_image_uses_grayscale_display_path():
    grayscale = np.arange(20, dtype=np.float32).reshape(4, 5)
    model = ImageDataModel()

    assert model.load_single_image(grayscale)

    assert model.image_mode == "grayscale_volume"
    assert model.get_slice_count() == 1
    assert model.pixel_array.shape == (1, 4, 5)
    assert model.get_display_slice().shape == (4, 5)


def test_3d_non_rgb_array_remains_grayscale_volume():
    volume = np.zeros((3, 4, 5), dtype=np.float32)
    model = ImageDataModel()

    assert model.load_single_image(volume)

    assert model.image_mode == "grayscale_volume"
    assert model.get_slice_count() == 3
    assert model.pixel_array.shape == (3, 4, 5)


def test_window_level_strategy_fixed_uses_400_40():
    settings = get_settings_manager()
    previous = settings.get_setting("display.window_level_strategy", "dicom")
    settings.set_setting("display.window_level_strategy", "fixed")

    try:
        model = ImageDataModel()
        assert model.load_single_image(np.arange(100, dtype=np.float32).reshape(10, 10))
    finally:
        settings.set_setting("display.window_level_strategy", previous)

    assert model.window_width == 400
    assert model.window_level == 40
