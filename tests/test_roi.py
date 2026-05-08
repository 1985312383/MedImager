import numpy as np
import pytest

from medimager.core.analysis import calculate_roi_statistics
from medimager.core.image_data_model import ImageDataModel
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI
from medimager.ui.widgets.roi_stats_box import get_stats_text
from medimager.utils.settings import get_settings_manager


def make_model(pixel_spacing=None):
    data = np.arange(100, dtype=np.float32).reshape(10, 10)
    model = ImageDataModel()
    metadata = {}
    if pixel_spacing is not None:
        metadata["PixelSpacing"] = pixel_spacing
    assert model.load_single_image(data, metadata)
    return model


@pytest.mark.parametrize(
    "roi",
    [
        RectangleROI((1, 1), (3, 4), 0),
        CircleROI((5, 5), 2, 0),
        EllipseROI((5, 5), 3, 2, 0),
    ],
)
def test_roi_statistics_include_pixel_area(roi):
    model = make_model()
    expected_count = int(np.sum(roi.get_mask(10, 10)))

    stats = calculate_roi_statistics(model, roi)

    assert stats["count"] == expected_count
    assert stats["area_px"] == float(expected_count)
    assert "area_mm2" not in stats


def test_roi_statistics_include_mm2_area_when_pixel_spacing_exists():
    model = make_model(pixel_spacing=[0.5, 2.0])
    roi = RectangleROI((0, 0), (1, 2), 0)

    stats = calculate_roi_statistics(model, roi)

    assert stats["count"] == 6
    assert stats["area_px"] == 6.0
    assert stats["area_mm2"] == 6.0


def test_roi_statistics_ignore_malformed_pixel_spacing():
    model = make_model(pixel_spacing=0.5)
    roi = RectangleROI((0, 0), (1, 2), 0)

    stats = calculate_roi_statistics(model, roi)

    assert stats["count"] == 6
    assert stats["area_px"] == 6.0
    assert "area_mm2" not in stats


def test_empty_roi_returns_none():
    model = make_model()
    roi = RectangleROI((0, 0), (1, 1), 5)

    assert calculate_roi_statistics(model, roi) is None


def test_radiant_roi_stats_text_uses_compact_cm2_format():
    settings = get_settings_manager()
    previous_theme = settings.get_setting("roi_theme", "default")
    settings.set_setting("roi_theme", "radiant")

    try:
        text = get_stats_text(
            {
                "mean": 251.83,
                "std": 26.06,
                "max": 319.0,
                "min": 181.0,
                "count": 212,
                "area_px": 212.0,
                "area_mm2": 120.0,
            }
        )
    finally:
        settings.set_setting("roi_theme", previous_theme)

    assert text == "Mean=251.83 SD=26.06\nMax=319 Min=181\nArea=1.2 cm² (212 px)"
