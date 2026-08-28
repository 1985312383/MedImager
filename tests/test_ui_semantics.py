from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from medimager.ui.panels.dicom_tag_panel import DicomTagPanel
from medimager.ui.widgets.layout_grid_selector import DynamicLayoutSelector
from medimager.ui.widgets.panel_toggle_strip import PanelToggleStrip
from medimager.utils.icon_registry import ICON_FILES
from medimager.utils.theme_manager import MEDICAL_CANVAS_COLOR, normalize_ui_theme


class _MemorySettings:
    def __init__(self):
        self.values = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class _SettingsParent(QWidget):
    def __init__(self):
        super().__init__()
        self.settings_manager = _MemorySettings()


def test_legacy_ui_theme_expands_to_semantic_tokens_and_neutral_canvas():
    tokens = normalize_ui_theme(
        {
            "background_color": "#FAFAFA",
            "text_color": "#111111",
            "highlight_color": "#0063B1",
            "border_color": "#CCCCCC",
            "canvas_color": "#FFFFFF",
        }
    )

    required = {
        "window_color",
        "surface_color",
        "surface_raised_color",
        "surface_sunken_color",
        "text_secondary_color",
        "text_disabled_color",
        "focus_color",
        "success_color",
        "warning_color",
        "error_color",
        "annotation_color",
        "measurement_color",
        "reference_line_color",
    }
    assert required <= tokens.keys()
    assert tokens["canvas_color"] == MEDICAL_CANVAS_COLOR


def test_registered_icons_follow_the_24px_current_color_contract():
    icons_dir = Path("medimager/icons")
    for semantic_name, filename in ICON_FILES.items():
        path = icons_dir / filename
        assert path.is_file(), semantic_name
        source = path.read_text(encoding="utf-8")
        root = ET.fromstring(source)
        assert root.attrib.get("viewBox") == "0 0 24 24", semantic_name
        assert "currentColor" in source, semantic_name


def test_dicom_tag_panel_defaults_to_compact_columns_and_remembers_advanced(qapp):
    parent = _SettingsParent()
    panel = DicomTagPanel(parent)

    assert not panel.tree_widget.isColumnHidden(panel.TAG_COLUMN)
    assert panel.tree_widget.isColumnHidden(panel.KEYWORD_COLUMN)
    assert not panel.tree_widget.isColumnHidden(panel.NAME_COLUMN)
    assert panel.tree_widget.isColumnHidden(panel.VR_COLUMN)
    assert not panel.tree_widget.isColumnHidden(panel.VALUE_COLUMN)

    panel._advanced_actions[panel.KEYWORD_COLUMN].setChecked(True)
    assert not panel.tree_widget.isColumnHidden(panel.KEYWORD_COLUMN)
    assert parent.settings_manager.values["dicom_tags.column_1_visible"] is True
    panel.close()
    parent.close()


def test_panel_toggle_is_keyboard_reachable_and_has_28px_target(qapp):
    strip = PanelToggleStrip("right", "Metadata")
    spy = QSignalSpy(strip.toggled)
    strip.show()
    strip.setFocus()

    QTest.keyClick(strip, Qt.Key.Key_Space)

    assert strip.width() == 28
    assert strip.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert strip.accessibleName() == "Metadata"
    assert spy.count() == 1
    assert spy.at(0)[0] is True
    strip.close()


def test_dynamic_layout_grid_supports_arrow_and_enter_keys(qapp):
    selector = DynamicLayoutSelector(max_rows=3, max_cols=4)
    spy = QSignalSpy(selector.layout_selected)
    selector.show()
    selector.grid_widget.setFocus()
    qapp.processEvents()

    QTest.keyClick(selector.grid_widget, Qt.Key.Key_Right)
    QTest.keyClick(selector.grid_widget, Qt.Key.Key_Down)
    QTest.keyClick(selector.grid_widget, Qt.Key.Key_Return)

    assert (selector.hovered_rows, selector.hovered_cols) == (2, 2)
    assert spy.count() == 1
    assert tuple(spy.at(0)) == (2, 2)
    selector.close()
