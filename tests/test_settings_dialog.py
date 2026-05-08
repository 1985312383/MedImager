from PySide6.QtWidgets import QWidget

from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.utils.settings import SettingsManager


class ThemeManagerStub:
    def __init__(self, settings_manager: SettingsManager):
        self.settings_manager = settings_manager
        self.current_theme = settings_manager.get_setting("ui_theme", "dark")

    def get_current_theme(self):
        return self.current_theme

    def set_theme(self, theme_name: str):
        self.current_theme = theme_name
        self.settings_manager.set_setting("ui_theme", theme_name)


class SettingsParent(QWidget):
    def __init__(self, settings_manager: SettingsManager):
        super().__init__()
        self.theme_manager = ThemeManagerStub(settings_manager)


def test_settings_dialog_keeps_selected_roi_theme_preview(qapp):
    settings = SettingsManager(use_json=True)
    settings.set_setting("roi_theme", "radiant")

    dialog = SettingsDialog(settings)
    qapp.processEvents()

    assert dialog.setting_widgets["roi.custom.border_color"].color().name().lower() == "#00b050"
    assert dialog.setting_widgets["roi.custom.info_bg_color"].color().name().lower() == "#4a241e"
    assert dialog.setting_widgets["roi.custom.info_selected_bg_color"].color().name().lower() == "#b83a3a"
    assert not dialog.setting_widgets["roi.custom.info_bg_color"].isEnabled()

    dialog.close()


def test_settings_dialog_cancel_restores_previewed_ui_theme(qapp):
    settings = SettingsManager(use_json=True)
    settings.set_setting("ui_theme", "dark")
    parent = SettingsParent(settings)
    dialog = SettingsDialog(settings, parent)

    ui_combo = dialog.setting_widgets["ui_theme"]
    light_index = ui_combo.findData("light")
    assert light_index != -1

    ui_combo.setCurrentIndex(light_index)
    assert parent.theme_manager.get_current_theme() == "light"

    dialog.reject()

    assert parent.theme_manager.get_current_theme() == "dark"
    assert settings.get_setting("ui_theme") == "dark"

    parent.close()


def test_settings_dialog_saves_workflow_settings(qapp):
    settings = SettingsManager(use_json=True)
    dialog = SettingsDialog(settings)

    dialog.setting_widgets["interaction.left_drag_action"].setCurrentIndex(
        dialog.setting_widgets["interaction.left_drag_action"].findData("window")
    )
    dialog.setting_widgets["display.smooth_interpolation"].setChecked(False)
    dialog.setting_widgets["dicom.recursive_scan"].setChecked(False)
    dialog.setting_widgets["roi.stats.area_unit"].setCurrentIndex(
        dialog.setting_widgets["roi.stats.area_unit"].findData("cm2")
    )
    dialog.setting_widgets["multiview.default_layout"].setCurrentIndex(
        dialog.setting_widgets["multiview.default_layout"].findData("2x2")
    )
    dialog.setting_widgets["cine.default_fps"].setValue(24)

    dialog.accept()

    assert settings.get_setting("interaction.left_drag_action") == "window"
    assert settings.get_setting("display.smooth_interpolation") is False
    assert settings.get_setting("dicom.recursive_scan") is False
    assert settings.get_setting("roi.stats.area_unit") == "cm2"
    assert settings.get_setting("multiview.default_layout") == "2x2"
    assert settings.get_setting("cine.default_fps") == 24
