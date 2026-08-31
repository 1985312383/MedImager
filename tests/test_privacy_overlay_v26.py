from medimager.core.multi_series_manager import MultiSeriesManager, ViewPosition
from medimager.ui.image_viewer import ImageViewer
from medimager.ui.multi_viewer_grid import MultiViewerGrid, ViewFrame


class _Settings:
    def __init__(self, values):
        self.values = values

    def get_setting(self, key, default=None):
        return self.values.get(key, default)


def test_image_viewer_runtime_overlay_controls_are_real(qapp):
    viewer = ImageViewer()
    viewer.settings_manager = _Settings(
        {
            "overlay.show_orientation": False,
            "overlay.show_slice_position": False,
            "overlay.show_scale": False,
            "overlay.show_patient": False,
            "overlay.show_pixel_value": True,
        }
    )

    viewer.apply_runtime_settings()

    assert viewer._overlay_options == {
        "orientation": False,
        "slice_position": False,
        "scale": False,
        "patient": False,
        "pixel_value": True,
    }


def test_view_frame_privacy_alias_replaces_title_and_corner_overlay(qapp):
    frame = ViewFrame("view_1", ViewPosition.TOP_LEFT)
    frame._series_id = "raw-series-uid"
    frame._series_info = "Patient Name - CT"

    frame.set_privacy_mode(True, "Series 01")
    assert frame._series_label.text() == "Series 01"
    assert frame.image_viewer._corner_overlay_info["title"] == "Series 01"

    frame.set_privacy_mode(False)
    assert frame._series_label.text() == "Patient Name - CT"


def test_grid_privacy_aliases_are_stable_for_the_session(qapp):
    grid = MultiViewerGrid(MultiSeriesManager())
    assert grid._privacy_alias_for("series-a") == "Series 01"
    assert grid._privacy_alias_for("series-b") == "Series 02"
    assert grid._privacy_alias_for("series-a") == "Series 01"
