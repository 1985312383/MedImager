import numpy as np

from medimager.core.image_data_model import ImageDataModel


def test_rgb_image_loads_as_single_rgb_slice():
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgb[..., 0] = 255
    model = ImageDataModel()

    assert model.load_single_image(rgb)

    assert model.image_mode == "rgb_image"
    assert model.get_slice_count() == 1
    assert model.pixel_array.shape == (1, 4, 5, 3)
    assert model.get_display_slice().shape == (4, 5, 3)


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
