from PySide6.QtWidgets import (QToolBar, QMenu, QToolButton, QVBoxLayout,
                              QHBoxLayout, QRadioButton, QButtonGroup, QCheckBox,
                              QLabel, QFrame, QWidget, QWidgetAction, QSpinBox)
from PySide6.QtGui import QAction, QIcon, QActionGroup, QFont
from PySide6.QtCore import Qt, QPoint, QSize, Signal, QSignalBlocker

from medimager.utils.logger import get_logger
from medimager.utils.resource_path import get_icon_path
from medimager.utils.i18n import t

logger = get_logger(__name__)

# 工具栏统一尺寸常量
_ICON_SIZE = QSize(20, 20)
_BTN_HEIGHT = 32


class ViewerToolbar(QToolBar):
    """Main toolbar contract used by MainWindow without viewer coupling."""

    interaction_mode_requested = Signal(str)
    viewer_command_requested = Signal(str)
    voi_option_requested = Signal(object)
    voi_menu_about_to_show = Signal()


def _set_accessibility(widget, name: str, description: str = "") -> None:
    widget.setAccessibleName(name)
    widget.setAccessibleDescription(description or name)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


_SEMANTIC_ICON_FILES = {
    "pan": "pan.svg",
    "zoom_in": "zoom-in.svg",
    "fit": "fit.svg",
    "actual_size": "actual-size.svg",
    "reset": "reset.svg",
    "flip_horizontal": "flip-horizontal.svg",
    "flip_vertical": "flip-vertical.svg",
    "rotate_left": "rotate-left.svg",
    "rotate_right": "rotate-right.svg",
    "invert": "invert.svg",
}


def _semantic_icon(main_window, name: str) -> QIcon:
    """Use IconRegistry while retaining compatibility with lightweight stubs."""
    theme_manager = main_window.theme_manager
    if hasattr(theme_manager, "create_icon"):
        return theme_manager.create_icon(name)
    return theme_manager.create_themed_icon(
        get_icon_path(_SEMANTIC_ICON_FILES[name])
    )


def _tag_toolbar_action(toolbar: QToolBar, action: QAction, group: str, shortcut_hint: str = "") -> None:
    action.setProperty("toolbarGroup", group)
    action.setProperty("shortcutHint", shortcut_hint)
    label = action.text()
    if shortcut_hint:
        action.setToolTip(f"{label} ({shortcut_hint})")
    button = toolbar.widgetForAction(action)
    if button is not None:
        button.setProperty("toolbarGroup", group)
        _set_accessibility(button, label, action.toolTip() or label)


def _setup_button(btn: QToolButton):
    """统一设置普通工具按钮"""
    btn.setIconSize(_ICON_SIZE)
    btn.setFixedHeight(_BTN_HEIGHT)


_ARROW_STRIP_W = 14  # ::menu-button 箭头条宽度，与 stylesheet 保持一致

def _setup_split_dropdown(btn: QToolButton):
    """分体式下拉按钮：图标区点击激活工具，右侧箭头条点击弹出菜单。
    适用于 ROI、测量等需要区分"使用当前工具"和"切换子工具"的场景。
    总宽度 = 正方形图标区 + 箭头条，箭头条不侵入图标区。"""
    btn.setPopupMode(QToolButton.MenuButtonPopup)
    btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
    btn.setIconSize(_ICON_SIZE)
    btn.setFixedHeight(_BTN_HEIGHT)
    btn.setMinimumWidth(_BTN_HEIGHT + _ARROW_STRIP_W)
    # padding-right 补偿箭头条宽度，让图标在左侧正方形区域内居中
    btn.setStyleSheet(f"QToolButton {{ padding-right: {_ARROW_STRIP_W}px; }}")


def _setup_menu_button(btn: QToolButton):
    """整体式下拉按钮：点击按钮任意位置直接弹出菜单，右下角显示小三角指示。
    适用于窗宽窗位预设、图像变换、同步等纯菜单按钮。"""
    btn.setPopupMode(QToolButton.InstantPopup)
    btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
    btn.setIconSize(_ICON_SIZE)
    btn.setFixedHeight(_BTN_HEIGHT)


def create_main_toolbar(main_window) -> QToolBar:
    """
    创建并返回主工具栏。
    
    Args:
        main_window: MainWindow的实例，用于连接信号。
        
    Returns:
        配置好的QToolBar实例。
    """
    toolbar = ViewerToolbar(t("mainwindow.main_toolbar"), main_window)
    toolbar.setObjectName("MainToolBar")
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    toolbar.setIconSize(_ICON_SIZE)
    toolbar.setProperty("logicalGroups", "interaction,annotation,display,layout-sync-cine")
    toolbar.setAccessibleName(t("mainwindow.main_toolbar"))

    tool_action_group = QActionGroup(main_window)
    tool_action_group.setExclusive(True)

    # 在主窗口存储 actions，以便后续可以更新它们的选中状态
    main_window.tool_actions = {}

    # 1. 默认工具 (指针)
    click_icon_path = get_icon_path("click.svg")
    default_icon = main_window.theme_manager.create_themed_icon(click_icon_path)

    action = QAction(default_icon, t("mainwindow.pointer"), main_window)
    action.setStatusTip(t("mainwindow.activate_default_pointer_tool"))
    action.setCheckable(True)
    action.setChecked(True)
    action.triggered.connect(lambda: main_window._on_tool_selected("default"))
    action.triggered.connect(lambda: toolbar.interaction_mode_requested.emit("default"))
    action._icon_path = click_icon_path
    toolbar.addAction(action)
    tool_action_group.addAction(action)
    default_action = action
    main_window.tool_actions["default"] = action
    _tag_toolbar_action(toolbar, action, "interaction", "P")

    interaction_actions = {}
    for mode, icon_name, label, hint in (
        ("pan", "pan", "Pan", "H"),
        ("zoom", "zoom_in", "Zoom", "Z"),
    ):
        mode_action = QAction(_semantic_icon(main_window, icon_name), label, main_window)
        mode_action.setCheckable(True)
        mode_action.setStatusTip(label)
        mode_action.triggered.connect(
            lambda checked=False, requested=mode: toolbar.interaction_mode_requested.emit(requested)
        )
        toolbar.addAction(mode_action)
        tool_action_group.addAction(mode_action)
        main_window.tool_actions[mode] = mode_action
        interaction_actions[mode] = mode_action
        _tag_toolbar_action(toolbar, mode_action, "interaction", hint)

    toolbar.addSeparator()

    # 2. ROI工具按钮（带下拉菜单）
    roi_button = QToolButton(main_window)
    roi_button.setObjectName("RoiToolButton")
    roi_button.setCheckable(True)
    _setup_split_dropdown(roi_button)

    ellipse_icon_path = get_icon_path("ellipse.svg")
    ellipse_icon = main_window.theme_manager.create_themed_icon(ellipse_icon_path)
    roi_button.setIcon(ellipse_icon)
    roi_button.setToolTip(t("mainwindow.select_roi_tool_type"))
    roi_button._icon_path = ellipse_icon_path
    roi_button._active_tool_name = "ellipse_roi"

    roi_menu = QMenu(main_window)
    roi_action_group = QActionGroup(main_window)
    roi_action_group.setExclusive(True)
    ellipse_action = QAction(ellipse_icon, t("mainwindow.ellipse"), main_window)
    ellipse_action.setCheckable(True)
    ellipse_action.setChecked(True)
    ellipse_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, ellipse_action, "ellipse_roi"))
    ellipse_action._icon_path = ellipse_icon_path
    roi_menu.addAction(ellipse_action)
    roi_action_group.addAction(ellipse_action)

    rect_icon_path = get_icon_path("rectangle.svg")
    rect_icon = main_window.theme_manager.create_themed_icon(rect_icon_path)
    rect_action = QAction(rect_icon, t("mainwindow.rectangle"), main_window)
    rect_action.setCheckable(True)
    rect_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, rect_action, "rectangle_roi"))
    rect_action._icon_path = rect_icon_path
    roi_menu.addAction(rect_action)
    roi_action_group.addAction(rect_action)

    circle_icon_path = get_icon_path("circle.svg")
    circle_icon = main_window.theme_manager.create_themed_icon(circle_icon_path)
    circle_action = QAction(circle_icon, t("mainwindow.circle"), main_window)
    circle_action.setCheckable(True)
    circle_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, circle_action, "circle_roi"))
    circle_action._icon_path = circle_icon_path
    roi_menu.addAction(circle_action)
    roi_action_group.addAction(circle_action)

    roi_button.setMenu(roi_menu)
    roi_button._active_action = ellipse_action
    roi_button.clicked.connect(
        lambda checked=False: _activate_split_tool(roi_button)
    )

    def refresh_roi_icon():
        icon_path = getattr(roi_button, '_icon_path', ellipse_icon_path)
        roi_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))

    roi_button.refresh_icon = refresh_roi_icon
    toolbar.addWidget(roi_button)

    main_window.tool_actions["ellipse_roi"] = ellipse_action
    main_window.tool_actions["rectangle_roi"] = rect_action
    main_window.tool_actions["circle_roi"] = circle_action
    roi_button.setProperty("toolbarGroup", "annotation")
    _set_accessibility(roi_button, t("mainwindow.select_roi_tool_type"))

    # 3. 测量工具按钮（带下拉菜单）
    measure_button = QToolButton(main_window)
    measure_button.setObjectName("MeasurementToolButton")
    measure_button.setCheckable(True)
    _setup_split_dropdown(measure_button)

    ruler_icon_path = get_icon_path("ruler.svg")
    ruler_icon = main_window.theme_manager.create_themed_icon(ruler_icon_path)
    measure_button.setIcon(ruler_icon)
    measure_button.setToolTip(t("mainwindow.measurement_tool"))
    measure_button._icon_path = ruler_icon_path
    measure_button._active_tool_name = "measurement"

    measure_menu = QMenu(main_window)
    measure_action_group = QActionGroup(main_window)
    measure_action_group.setExclusive(True)
    ruler_action = QAction(ruler_icon, t("mainwindow.line_measurement"), main_window)
    ruler_action.setCheckable(True)
    ruler_action.setChecked(True)
    ruler_action.triggered.connect(lambda: _on_measure_tool_selected(main_window, measure_button, ruler_action, "measurement"))
    ruler_action._icon_path = ruler_icon_path
    measure_menu.addAction(ruler_action)
    measure_action_group.addAction(ruler_action)

    angle_icon_path = get_icon_path("angle.svg")
    angle_icon = main_window.theme_manager.create_themed_icon(angle_icon_path)
    angle_action = QAction(angle_icon, t("mainwindow.angle_measurement"), main_window)
    angle_action.setCheckable(True)
    angle_action.triggered.connect(lambda: _on_measure_tool_selected(main_window, measure_button, angle_action, "angle"))
    angle_action._icon_path = angle_icon_path
    measure_menu.addAction(angle_action)
    measure_action_group.addAction(angle_action)

    measure_button.setMenu(measure_menu)
    measure_button._active_action = ruler_action
    measure_button.clicked.connect(
        lambda checked=False: _activate_split_tool(measure_button)
    )

    def refresh_measure_icon():
        icon_path = getattr(measure_button, '_icon_path', ruler_icon_path)
        measure_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))

    measure_button.refresh_icon = refresh_measure_icon
    toolbar.addWidget(measure_button)

    main_window.tool_actions["measurement"] = ruler_action
    main_window.tool_actions["angle"] = angle_action
    measure_button.setProperty("toolbarGroup", "annotation")
    _set_accessibility(measure_button, t("mainwindow.measurement_tool"))

    toolbar.addSeparator()

    # 4. Window/level interaction and DICOM VOI presets
    wl_button = create_wl_preset_button(main_window, toolbar)
    wl_button.setProperty("toolbarGroup", "display")
    toolbar.addWidget(wl_button)

    for command, icon_name, label, hint in (
        ("fit", "fit", "Fit image", "F"),
        ("actual_size", "actual_size", "Actual pixels (1:1)", "1"),
        ("reset_view", "reset", "Reset view", "Home"),
    ):
        command_action = QAction(_semantic_icon(main_window, icon_name), label, main_window)
        command_action.triggered.connect(
            lambda checked=False, requested=command: toolbar.viewer_command_requested.emit(requested)
        )
        toolbar.addAction(command_action)
        _tag_toolbar_action(toolbar, command_action, "display", hint)

    # 5. Image transform menu
    transform_button = create_transform_button(main_window)
    transform_button.setProperty("toolbarGroup", "display")
    _set_accessibility(transform_button, t("mainwindow.image_transform"))
    toolbar.addWidget(transform_button)

    toolbar.addSeparator()

    # 6. 布局选择器按钮
    layout_button = create_layout_selector_button(main_window)
    layout_button.setProperty("toolbarGroup", "layout-sync-cine")
    toolbar.addWidget(layout_button)

    # 7. Sync status and controls
    sync_button = create_sync_button(main_window)
    sync_button.setProperty("toolbarGroup", "layout-sync-cine")
    toolbar.addWidget(sync_button)

    # 8. Orthogonal MPR workspace
    mpr_icon_path = get_icon_path('mpr.svg')
    mpr_action = QAction(
        main_window.theme_manager.create_themed_icon(mpr_icon_path),
        t('mpr.enter'),
        main_window,
    )
    mpr_action.setCheckable(True)
    mpr_action.setEnabled(False)
    mpr_handler = getattr(main_window, '_toggle_mpr_workspace', None)
    if callable(mpr_handler):
        mpr_action.triggered.connect(mpr_handler)
    mpr_action._icon_path = mpr_icon_path
    toolbar.addAction(mpr_action)
    _tag_toolbar_action(toolbar, mpr_action, 'layout-sync-cine', 'M')
    main_window.mpr_action = mpr_action
    if not hasattr(main_window, '_image_required_actions'):
        main_window._image_required_actions = []
    main_window._image_required_actions.append(mpr_action)

    # 9. Cine playback
    cine_controls = create_cine_controls(main_window)
    cine_controls.setProperty("toolbarGroup", "layout-sync-cine")
    toolbar.addWidget(cine_controls)

    if not hasattr(main_window, '_image_required_widgets'):
        main_window._image_required_widgets = []
    main_window._image_required_widgets.extend([
        roi_button,
        measure_button,
        wl_button,
        transform_button,
    ])

    roi_tools = {"ellipse_roi", "rectangle_roi", "circle_roi"}
    measurement_tools = {"measurement", "angle"}

    def set_active_tool_feedback(tool_name: str) -> None:
        """Keep every interaction/annotation control visibly selected."""
        default_action.setChecked(tool_name == "default")
        for name, mode_action in interaction_actions.items():
            mode_action.setChecked(tool_name == name)
        wl_button.setChecked(tool_name == "window_level")
        roi_button.setChecked(tool_name in roi_tools)
        measure_button.setChecked(tool_name in measurement_tools)

    for tool_name, tool_action in main_window.tool_actions.items():
        tool_action.triggered.connect(
            lambda checked=False, name=tool_name: set_active_tool_feedback(name)
        )

    # Expose a small toolbar-level API for programmatic tool changes.
    toolbar.set_active_tool_feedback = set_active_tool_feedback
    toolbar.set_dicom_voi_options = wl_button.set_dicom_voi_options
    toolbar.set_cine_fps = cine_controls.set_fps
    toolbar.sync_button = sync_button
    set_active_tool_feedback("default")

    return toolbar


def _on_roi_tool_selected(main_window, roi_tool_button, action, tool_name):
    """当ROI工具被选中时，更新工具栏按钮并切换工具"""
    # 更新工具栏按钮的图标和文本
    roi_tool_button.setIcon(action.icon())
    roi_tool_button.setToolTip(action.text())
    roi_tool_button._icon_path = action._icon_path
    roi_tool_button._active_action = action
    roi_tool_button._active_tool_name = tool_name
    roi_tool_button.setChecked(True)
    
    # 更新菜单中的选中状态
    menu = roi_tool_button.menu()
    if menu:
        for menu_action in menu.actions():
            menu_action.setChecked(menu_action == action)
    
    # 切换工具
    main_window._on_tool_selected(tool_name)


def _on_measure_tool_selected(main_window, measure_button, action, tool_name):
    """当测量工具被选中时，更新工具栏按钮并切换工具"""
    measure_button.setIcon(action.icon())
    measure_button.setToolTip(action.text())
    measure_button._icon_path = action._icon_path
    measure_button._active_action = action
    measure_button._active_tool_name = tool_name
    measure_button.setChecked(True)

    menu = measure_button.menu()
    if menu:
        for menu_action in menu.actions():
            menu_action.setChecked(menu_action == action)

    main_window._on_tool_selected(tool_name)


def _activate_split_tool(button: QToolButton) -> None:
    """Activate the sub-tool currently represented by a split button."""
    action = getattr(button, "_active_action", None)
    if action is not None:
        action.trigger()


def create_wl_preset_button(main_window, toolbar: ViewerToolbar | None = None) -> QToolButton:
    """创建窗宽窗位预设按钮"""
    wl_button = QToolButton(main_window)
    wl_button.setToolTip(t("mainwindow.window_level_presets") + " (W)")
    wl_button.setCheckable(True)
    _setup_split_dropdown(wl_button)
    _set_accessibility(wl_button, t("mainwindow.window_level_presets"))
    if toolbar is not None:
        wl_button.clicked.connect(
            lambda checked=False: toolbar.interaction_mode_requested.emit("window_level")
        )

    icon_path = get_icon_path("contrast.svg")
    wl_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))
    wl_button._icon_path = icon_path

    wl_menu = QMenu(main_window)
    presets = [
        (t("mainwindow.auto"), -1, -1),
        (t("mainwindow.abdomen"), 400, 50),
        (t("mainwindow.brain_window"), 80, 40),
        (t("mainwindow.bone_window"), 2000, 600),
        (t("mainwindow.lung_window"), 1500, -600),
        (t("mainwindow.mediastinum"), 350, 50),
    ]
    for name, width, level in presets:
        action = QAction(name, main_window)
        action.triggered.connect(
            lambda checked=False, width=width, level=level: (
                main_window._set_window_level_preset(width, level)
            )
        )
        wl_menu.addAction(action)

    dicom_separator = wl_menu.addSeparator()
    dicom_separator.setVisible(False)
    custom_action = QAction(t("mainwindow.custom_ellipsis"), main_window)
    custom_action.triggered.connect(main_window._open_custom_wl_dialog)
    wl_menu.addAction(custom_action)

    wl_button.setMenu(wl_menu)
    wl_button._dicom_voi_actions = []
    if toolbar is not None:
        wl_menu.aboutToShow.connect(toolbar.voi_menu_about_to_show.emit)

    def set_dicom_voi_options(options, active_index=None):
        for old_action in wl_button._dicom_voi_actions:
            wl_menu.removeAction(old_action)
            old_action.deleteLater()
        wl_button._dicom_voi_actions = []
        safe_options = [dict(option) for option in (options or [])]
        dicom_separator.setVisible(bool(safe_options))
        for index, option in enumerate(safe_options):
            option_action = QAction(str(option.get("label") or "DICOM VOI"), wl_menu)
            option_action.setCheckable(True)
            option_action.setChecked(active_index == index)
            option_action.setData(option)
            if toolbar is not None:
                option_action.triggered.connect(
                    lambda checked=False, selected=dict(option): toolbar.voi_option_requested.emit(selected)
                )
            wl_menu.insertAction(dicom_separator, option_action)
            wl_button._dicom_voi_actions.append(option_action)

    wl_button.set_dicom_voi_options = set_dicom_voi_options

    def refresh_icon():
        icon_p = getattr(wl_button, '_icon_path', icon_path)
        wl_button.setIcon(main_window.theme_manager.create_themed_icon(icon_p))

    wl_button.refresh_icon = refresh_icon
    return wl_button


def create_transform_button(main_window) -> QToolButton:
    """创建图像变换按钮（翻转/旋转/反色）"""
    btn = QToolButton(main_window)
    btn.setToolTip(t("mainwindow.image_transform"))
    _setup_menu_button(btn)

    icon_path = get_icon_path("transform.svg")
    btn.setIcon(main_window.theme_manager.create_themed_icon(icon_path))
    btn._icon_path = icon_path

    menu = QMenu(main_window)
    transforms = [
        (t("mainwindow.flip_horizontal"), "flip_h", "flip_horizontal"),
        (t("mainwindow.flip_vertical"), "flip_v", "flip_vertical"),
        (t("mainwindow.rotate_left_90"), "rotate_left", "rotate_left"),
        (t("mainwindow.rotate_right_90"), "rotate_right", "rotate_right"),
        (t("mainwindow.invert"), "invert", "invert"),
    ]
    for name, key, semantic_icon in transforms:
        action = QAction(_semantic_icon(main_window, semantic_icon), name, main_window)
        action.triggered.connect(
            lambda checked=False, k=key: main_window._apply_viewer_transform(k)
        )
        menu.addAction(action)

    menu.addSeparator()
    reset_action = QAction(_semantic_icon(main_window, "reset"), t("mainwindow.reset"), main_window)
    reset_action.triggered.connect(
        lambda: main_window._apply_viewer_transform("reset")
    )
    menu.addAction(reset_action)

    btn.setMenu(menu)

    def refresh_icon():
        icon_p = getattr(btn, '_icon_path', icon_path)
        btn.setIcon(main_window.theme_manager.create_themed_icon(icon_p))

    btn.refresh_icon = refresh_icon
    return btn


def create_cine_controls(main_window) -> QWidget:
    """创建 Cine 播放控件"""
    container = QWidget(main_window)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(2, 0, 2, 0)
    layout.setSpacing(4)

    # 播放/暂停按钮
    play_btn = QToolButton(main_window)
    play_icon_path = get_icon_path("play.svg")
    play_btn.setIcon(main_window.theme_manager.create_themed_icon(play_icon_path))
    play_btn.setToolTip(t("mainwindow.cine_play_pause"))
    play_btn._icon_path = play_icon_path
    play_btn.setCheckable(True)
    _setup_button(play_btn)
    play_btn.toggled.connect(lambda checked: main_window._cine_toggle_play())
    layout.addWidget(play_btn)

    # 帧率控制
    fps_spin = QSpinBox(main_window)
    fps_spin.setRange(1, 60)
    fps_spin.setValue(max(1, min(60, int(getattr(main_window, "_cine_fps", 10)))))
    fps_spin.setSuffix(t("settingsdialog.fps_suffix"))
    fps_spin.setFixedWidth(72)
    fps_spin.setFixedHeight(_BTN_HEIGHT)
    fps_spin.valueChanged.connect(main_window._cine_set_fps)
    layout.addWidget(fps_spin)

    # 存储引用以便状态更新
    main_window._cine_play_btn = play_btn
    main_window._cine_fps_spin = fps_spin
    _set_accessibility(play_btn, t("mainwindow.cine_play_pause"), "Space")
    fps_spin.setAccessibleName(t("mainwindow.cine_play_pause"))

    def set_fps(value: int) -> None:
        blocker = QSignalBlocker(fps_spin)
        fps_spin.setValue(max(1, min(60, int(value))))
        del blocker

    container.set_fps = set_fps

    def refresh_icon():
        icon_p = getattr(play_btn, '_icon_path', play_icon_path)
        play_btn.setIcon(main_window.theme_manager.create_themed_icon(icon_p))

    container.refresh_icon = refresh_icon
    return container


def create_layout_selector_button(main_window) -> QToolButton:
    """创建布局选择器按钮"""
    layout_button = QToolButton(main_window)
    layout_button.setObjectName("LayoutSelectorButton")
    layout_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    _setup_button(layout_button)
    
    # 设置图标
    layout_icon_path = get_icon_path("layout.svg")
    layout_icon = main_window.theme_manager.create_themed_icon(layout_icon_path)
    layout_button.setIcon(layout_icon)
    layout_button.setToolTip(t("mainwindow.select_view_layout"))
    layout_button._icon_path = layout_icon_path
    _set_accessibility(layout_button, t("mainwindow.select_view_layout"))
    
    def on_layout_button_clicked():
        """布局按钮点击事件处理"""
        logger.debug("[create_layout_selector_button] 布局按钮被点击")
        
        from medimager.ui.widgets.layout_grid_selector import LayoutDropdown
        
        if not hasattr(layout_button, '_dropdown'):
            # 传递main_window作为父窗口，确保能找到主题管理器
            layout_dropdown = LayoutDropdown(main_window)
            layout_dropdown.layout_selected.connect(lambda config: main_window._set_layout(config))
            layout_dropdown.auto_assign_requested.connect(main_window._auto_assign_all_series)
            layout_dropdown.clear_bindings_requested.connect(main_window._clear_all_bindings)
            layout_button._dropdown = layout_dropdown
        
        global_pos = layout_button.mapToGlobal(QPoint(0, layout_button.height()))
        layout_button._dropdown.show_at_position(global_pos)
    
    layout_button.clicked.connect(on_layout_button_clicked)
    
    def set_current_layout(layout_config):
        """设置当前布局显示"""
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            layout_button.setToolTip(
                t("layoutselectorbutton.current_layout_size").replace("%1", str(rows)).replace("%2", str(cols))
            )
        else:
            layout_button.setToolTip(t("layoutselectorbutton.current_layout_special_layout"))
    
    layout_button.set_current_layout = set_current_layout
    
    def refresh_icon():
        """刷新图标以适应主题变化"""
        icon_path = getattr(layout_button, '_icon_path', layout_icon_path)
        layout_icon = main_window.theme_manager.create_themed_icon(icon_path)
        layout_button.setIcon(layout_icon)
    
    layout_button.refresh_icon = refresh_icon
    
    return layout_button


def create_sync_button(main_window) -> QToolButton:
    """创建同步按钮"""
    sync_button = QToolButton(main_window)
    sync_button.setToolTip(t("mainwindow.sync_settings"))
    sync_button.setCheckable(True)
    sync_button.setProperty("syncState", "partial")
    _setup_menu_button(sync_button)
    _set_accessibility(sync_button, t("mainwindow.sync_settings"))
    
    chain_icon_path = get_icon_path("chain.svg")
    sync_button.setIcon(main_window.theme_manager.create_themed_icon(chain_icon_path))
    sync_button._icon_path = chain_icon_path
    
    # 创建同步下拉菜单
    # 使用自定义 QMenu 子类，防止点击内嵌 widget 时菜单自动关闭
    class _SyncMenu(QMenu):
        def mouseReleaseEvent(self, event):
            action = self.activeAction()
            if action and isinstance(action, QWidgetAction):
                # 内嵌 widget 区域的点击不关闭菜单
                action.trigger()
                return
            super().mouseReleaseEvent(event)

    sync_menu = _SyncMenu(main_window)
    sync_widget = SyncDropdownWidget(main_window)

    widget_action = QWidgetAction(main_window)
    widget_action.setDefaultWidget(sync_widget)
    sync_menu.addAction(widget_action)
    sync_button.setMenu(sync_menu)
    
    # 连接信号
    sync_widget.sync_position_changed.connect(main_window._on_sync_position_changed)
    sync_widget.sync_pan_changed.connect(main_window._on_sync_pan_changed)
    sync_widget.sync_zoom_changed.connect(main_window._on_sync_zoom_changed)
    sync_widget.sync_window_level_changed.connect(main_window._on_sync_window_level_changed)
    
    # 添加设置和获取状态的方法
    def _update_sync_summary() -> None:
        states = sync_widget.get_sync_states()
        enabled = [states["position_mode"] != "none", states["pan"], states["zoom"], states["window_level"]]
        if not any(enabled):
            summary = "off"
        elif all(enabled) and states["position_mode"] == "both":
            summary = "all"
        else:
            summary = "partial"
        sync_button.setProperty("syncState", summary)
        sync_button.setChecked(summary != "off")
        sync_button.setToolTip(f"{t('mainwindow.sync_settings')}: {summary}")
        sync_button.setAccessibleDescription(sync_button.toolTip())
        sync_button.style().unpolish(sync_button)
        sync_button.style().polish(sync_button)

    def set_sync_states(position_mode: str = "auto", pan: bool = False,
                        zoom: bool = False, window_level: bool = False) -> None:
        sync_widget.set_sync_states(position_mode, pan, zoom, window_level)
        _update_sync_summary()
    
    def get_sync_states() -> dict:
        return sync_widget.get_sync_states()
    
    def refresh_icon():
        """刷新图标以适应主题变化"""
        icon_path = getattr(sync_button, '_icon_path', chain_icon_path)
        if icon_path:
            new_icon = main_window.theme_manager.create_themed_icon(icon_path)
            sync_button.setIcon(new_icon)
    
    for state_signal in (
        sync_widget.sync_position_changed,
        sync_widget.sync_pan_changed,
        sync_widget.sync_zoom_changed,
        sync_widget.sync_window_level_changed,
    ):
        state_signal.connect(lambda *_: _update_sync_summary())

    sync_button.set_sync_states = set_sync_states
    sync_button.get_sync_states = get_sync_states
    sync_button.sync_widget = sync_widget
    sync_button.refresh_icon = refresh_icon
    _update_sync_summary()
    
    return sync_button


class SyncDropdownWidget(QWidget):
    """同步功能下拉菜单组件"""
    
    sync_position_changed = Signal(str)
    sync_pan_changed = Signal(bool)
    sync_zoom_changed = Signal(bool)
    sync_window_level_changed = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        logger.debug("[SyncDropdownWidget.__init__] 初始化同步下拉菜单组件")
        
        self._setup_ui()
        self._connect_signals()
        
        logger.debug("[SyncDropdownWidget.__init__] 同步下拉菜单组件初始化完成")
    
    def _setup_ui(self):
        """设置UI布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        
        # 设置字体
        font = QFont()
        font.setPointSize(9)
        
        # 同步位置
        position_frame = self._create_position_section()
        layout.addWidget(position_frame)
        
        # 分隔线
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line1)
        
        # 同步平移
        self._pan_checkbox = QCheckBox(t("syncdropdownwidget.synchronized_translation"))
        self._pan_checkbox.setFont(font)
        layout.addWidget(self._pan_checkbox)
        
        # 同步缩放
        self._zoom_checkbox = QCheckBox(t("syncdropdownwidget.synchronized_zoom"))
        self._zoom_checkbox.setFont(font)
        layout.addWidget(self._zoom_checkbox)
        
        # 同步窗宽窗位
        self._window_level_checkbox = QCheckBox(t("syncdropdownwidget.synchronize_window_width_and_window_position"))
        self._window_level_checkbox.setFont(font)
        layout.addWidget(self._window_level_checkbox)
        
        # 设置默认状态
        self._set_default_states()
    
    def _create_position_section(self):
        """创建位置同步部分"""
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # 标题
        title_label = QLabel(t("syncdropdownwidget.sync_location"))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        title_label.setFont(font)
        layout.addWidget(title_label)
        
        # 单选按钮组
        radio_layout = QHBoxLayout()
        radio_layout.setContentsMargins(16, 0, 0, 0)
        radio_layout.setSpacing(12)
        
        self._position_button_group = QButtonGroup(self)
        
        self._position_none_radio = QRadioButton(t("syncdropdownwidget.no"))
        self._position_auto_radio = QRadioButton(t("syncdropdownwidget.auto"))
        self._position_manual_radio = QRadioButton(t("syncdropdownwidget.manual"))
        self._position_both_radio = QRadioButton(t("syncdropdownwidget.both"))
        
        # 设置字体
        radio_font = QFont()
        radio_font.setPointSize(9)
        self._position_none_radio.setFont(radio_font)
        self._position_auto_radio.setFont(radio_font)
        self._position_manual_radio.setFont(radio_font)
        self._position_both_radio.setFont(radio_font)
        
        self._position_button_group.addButton(self._position_none_radio, 0)
        self._position_button_group.addButton(self._position_auto_radio, 1)
        self._position_button_group.addButton(self._position_manual_radio, 2)
        self._position_button_group.addButton(self._position_both_radio, 3)
        
        radio_layout.addWidget(self._position_none_radio)
        radio_layout.addWidget(self._position_auto_radio)
        radio_layout.addWidget(self._position_manual_radio)
        radio_layout.addWidget(self._position_both_radio)
        radio_layout.addStretch()
        
        layout.addLayout(radio_layout)
        
        return frame
    
    def _set_default_states(self):
        """设置默认状态"""
        # 默认位置同步为"自动"
        self._position_auto_radio.setChecked(True)
        
        # 默认其他同步功能关闭
        self._pan_checkbox.setChecked(False)
        self._zoom_checkbox.setChecked(False)
        self._window_level_checkbox.setChecked(False)
    
    def _connect_signals(self):
        """连接信号"""
        # 位置同步信号
        self._position_button_group.buttonClicked.connect(self._on_position_changed)
        
        # 其他同步信号
        self._pan_checkbox.toggled.connect(self._on_pan_changed)
        self._zoom_checkbox.toggled.connect(self._on_zoom_changed)
        self._window_level_checkbox.toggled.connect(self._on_window_level_changed)
    
    def _on_position_changed(self):
        """位置同步模式变化处理"""
        checked_id = self._position_button_group.checkedId()
        mode_map = {0: "none", 1: "auto", 2: "manual", 3: "both"}
        mode = mode_map.get(checked_id, "none")
        
        logger.debug(f"[SyncDropdownWidget._on_position_changed] 位置同步模式变化: {mode}")
        self.sync_position_changed.emit(mode)
    
    def _on_pan_changed(self, checked: bool):
        """平移同步状态变化处理"""
        logger.debug(f"[SyncDropdownWidget._on_pan_changed] 平移同步状态变化: {checked}")
        self.sync_pan_changed.emit(checked)
    
    def _on_zoom_changed(self, checked: bool):
        """缩放同步状态变化处理"""
        logger.debug(f"[SyncDropdownWidget._on_zoom_changed] 缩放同步状态变化: {checked}")
        self.sync_zoom_changed.emit(checked)
    
    def _on_window_level_changed(self, checked: bool):
        """窗宽窗位同步状态变化处理"""
        logger.debug(f"[SyncDropdownWidget._on_window_level_changed] 窗宽窗位同步状态变化: {checked}")
        self.sync_window_level_changed.emit(checked)
    
    def set_sync_states(self, position_mode: str = "auto", pan: bool = False, 
                       zoom: bool = False, window_level: bool = False):
        """设置同步状态"""
        logger.debug(f"[SyncDropdownWidget.set_sync_states] 设置同步状态: position={position_mode}, pan={pan}, zoom={zoom}, wl={window_level}")
        
        # 设置位置同步模式
        mode_map = {"none": 0, "auto": 1, "manual": 2, "both": 3}
        button_id = mode_map.get(position_mode, 1)
        if button := self._position_button_group.button(button_id):
            button.setChecked(True)
        
        # 设置其他同步状态
        self._pan_checkbox.setChecked(pan)
        self._zoom_checkbox.setChecked(zoom)
        self._window_level_checkbox.setChecked(window_level)
    
    def get_sync_states(self) -> dict:
        """获取当前同步状态"""
        checked_id = self._position_button_group.checkedId()
        mode_map = {0: "none", 1: "auto", 2: "manual", 3: "both"}
        position_mode = mode_map.get(checked_id, "auto")
        
        states = {
            "position_mode": position_mode,
            "pan": self._pan_checkbox.isChecked(),
            "zoom": self._zoom_checkbox.isChecked(),
            "window_level": self._window_level_checkbox.isChecked()
        }
        
        logger.debug(f"[SyncDropdownWidget.get_sync_states] 获取同步状态: {states}")
        return states
