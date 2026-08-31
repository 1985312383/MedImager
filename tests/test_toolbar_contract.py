from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
import re

import pytest
from PySide6.QtWidgets import QLabel, QSpinBox, QToolButton

from medimager.ui.main_toolbar import create_main_toolbar
from medimager.utils.i18n import get_translation_manager, t
from tests.test_main_toolbar import _ToolbarWindow


def _dock_toolbar(window, toolbar, area, qapp) -> None:
    window.addToolBar(area, toolbar)
    window.show()
    qapp.processEvents()


def _visible_action_hosts(toolbar):
    """Return real toolbar layout items, excluding separators/overflow chrome."""

    hosts = []
    for action in toolbar.actions():
        if action.isSeparator() or not action.isVisible():
            continue
        host = toolbar.widgetForAction(action)
        if host is not None and host.isVisibleTo(toolbar):
            hosts.append((action, host))
    return hosts


def _toolbar_point(widget, toolbar):
    return widget.mapTo(toolbar, widget.rect().center())


def _toolbar_buttons(toolbar, window):
    buttons = []
    for _action, host in _visible_action_hosts(toolbar):
        control = host if isinstance(host, QToolButton) else getattr(host, "child", None)
        if isinstance(control, QToolButton):
            buttons.append(control)
    play_button = window._cine_play_btn
    if play_button.isVisibleTo(toolbar) and play_button not in buttons:
        buttons.append(play_button)
    return buttons


def test_toolbar_exposes_interaction_view_voi_sync_and_fps_contract(qapp):
    window = _ToolbarWindow()
    window._cine_fps = 18
    toolbar = create_main_toolbar(window)
    interaction_spy = QSignalSpy(toolbar.interaction_mode_requested)
    command_spy = QSignalSpy(toolbar.viewer_command_requested)
    voi_spy = QSignalSpy(toolbar.voi_option_requested)

    window.tool_actions["pan"].trigger()
    fit_action = next(
        action for action in toolbar.actions()
        if action.property("shortcutHint") == "F"
    )
    fit_action.trigger()

    window_level_button = next(
        button for button in toolbar.findChildren(QToolButton)
        if hasattr(button, "_dicom_voi_actions")
    )
    option = {"kind": "window", "index": 1, "label": "Soft tissue"}
    toolbar.set_dicom_voi_options([option], active_index=0)
    window_level_button._dicom_voi_actions[0].trigger()

    assert interaction_spy.at(0)[0] == "pan"
    assert command_spy.at(0)[0] == "fit"
    assert voi_spy.at(0)[0] == option
    assert window._cine_fps_spin.value() == 18
    assert toolbar.reference_lines_action.isCheckable()
    assert toolbar.shared_cursor_action.isCheckable()
    assert (
        toolbar.reference_lines_action.property("toolbarGroup")
        == "compare"
    )
    toolbar.set_cine_fps(24)
    assert window._cine_fps_spin.value() == 24

    toolbar.sync_button.set_sync_states("none", False, False, False)
    assert toolbar.sync_button.property("syncState") == "off"
    toolbar.sync_button.set_sync_states("both", True, True, True)
    assert toolbar.sync_button.property("syncState") == "all"
    window.close()


def test_toolbar_applies_group_order_visibility_labels_and_icon_size(qapp):
    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)

    toolbar.apply_preferences(
        density="comfortable",
        icon_size=30,
        show_labels=True,
        visible_groups=("browse", "advanced"),
        group_order=("advanced", "browse", "measure", "compare"),
    )

    assert toolbar.iconSize() == QSize(30, 30)
    assert toolbar.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert toolbar.property("groupOrder") == "advanced,browse,measure,compare"
    assert toolbar.property("visibleGroups") == "advanced,browse"
    assert any(
        action.isVisible()
        for action in toolbar._group_actions["advanced"]
    )
    assert all(
        not action.isVisible()
        for action in toolbar._group_actions["measure"]
    )

    window.tool_actions["pan"].trigger()
    chip = toolbar.findChild(QLabel, "ActiveToolChip")
    assert chip is not None
    assert chip.text()
    window.close()


def test_active_tool_chip_shows_canonical_icon_name_and_shortcut(qapp):
    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)
    name = toolbar.findChild(QLabel, "ActiveToolChip")
    icon = toolbar.findChild(QLabel, "ActiveToolChipIcon")
    shortcut = toolbar.findChild(QLabel, "ActiveToolShortcutHint")

    assert name is not None
    assert icon is not None and icon.pixmap() is not None
    assert not icon.pixmap().isNull()
    assert shortcut is not None
    assert name.text() == window.tool_actions["default"].text()
    assert shortcut.text() == "P"

    window.tool_actions["pan"].trigger()

    assert name.text() == window.tool_actions["pan"].text()
    assert shortcut.text() == "H"
    assert toolbar.active_tool_chip.property("activeTool") == "pan"
    assert toolbar.active_tool_chip.property("shortcutHint") == "H"
    assert not icon.pixmap().isNull()
    assert "H" in toolbar.active_tool_chip.toolTip()

    toolbar.set_active_tool_feedback("window_level")
    assert shortcut.text() == "W"
    assert not icon.pixmap().isNull()
    window.close()


def test_icon_only_toolbar_tiles_stay_square_and_uniform_across_dock_orientations(
    qapp,
):
    """Split/menu buttons must not grow wider than the ordinary tool tile."""

    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)
    toolbar.apply_preferences(
        density="compact",
        icon_size=24,
        show_labels=False,
        visible_groups=("browse", "measure", "compare", "advanced"),
    )

    cases = (
        (Qt.ToolBarArea.TopToolBarArea, Qt.Orientation.Horizontal, (2400, 800)),
        (Qt.ToolBarArea.LeftToolBarArea, Qt.Orientation.Vertical, (500, 1800)),
        (Qt.ToolBarArea.TopToolBarArea, Qt.Orientation.Horizontal, (2400, 800)),
    )
    try:
        for area, expected_orientation, size in cases:
            window.resize(*size)
            _dock_toolbar(window, toolbar, area, qapp)

            assert toolbar.orientation() is expected_orientation
            buttons = _toolbar_buttons(toolbar, window)
            assert len(buttons) >= 16

            actual_sizes = {(button.width(), button.height()) for button in buttons}
            assert len(actual_sizes) == 1, {
                button.toolTip(): button.size().toTuple() for button in buttons
            }
            (extent_width, extent_height), = actual_sizes
            assert extent_width == extent_height

            split_buttons = [
                button
                for button in buttons
                if bool(button.property("splitDropdown"))
            ]
            assert len(split_buttons) == 3
            assert all(
                button.size().toTuple() == (extent_width, extent_height)
                for button in split_buttons
            )
            assert all(
                button.popupMode()
                is QToolButton.ToolButtonPopupMode.DelayedPopup
                for button in split_buttons
            )
    finally:
        window.close()


def test_square_split_button_keeps_main_action_and_internal_menu_hotspot(qapp):
    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)
    try:
        window.resize(1400, 600)
        _dock_toolbar(window, toolbar, Qt.ToolBarArea.TopToolBarArea, qapp)
        roi_button = toolbar.findChild(QToolButton, "RoiToolButton")
        menu = roi_button.menu()
        menu_spy = QSignalSpy(menu.aboutToShow)

        window.tool_actions["rectangle_roi"].trigger()
        window.selected_tools.clear()
        QTest.mouseClick(
            roi_button,
            Qt.MouseButton.LeftButton,
            pos=QPoint(4, roi_button.height() // 2),
        )
        assert window.selected_tools == ["rectangle_roi"]
        assert menu_spy.count() == 0

        window.selected_tools.clear()
        QTimer.singleShot(0, menu.close)
        QTest.mousePress(
            roi_button,
            Qt.MouseButton.LeftButton,
            pos=QPoint(roi_button.width() - 2, roi_button.height() // 2),
        )
        QTest.mouseRelease(
            roi_button,
            Qt.MouseButton.LeftButton,
            pos=QPoint(roi_button.width() - 2, roi_button.height() // 2),
        )
        assert menu_spy.count() == 1
        assert window.selected_tools == []
    finally:
        window.close()


def test_toolbar_composites_reflow_and_all_action_hosts_align_when_dock_rotates(qapp):
    """A vertical toolbar must not mix centered action buttons with left-aligned widgets."""

    window = _ToolbarWindow()
    toolbar = create_main_toolbar(window)
    toolbar.apply_preferences(
        density="compact",
        icon_size=24,
        show_labels=False,
        visible_groups=("browse", "measure", "compare", "advanced"),
    )

    try:
        window.resize(2400, 800)
        _dock_toolbar(
            window,
            toolbar,
            Qt.ToolBarArea.TopToolBarArea,
            qapp,
        )
        horizontal_hosts = [host for _action, host in _visible_action_hosts(toolbar)]
        horizontal_y = [_toolbar_point(host, toolbar).y() for host in horizontal_hosts]
        assert max(horizontal_y) - min(horizontal_y) <= 1

        chip = toolbar.active_tool_chip
        natural_chip_width = max(chip.minimumWidth(), chip.sizeHint().width())
        assert chip.width() <= natural_chip_width + 1

        cine_host = next(
            host
            for host in horizontal_hosts
            if host.findChild(QSpinBox) is window._cine_fps_spin
        )
        play_center = _toolbar_point(window._cine_play_btn, cine_host)
        fps_center = _toolbar_point(window._cine_fps_spin, cine_host)
        assert abs(play_center.y() - fps_center.y()) <= 1
        assert play_center.x() < fps_center.x()

        window.resize(500, 1800)
        _dock_toolbar(
            window,
            toolbar,
            Qt.ToolBarArea.LeftToolBarArea,
            qapp,
        )
        assert toolbar.orientation() is Qt.Orientation.Vertical
        vertical_hosts = [host for _action, host in _visible_action_hosts(toolbar)]
        vertical_x = [_toolbar_point(host, toolbar).x() for host in vertical_hosts]
        assert max(vertical_x) - min(vertical_x) <= 1

        cine_host = next(
            host
            for host in vertical_hosts
            if host.findChild(QSpinBox) is window._cine_fps_spin
        )
        play_center = _toolbar_point(window._cine_play_btn, cine_host)
        fps_center = _toolbar_point(window._cine_fps_spin, cine_host)
        assert abs(play_center.x() - fps_center.x()) <= 1
        assert play_center.y() < fps_center.y()
        assert _toolbar_point(chip, toolbar).x() == vertical_x[0]
    finally:
        window.close()


@pytest.mark.parametrize(
    "language",
    ("en_US", "zh_CN", "de_DE", "es_ES", "fr_FR"),
)
def test_toolbar_text_mode_uses_one_localized_label_strategy_in_both_orientations(
    language,
    qapp,
):
    """Custom widget actions must follow the same label policy as QAction buttons."""

    manager = get_translation_manager()
    original_language = manager.current_language()
    window = None
    try:
        assert manager.set_language(language)
        window = _ToolbarWindow()
        toolbar = create_main_toolbar(window)
        toolbar.apply_preferences(
            density="compact",
            icon_size=24,
            show_labels=True,
            visible_groups=("browse", "measure", "compare", "advanced"),
        )

        window.resize(4200, 900)
        _dock_toolbar(
            window,
            toolbar,
            Qt.ToolBarArea.TopToolBarArea,
            qapp,
        )
        horizontal_buttons = _toolbar_buttons(toolbar, window)
        assert all(button.text().strip() for button in horizontal_buttons)
        assert {
            button.toolButtonStyle() for button in horizontal_buttons
        } == {Qt.ToolButtonStyle.ToolButtonTextBesideIcon}

        window.resize(900, 3000)
        _dock_toolbar(
            window,
            toolbar,
            Qt.ToolBarArea.LeftToolBarArea,
            qapp,
        )
        vertical_buttons = _toolbar_buttons(toolbar, window)
        assert all(button.text().strip() for button in vertical_buttons)
        assert {
            button.toolButtonStyle() for button in vertical_buttons
        } == {Qt.ToolButtonStyle.ToolButtonTextUnderIcon}
    finally:
        if window is not None:
            window.close()
        manager.set_language(original_language)


@pytest.mark.parametrize(
    "language",
    ("en_US", "zh_CN", "de_DE", "es_ES", "fr_FR"),
)
def test_toolbar_copy_hierarchy_is_localized_and_accessible(language, qapp):
    manager = get_translation_manager()
    original_language = manager.current_language()
    window = None
    try:
        assert manager.set_language(language)
        window = _ToolbarWindow()
        toolbar = create_main_toolbar(window)

        pointer = window.tool_actions["default"]
        pan = window.tool_actions["pan"]
        assert toolbar.accessibleName() == t("mainwindow.main_toolbar")
        assert pointer.text() == t("mainwindow.pointer")
        assert pan.text() == t("mainwindow.pan")
        assert toolbar.active_tool_chip.name_label.text() == pointer.text()
        assert toolbar.active_tool_chip.accessibleName() == (
            t("mainwindow.current_tool_value").replace(
                "%1", f"{pointer.text()} (P)"
            )
        )

        fps = window._cine_fps_spin
        assert fps.suffix() == t("settingsdialog.fps_suffix")
        assert fps.accessibleName() == t("toolbar.cine.frame_rate")
        assert fps.accessibleDescription() == t("toolbar.cine.frame_rate")
        assert fps.toolTip() == t("toolbar.cine.frame_rate")
        assert window._cine_play_btn.accessibleName() == t(
            "mainwindow.cine_play_pause"
        )

        raw_sync_states = (
            (("none", False, False, False), "off"),
            (("auto", False, False, False), "partial"),
            (("both", True, True, True), "all"),
        )
        sync_heading = t("mainwindow.sync_settings")
        for arguments, raw_state in raw_sync_states:
            toolbar.sync_button.set_sync_states(*arguments)
            tooltip = toolbar.sync_button.toolTip()
            expected_state = t(f"toolbar.sync.state_{raw_state}")
            assert tooltip == t("toolbar.sync.summary", state=expected_state)
            assert toolbar.sync_button.accessibleName() == sync_heading
            assert toolbar.sync_button.accessibleDescription() == tooltip
            if language == "zh_CN":
                assert not re.search(
                    rf"(?<![A-Za-z]){raw_state}(?![A-Za-z])",
                    tooltip,
                    flags=re.IGNORECASE,
                )

        roi_button = toolbar.findChild(QToolButton, "RoiToolButton")
        rectangle = window.tool_actions["rectangle_roi"]
        rectangle.trigger()
        assert roi_button.toolTip() == rectangle.text()
        assert roi_button.accessibleName() == rectangle.text()
        assert roi_button.accessibleDescription() == rectangle.text()

        measurement_button = toolbar.findChild(
            QToolButton, "MeasurementToolButton"
        )
        angle = window.tool_actions["angle"]
        angle.trigger()
        assert measurement_button.toolTip() == angle.text()
        assert measurement_button.accessibleName() == angle.text()
        assert measurement_button.accessibleDescription() == angle.text()

        toolbar.set_active_tool_feedback("window_level")
        assert toolbar.active_tool_chip.name_label.text() == t(
            "toolbar.window_level"
        )

        user_facing_text = (
            pointer.text(),
            pan.text(),
            fps.accessibleName(),
            toolbar.sync_button.toolTip(),
            roi_button.toolTip(),
            measurement_button.toolTip(),
            toolbar.active_tool_chip.name_label.text(),
        )
        assert all(text.strip() for text in user_facing_text)
        assert not any(
            re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", text)
            for text in user_facing_text
        )
    finally:
        if window is not None:
            window.close()
        manager.set_language(original_language)
