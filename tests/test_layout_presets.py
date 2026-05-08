from PySide6.QtCore import QPoint

from medimager.ui.main_window import MainWindow
from medimager.ui.widgets.layout_grid_selector import LayoutDropdown


def test_vertical_split_bottom_split_uses_three_logical_views(qapp):
    window = MainWindow()
    layout_config = {
        "type": "vertical_split",
        "top_ratio": 0.6,
        "bottom_split": True,
    }

    window._set_layout(layout_config)
    qapp.processEvents()

    assert window.series_manager.get_all_view_ids() == [
        "view_0_0",
        "view_1_0",
        "view_1_1",
    ]
    assert set(window.multi_viewer_grid.get_all_view_frames()) == {
        "view_0_0",
        "view_1_0",
        "view_1_1",
    }

    binding_table = window.series_panel._binding_widget._binding_table
    assert binding_table.rowCount() == 3
    assert [binding_table.item(row, 0).text().replace(" ★", "") for row in range(3)] == [
        "1-1",
        "2-1",
        "2-2",
    ]

    window.close()
    qapp.processEvents()


def test_layout_dropdown_rethemes_preset_buttons(qapp):
    window = MainWindow()
    dropdown = LayoutDropdown(window)

    window.theme_manager.set_theme("dark")
    dropdown.show_at_position(QPoint(0, 0))
    qapp.processEvents()

    dark_styles = [button.styleSheet() for button in dropdown._preset_buttons]
    assert dark_styles
    assert all("#2B2B2B" in style or "#2b2b2b" in style for style in dark_styles)

    dropdown.hide()
    window.close()
    qapp.processEvents()
