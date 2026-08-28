from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QToolButton

from medimager.ui.main_toolbar import create_main_toolbar


class _ThemeStub:
    def create_themed_icon(self, svg_path: str) -> QIcon:
        return QIcon(svg_path)


class _ToolbarWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme_manager = _ThemeStub()
        self.selected_tools = []

    def _on_tool_selected(self, name):
        self.selected_tools.append(name)

    def _set_window_level_preset(self, *args):
        pass

    def _open_custom_wl_dialog(self):
        pass

    def _apply_viewer_transform(self, *args):
        pass

    def _set_layout(self, *args):
        pass

    def _auto_assign_all_series(self):
        pass

    def _clear_all_bindings(self):
        pass

    def _on_sync_position_changed(self, *args):
        pass

    def _on_sync_pan_changed(self, *args):
        pass

    def _on_sync_zoom_changed(self, *args):
        pass

    def _on_sync_window_level_changed(self, *args):
        pass

    def _cine_toggle_play(self):
        pass

    def _cine_set_fps(self, *args):
        pass


def test_split_buttons_reactivate_the_displayed_last_tool(qapp):
    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)
    roi_button = toolbar.findChild(QToolButton, "RoiToolButton")
    measurement_button = toolbar.findChild(QToolButton, "MeasurementToolButton")

    assert window.tool_actions["default"].isChecked()
    assert not roi_button.isChecked()
    assert not measurement_button.isChecked()

    window.tool_actions["rectangle_roi"].trigger()
    roi_button.click()
    assert window.selected_tools[-1] == "rectangle_roi"
    assert roi_button.isChecked()
    assert not measurement_button.isChecked()

    window.tool_actions["angle"].trigger()
    measurement_button.click()
    assert window.selected_tools[-1] == "angle"
    assert measurement_button.isChecked()
    assert not roi_button.isChecked()

    window.tool_actions["default"].trigger()
    assert not roi_button.isChecked()
    assert not measurement_button.isChecked()
    assert window.tool_actions["rectangle_roi"].isChecked()
    assert window.tool_actions["angle"].isChecked()
    window.close()
