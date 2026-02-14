from PySide6.QtWidgets import (QToolBar, QMenu, QToolButton, QVBoxLayout,
                              QHBoxLayout, QRadioButton, QButtonGroup, QCheckBox,
                              QLabel, QFrame, QWidget, QWidgetAction, QSpinBox)
from PySide6.QtGui import QAction, QIcon, QActionGroup, QFont
from PySide6.QtCore import Qt, QPoint, QSize, Signal

from medimager.utils.logger import get_logger
from medimager.utils.resource_path import get_icon_path

logger = get_logger(__name__)

# 工具栏统一尺寸常量
_ICON_SIZE = QSize(20, 20)
_BTN_HEIGHT = 32


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
    toolbar = QToolBar(main_window.tr("主工具"), main_window)
    toolbar.setObjectName("MainToolBar")
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    toolbar.setIconSize(_ICON_SIZE)

    tool_action_group = QActionGroup(main_window)
    tool_action_group.setExclusive(True)

    # 在主窗口存储 actions，以便后续可以更新它们的选中状态
    main_window.tool_actions = {}

    # 1. 默认工具 (指针)
    click_icon_path = get_icon_path("click.svg")
    default_icon = main_window.theme_manager.create_themed_icon(click_icon_path)

    action = QAction(default_icon, main_window.tr("指针"), main_window)
    action.setStatusTip(main_window.tr("激活默认的指针、平移、缩放、窗位工具"))
    action.setCheckable(True)
    action.setChecked(True)
    action.triggered.connect(lambda: main_window._on_tool_selected("default"))
    action._icon_path = click_icon_path
    toolbar.addAction(action)
    tool_action_group.addAction(action)
    main_window.tool_actions["default"] = action

    toolbar.addSeparator()

    # 2. ROI工具按钮（带下拉菜单）
    roi_button = QToolButton(main_window)
    _setup_split_dropdown(roi_button)

    ellipse_icon_path = get_icon_path("ellipse.svg")
    ellipse_icon = main_window.theme_manager.create_themed_icon(ellipse_icon_path)
    roi_button.setIcon(ellipse_icon)
    roi_button.setToolTip(main_window.tr("选择ROI工具类型"))
    roi_button._icon_path = ellipse_icon_path

    roi_menu = QMenu(main_window)
    roi_action_group = QActionGroup(main_window)
    roi_action_group.setExclusive(True)

    ellipse_action = QAction(ellipse_icon, main_window.tr("椭圆"), main_window)
    ellipse_action.setCheckable(True)
    ellipse_action.setChecked(True)
    ellipse_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, ellipse_action, "ellipse_roi"))
    ellipse_action._icon_path = ellipse_icon_path
    roi_menu.addAction(ellipse_action)
    roi_action_group.addAction(ellipse_action)

    rect_icon_path = get_icon_path("rectangle.svg")
    rect_icon = main_window.theme_manager.create_themed_icon(rect_icon_path)
    rect_action = QAction(rect_icon, main_window.tr("矩形"), main_window)
    rect_action.setCheckable(True)
    rect_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, rect_action, "rectangle_roi"))
    rect_action._icon_path = rect_icon_path
    roi_menu.addAction(rect_action)
    roi_action_group.addAction(rect_action)

    circle_icon_path = get_icon_path("circle.svg")
    circle_icon = main_window.theme_manager.create_themed_icon(circle_icon_path)
    circle_action = QAction(circle_icon, main_window.tr("圆形"), main_window)
    circle_action.setCheckable(True)
    circle_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_button, circle_action, "circle_roi"))
    circle_action._icon_path = circle_icon_path
    roi_menu.addAction(circle_action)
    roi_action_group.addAction(circle_action)

    roi_button.setMenu(roi_menu)
    roi_button.clicked.connect(lambda: main_window._on_tool_selected("ellipse_roi"))

    def refresh_roi_icon():
        icon_path = getattr(roi_button, '_icon_path', ellipse_icon_path)
        roi_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))

    roi_button.refresh_icon = refresh_roi_icon
    toolbar.addWidget(roi_button)

    tool_action_group.addAction(ellipse_action)
    main_window.tool_actions["ellipse_roi"] = ellipse_action
    main_window.tool_actions["rectangle_roi"] = rect_action
    main_window.tool_actions["circle_roi"] = circle_action

    toolbar.addSeparator()

    # 3. 测量工具按钮（带下拉菜单）
    measure_button = QToolButton(main_window)
    _setup_split_dropdown(measure_button)

    ruler_icon_path = get_icon_path("ruler.svg")
    ruler_icon = main_window.theme_manager.create_themed_icon(ruler_icon_path)
    measure_button.setIcon(ruler_icon)
    measure_button.setToolTip(main_window.tr("测量工具"))
    measure_button._icon_path = ruler_icon_path

    measure_menu = QMenu(main_window)
    measure_action_group = QActionGroup(main_window)
    measure_action_group.setExclusive(True)

    ruler_action = QAction(ruler_icon, main_window.tr("直线测量"), main_window)
    ruler_action.setCheckable(True)
    ruler_action.setChecked(True)
    ruler_action.triggered.connect(lambda: _on_measure_tool_selected(main_window, measure_button, ruler_action, "measurement"))
    ruler_action._icon_path = ruler_icon_path
    measure_menu.addAction(ruler_action)
    measure_action_group.addAction(ruler_action)

    angle_icon_path = get_icon_path("angle.svg")
    angle_icon = main_window.theme_manager.create_themed_icon(angle_icon_path)
    angle_action = QAction(angle_icon, main_window.tr("角度测量"), main_window)
    angle_action.setCheckable(True)
    angle_action.triggered.connect(lambda: _on_measure_tool_selected(main_window, measure_button, angle_action, "angle"))
    angle_action._icon_path = angle_icon_path
    measure_menu.addAction(angle_action)
    measure_action_group.addAction(angle_action)

    measure_button.setMenu(measure_menu)
    measure_button.clicked.connect(lambda: main_window._on_tool_selected("measurement"))

    def refresh_measure_icon():
        icon_path = getattr(measure_button, '_icon_path', ruler_icon_path)
        measure_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))

    measure_button.refresh_icon = refresh_measure_icon
    toolbar.addWidget(measure_button)

    tool_action_group.addAction(ruler_action)
    tool_action_group.addAction(angle_action)
    main_window.tool_actions["measurement"] = ruler_action
    main_window.tool_actions["angle"] = angle_action

    toolbar.addSeparator()

    # 4. 窗宽窗位预设按钮
    wl_button = create_wl_preset_button(main_window)
    toolbar.addWidget(wl_button)

    toolbar.addSeparator()

    # 5. 图像变换按钮
    transform_button = create_transform_button(main_window)
    toolbar.addWidget(transform_button)

    toolbar.addSeparator()

    # 6. 布局选择器按钮
    layout_button = create_layout_selector_button(main_window)
    toolbar.addWidget(layout_button)

    toolbar.addSeparator()

    # 7. 同步按钮
    sync_button = create_sync_button(main_window)
    toolbar.addWidget(sync_button)

    toolbar.addSeparator()

    # 8. Cine 播放控件
    cine_controls = create_cine_controls(main_window)
    toolbar.addWidget(cine_controls)

    return toolbar


def _on_roi_tool_selected(main_window, roi_tool_button, action, tool_name):
    """当ROI工具被选中时，更新工具栏按钮并切换工具"""
    # 更新工具栏按钮的图标和文本
    roi_tool_button.setIcon(action.icon())
    roi_tool_button.setToolTip(action.text())
    roi_tool_button._icon_path = action._icon_path
    
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

    menu = measure_button.menu()
    if menu:
        for menu_action in menu.actions():
            menu_action.setChecked(menu_action == action)

    main_window._on_tool_selected(tool_name)


def create_wl_preset_button(main_window) -> QToolButton:
    """创建窗宽窗位预设按钮"""
    wl_button = QToolButton(main_window)
    wl_button.setToolTip(main_window.tr("窗宽窗位预设"))
    _setup_menu_button(wl_button)

    icon_path = get_icon_path("contrast.svg")
    wl_button.setIcon(main_window.theme_manager.create_themed_icon(icon_path))
    wl_button._icon_path = icon_path

    wl_menu = QMenu(main_window)
    presets = [
        (main_window.tr("自动"), -1, -1),
        (main_window.tr("腹部"), 400, 50),
        (main_window.tr("脑窗"), 80, 40),
        (main_window.tr("骨窗"), 2000, 600),
        (main_window.tr("肺窗"), 1500, -600),
        (main_window.tr("纵隔"), 350, 50),
    ]
    for name, w, l in presets:
        action = QAction(name, main_window)
        action.triggered.connect(
            lambda checked=False, w=w, l=l: main_window._set_window_level_preset(w, l)
        )
        wl_menu.addAction(action)

    wl_menu.addSeparator()
    custom_action = QAction(main_window.tr("自定义..."), main_window)
    custom_action.triggered.connect(main_window._open_custom_wl_dialog)
    wl_menu.addAction(custom_action)

    wl_button.setMenu(wl_menu)

    def refresh_icon():
        icon_p = getattr(wl_button, '_icon_path', icon_path)
        wl_button.setIcon(main_window.theme_manager.create_themed_icon(icon_p))

    wl_button.refresh_icon = refresh_icon
    return wl_button


def create_transform_button(main_window) -> QToolButton:
    """创建图像变换按钮（翻转/旋转/反色）"""
    btn = QToolButton(main_window)
    btn.setToolTip(main_window.tr("图像变换"))
    _setup_menu_button(btn)

    icon_path = get_icon_path("transform.svg")
    btn.setIcon(main_window.theme_manager.create_themed_icon(icon_path))
    btn._icon_path = icon_path

    menu = QMenu(main_window)
    transforms = [
        (main_window.tr("水平翻转"), "flip_h"),
        (main_window.tr("垂直翻转"), "flip_v"),
        (main_window.tr("左旋90°"), "rotate_left"),
        (main_window.tr("右旋90°"), "rotate_right"),
        (main_window.tr("反色"), "invert"),
    ]
    for name, key in transforms:
        action = QAction(name, main_window)
        action.triggered.connect(
            lambda checked=False, k=key: main_window._apply_viewer_transform(k)
        )
        menu.addAction(action)

    menu.addSeparator()
    reset_action = QAction(main_window.tr("重置"), main_window)
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
    play_btn.setToolTip(main_window.tr("Cine 播放/暂停"))
    play_btn._icon_path = play_icon_path
    play_btn.setCheckable(True)
    _setup_button(play_btn)
    play_btn.toggled.connect(lambda checked: main_window._cine_toggle_play())
    layout.addWidget(play_btn)

    # 帧率控制
    fps_spin = QSpinBox(main_window)
    fps_spin.setRange(1, 60)
    fps_spin.setValue(10)
    fps_spin.setSuffix(" fps")
    fps_spin.setFixedWidth(72)
    fps_spin.setFixedHeight(_BTN_HEIGHT)
    fps_spin.valueChanged.connect(main_window._cine_set_fps)
    layout.addWidget(fps_spin)

    # 存储引用以便状态更新
    main_window._cine_play_btn = play_btn

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
    layout_button.setToolTip(main_window.tr("选择视图布局"))
    layout_button._icon_path = layout_icon_path
    
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
            layout_button.setToolTip(main_window.tr(f"当前布局: {rows}×{cols}"))
        else:
            layout_button.setToolTip(main_window.tr("当前布局: 特殊布局"))
    
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
    sync_button.setToolTip(main_window.tr("同步功能设置"))
    _setup_menu_button(sync_button)
    
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
    def set_sync_states(position_mode: str = "auto", pan: bool = False, 
                       zoom: bool = False, window_level: bool = False) -> None:
        sync_widget.set_sync_states(position_mode, pan, zoom, window_level)
    
    def get_sync_states() -> dict:
        return sync_widget.get_sync_states()
    
    def refresh_icon():
        """刷新图标以适应主题变化"""
        icon_path = getattr(sync_button, '_icon_path', chain_icon_path)
        if icon_path:
            new_icon = main_window.theme_manager.create_themed_icon(icon_path)
            sync_button.setIcon(new_icon)
    
    sync_button.set_sync_states = set_sync_states
    sync_button.get_sync_states = get_sync_states
    sync_button.refresh_icon = refresh_icon
    
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
        self._pan_checkbox = QCheckBox(self.tr("同步平移"))
        self._pan_checkbox.setFont(font)
        layout.addWidget(self._pan_checkbox)
        
        # 同步缩放
        self._zoom_checkbox = QCheckBox(self.tr("同步缩放"))
        self._zoom_checkbox.setFont(font)
        layout.addWidget(self._zoom_checkbox)
        
        # 同步窗宽窗位
        self._window_level_checkbox = QCheckBox(self.tr("同步窗宽窗位"))
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
        title_label = QLabel(self.tr("同步位置"))
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
        
        self._position_none_radio = QRadioButton(self.tr("否"))
        self._position_auto_radio = QRadioButton(self.tr("自动"))
        self._position_manual_radio = QRadioButton(self.tr("手动"))
        
        # 设置字体
        radio_font = QFont()
        radio_font.setPointSize(9)
        self._position_none_radio.setFont(radio_font)
        self._position_auto_radio.setFont(radio_font)
        self._position_manual_radio.setFont(radio_font)
        
        self._position_button_group.addButton(self._position_none_radio, 0)
        self._position_button_group.addButton(self._position_auto_radio, 1)
        self._position_button_group.addButton(self._position_manual_radio, 2)
        
        radio_layout.addWidget(self._position_none_radio)
        radio_layout.addWidget(self._position_auto_radio)
        radio_layout.addWidget(self._position_manual_radio)
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
        mode_map = {0: "none", 1: "auto", 2: "manual"}
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
        mode_map = {"none": 0, "auto": 1, "manual": 2}
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
        mode_map = {0: "none", 1: "auto", 2: "manual"}
        position_mode = mode_map.get(checked_id, "auto")
        
        states = {
            "position_mode": position_mode,
            "pan": self._pan_checkbox.isChecked(),
            "zoom": self._zoom_checkbox.isChecked(),
            "window_level": self._window_level_checkbox.isChecked()
        }
        
        logger.debug(f"[SyncDropdownWidget.get_sync_states] 获取同步状态: {states}")
        return states