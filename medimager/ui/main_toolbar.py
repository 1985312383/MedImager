from PySide6.QtWidgets import (QToolBar, QMenu, QToolButton, QVBoxLayout,
                              QHBoxLayout, QBoxLayout, QRadioButton, QButtonGroup,
                              QCheckBox, QLabel, QFrame, QWidget, QWidgetAction,
                              QSpinBox, QSizePolicy, QLayout)
from PySide6.QtGui import QAction, QColor, QIcon, QActionGroup, QFont, QPalette
from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal, QSignalBlocker

from medimager.utils.logger import get_logger
from medimager.utils.resource_path import get_icon_path
from medimager.utils.i18n import t

logger = get_logger(__name__)

# 工具栏统一尺寸常量
_ICON_SIZE = QSize(24, 24)
_MIN_CONTROL_EXTENT = 36


def _control_extent(icon_pixels: int) -> int:
    """Return one stable square tile size for a toolbar icon."""

    return max(_MIN_CONTROL_EXTENT, int(icon_pixels) + 12)


def _relative_luminance(color: QColor) -> float:
    """Return WCAG relative luminance for an opaque Qt color."""

    channels = (color.redF(), color.greenF(), color.blueF())
    linear = tuple(
        value / 12.92
        if value <= 0.04045
        else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _readable_theme_text(foreground: QColor, background: QColor) -> QColor:
    """Keep the theme text token unless it misses normal-text contrast."""

    if foreground.isValid() and _contrast_ratio(foreground, background) >= 4.5:
        return foreground
    candidates = (QColor("#000000"), QColor("#FFFFFF"))
    return max(candidates, key=lambda candidate: _contrast_ratio(candidate, background))


class ViewerToolbar(QToolBar):
    """Main toolbar contract used by MainWindow without viewer coupling."""

    interaction_mode_requested = Signal(str)
    viewer_command_requested = Signal(str)
    voi_option_requested = Signal(object)
    voi_menu_about_to_show = Signal()


class SquareSplitToolButton(QToolButton):
    """Square split control with its menu affordance inside the tile.

    ``QToolButton.MenuButtonPopup`` reserves a separate 14 px strip in Qt's
    toolbar style.  That makes split controls wider than every ordinary tool.
    DelayedPopup keeps the small corner indicator inside the button; this
    subclass restores an immediate menu hit target on the right edge while a
    click elsewhere continues to activate the currently selected sub-tool.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("splitDropdown", True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)

    def _menu_hit_rect(self) -> QRect:
        hotspot = max(11, min(15, self.width() // 3))
        return QRect(self.width() - hotspot, 0, hotspot, self.height())

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.menu() is not None
            and self._menu_hit_rect().contains(event.position().toPoint())
        ):
            event.accept()
            self.showMenu()
            return
        super().mousePressEvent(event)


class _ToolbarItemHost(QWidget):
    """Give QWidgetAction controls the same cross-axis alignment as QAction."""

    def __init__(self, child: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.child = child
        self.setObjectName(f"{child.objectName() or type(child).__name__}Host")
        self.setProperty("toolbarItemHost", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addWidget(child, 0, Qt.AlignmentFlag.AlignCenter)
        self._layout = layout
        self.set_orientation(Qt.Orientation.Horizontal)

    def set_orientation(self, orientation: Qt.Orientation) -> None:
        horizontal = orientation == Qt.Orientation.Horizontal
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed if horizontal else QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding if horizontal else QSizePolicy.Policy.Fixed,
        )
        setter = getattr(self.child, "set_orientation", None)
        if callable(setter):
            setter(orientation)
        self.updateGeometry()


class ActiveToolChip(QFrame):
    """Compact current-tool indicator with a QLabel compatibility anchor."""

    def __init__(
        self,
        parent: QWidget | None = None,
        theme_manager=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self.setObjectName("ActiveToolChipContainer")
        self.setProperty("toolbarGroup", "feedback")
        self.setProperty("toolbarRole", "feedback")
        self.setMinimumWidth(148)
        self.setMaximumWidth(196)
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(5)
        self._layout = layout

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("ActiveToolChipIcon")
        self.icon_label.setFixedSize(18, 18)
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)

        # Keep this exact QLabel name: older integrations locate it with
        # toolbar.findChild(QLabel, "ActiveToolChip").
        self.name_label = QLabel(self)
        self.name_label.setObjectName("ActiveToolChip")
        self.name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.name_label.setMinimumWidth(64)
        layout.addWidget(self.name_label, 1)

        self.shortcut_label = QLabel(self)
        self.shortcut_label.setObjectName("ActiveToolShortcutHint")
        self.shortcut_label.setAlignment(Qt.AlignCenter)
        self.shortcut_label.setMinimumWidth(22)
        layout.addWidget(self.shortcut_label)

        register_component = getattr(theme_manager, "register_component", None)
        if callable(register_component):
            register_component(self)
        else:
            self.update_theme("")

    def set_orientation(self, orientation: Qt.Orientation) -> None:
        """Keep the status chip compact and centered in either toolbar axis."""

        if orientation == Qt.Orientation.Vertical:
            self.setMinimumWidth(132)
            self.name_label.setMinimumWidth(48)
        else:
            self.setMinimumWidth(148)
            self.name_label.setMinimumWidth(64)
        self.setMaximumWidth(196)
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.updateGeometry()

    @staticmethod
    def _palette_color(value, fallback: QColor) -> QColor:
        color = QColor(str(value or ""))
        return color if color.isValid() else QColor(fallback)

    def update_theme(self, theme_name: str) -> None:
        """Apply explicit semantic colors instead of OS-dependent palette roles.

        ``ThemeManager`` intentionally themes through QSS and does not replace
        QApplication's native palette.  On a Windows dark desktop that palette
        can therefore still expose white ``Text`` while MedImager's light QSS
        uses a white surface.  Resolve the active theme tokens here and mirror
        them into the widget palettes so both native painting and QSS agree.
        """

        tokens = {}
        get_tokens = getattr(self._theme_manager, "get_theme_tokens", None)
        if callable(get_tokens):
            tokens = get_tokens(theme_name or None)

        native = self.palette()
        background = self._palette_color(
            tokens.get("surface_raised_color"),
            native.color(QPalette.ColorRole.AlternateBase),
        )
        shortcut_background = self._palette_color(
            tokens.get("surface_sunken_color"),
            native.color(QPalette.ColorRole.Base),
        )
        border = self._palette_color(
            tokens.get("border_color"),
            native.color(QPalette.ColorRole.Mid),
        )
        requested_text = self._palette_color(
            tokens.get("text_color"),
            native.color(QPalette.ColorRole.Text),
        )
        foreground = _readable_theme_text(requested_text, background)
        shortcut_foreground = _readable_theme_text(
            requested_text,
            shortcut_background,
        )

        foreground_css = foreground.name(QColor.NameFormat.HexRgb)
        background_css = background.name(QColor.NameFormat.HexRgb)
        shortcut_foreground_css = shortcut_foreground.name(QColor.NameFormat.HexRgb)
        shortcut_background_css = shortcut_background.name(QColor.NameFormat.HexRgb)
        border_css = border.name(QColor.NameFormat.HexRgb)
        self.setStyleSheet(
            "QFrame#ActiveToolChipContainer { padding: 0; border-radius: 5px; "
            f"border: 1px solid {border_css}; background-color: {background_css}; "
            f"color: {foreground_css}; }}"
            "QLabel#ActiveToolChipIcon { background-color: transparent; }"
            "QLabel#ActiveToolChip { background-color: transparent; "
            f"color: {foreground_css}; }}"
            "QLabel#ActiveToolShortcutHint { padding: 1px 4px; border-radius: 3px; "
            f"border: 1px solid {border_css}; background-color: {shortcut_background_css}; "
            f"color: {shortcut_foreground_css}; font-size: 9px; }}"
        )

        self._set_widget_palette(self, foreground, background)
        self._set_widget_palette(self.name_label, foreground, background)
        self._set_widget_palette(
            self.shortcut_label,
            shortcut_foreground,
            shortcut_background,
        )
        main_contrast = _contrast_ratio(foreground, background)
        shortcut_contrast = _contrast_ratio(
            shortcut_foreground,
            shortcut_background,
        )
        self.setProperty("contrastForeground", foreground_css)
        self.setProperty("contrastBackground", background_css)
        self.setProperty("shortcutContrastForeground", shortcut_foreground_css)
        self.setProperty("shortcutContrastBackground", shortcut_background_css)
        self.setProperty("minimumContrastRatio", min(main_contrast, shortcut_contrast))

    @staticmethod
    def _set_widget_palette(widget: QWidget, foreground: QColor, background: QColor) -> None:
        palette = widget.palette()
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            for role in (
                QPalette.ColorRole.Text,
                QPalette.ColorRole.WindowText,
                QPalette.ColorRole.ButtonText,
            ):
                palette.setColor(group, role, foreground)
            palette.setColor(group, QPalette.ColorRole.Window, background)
            palette.setColor(group, QPalette.ColorRole.Base, background)
            palette.setColor(group, QPalette.ColorRole.AlternateBase, background)
        widget.setPalette(palette)

    def set_tool(
        self, icon: QIcon, label: str, shortcut_hint: str = "", tool_name: str = ""
    ) -> None:
        label = str(label or "")
        shortcut_hint = str(shortcut_hint or "").strip()
        self.icon_label.setPixmap(icon.pixmap(QSize(18, 18)))
        self.icon_label.setVisible(not icon.isNull())
        self.name_label.setText(label)
        self.shortcut_label.setText(shortcut_hint)
        self.shortcut_label.setVisible(bool(shortcut_hint))
        self.setProperty("activeTool", str(tool_name or ""))
        self.setProperty("shortcutHint", shortcut_hint)

        description = label
        if shortcut_hint:
            description = f"{label} ({shortcut_hint})"
        tooltip = t("mainwindow.current_tool_value").replace("%1", description)
        self.setToolTip(tooltip)
        self.name_label.setToolTip(tooltip)
        self.icon_label.setToolTip(tooltip)
        self.shortcut_label.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setAccessibleDescription(tooltip)


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


def _themed_icon(
    main_window,
    icon_path: str,
    *,
    preserve_on_color: bool = False,
) -> QIcon:
    """Create a themed icon while supporting lightweight legacy stubs."""

    creator = main_window.theme_manager.create_themed_icon
    if preserve_on_color:
        try:
            return creator(icon_path, preserve_on_color=True)
        except TypeError:
            pass
    return creator(icon_path)


def _tag_toolbar_action(
    toolbar: QToolBar,
    action: QAction,
    group: str,
    shortcut_hint: str = "",
    *,
    role: str = "command",
) -> None:
    action.setProperty("toolbarGroup", group)
    action.setProperty("shortcutHint", shortcut_hint)
    action.setProperty("toolbarRole", role)
    label = action.text()
    if shortcut_hint:
        action.setToolTip(f"{label} ({shortcut_hint})")
    button = toolbar.widgetForAction(action)
    if button is not None:
        button.setProperty("toolbarGroup", group)
        button.setProperty("toolbarRole", role)
        button.setProperty("toolbarControl", True)
        _set_accessibility(button, label, action.toolTip() or label)


def _setup_button(btn: QToolButton):
    """统一设置普通工具按钮"""
    btn.setProperty("toolbarControl", True)
    btn.setIconSize(_ICON_SIZE)
    extent = _control_extent(_ICON_SIZE.width())
    btn.setFixedSize(extent, extent)

def _setup_split_dropdown(btn: QToolButton):
    """Configure a square split control without a width-consuming arrow strip."""
    btn.setProperty("splitDropdown", True)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
    btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
    _setup_button(btn)


def _setup_menu_button(btn: QToolButton):
    """整体式下拉按钮：点击按钮任意位置直接弹出菜单，右下角显示小三角指示。
    适用于窗宽窗位预设、图像变换、同步等纯菜单按钮。"""
    btn.setPopupMode(QToolButton.InstantPopup)
    btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
    _setup_button(btn)


def _add_toolbar_widget(
    toolbar: QToolBar,
    widget: QWidget,
    group: str,
    *,
    role: str = "command",
) -> QAction:
    """Add a custom control through a host that centers on the cross axis."""

    widget.setProperty("toolbarGroup", group)
    widget.setProperty("toolbarRole", role)
    host = _ToolbarItemHost(widget, toolbar)
    host.setProperty("toolbarGroup", group)
    host.setProperty("toolbarRole", role)
    action = toolbar.addWidget(host)
    action.setProperty("toolbarGroup", group)
    action.setProperty("toolbarRole", role)
    hosts = getattr(toolbar, "_custom_hosts", None)
    if hosts is None:
        hosts = []
        toolbar._custom_hosts = hosts
    hosts.append(host)
    return action


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
    toolbar.setProperty("logicalGroups", "browse,measure,compare,advanced")
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
    _tag_toolbar_action(toolbar, action, "browse", "P", role="mode")

    interaction_actions = {}
    for mode, icon_name, label, hint in (
        ("pan", "pan", t("mainwindow.pan"), "H"),
        ("zoom", "zoom_in", t("mainwindow.zoom"), "Z"),
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
        _tag_toolbar_action(toolbar, mode_action, "browse", hint, role="mode")

    toolbar.addSeparator()

    # 2. ROI工具按钮（带下拉菜单）
    roi_button = SquareSplitToolButton(main_window)
    roi_button.setObjectName("RoiToolButton")
    roi_button.setCheckable(True)
    _setup_split_dropdown(roi_button)

    ellipse_icon_path = get_icon_path("ellipse.svg")
    ellipse_icon = main_window.theme_manager.create_themed_icon(ellipse_icon_path)
    roi_button.setIcon(ellipse_icon)
    roi_button.setText(t("mainwindow.ellipse"))
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
    _add_toolbar_widget(toolbar, roi_button, "measure", role="mode")

    main_window.tool_actions["ellipse_roi"] = ellipse_action
    main_window.tool_actions["rectangle_roi"] = rect_action
    main_window.tool_actions["circle_roi"] = circle_action
    _set_accessibility(roi_button, t("mainwindow.select_roi_tool_type"))

    # 3. 测量工具按钮（带下拉菜单）
    measure_button = SquareSplitToolButton(main_window)
    measure_button.setObjectName("MeasurementToolButton")
    measure_button.setCheckable(True)
    _setup_split_dropdown(measure_button)

    ruler_icon_path = get_icon_path("ruler.svg")
    ruler_icon = main_window.theme_manager.create_themed_icon(ruler_icon_path)
    measure_button.setIcon(ruler_icon)
    measure_button.setText(t("mainwindow.line_measurement"))
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
    _add_toolbar_widget(toolbar, measure_button, "measure", role="mode")

    main_window.tool_actions["measurement"] = ruler_action
    main_window.tool_actions["angle"] = angle_action
    _set_accessibility(measure_button, t("mainwindow.measurement_tool"))

    toolbar.addSeparator()

    # 4. Window/level interaction and DICOM VOI presets
    wl_button = create_wl_preset_button(main_window, toolbar)
    _add_toolbar_widget(toolbar, wl_button, "browse", role="mode")

    for command, icon_name, label, hint in (
        ("fit", "fit", t("mainwindow.fit_image"), "F"),
        ("actual_size", "actual_size", t("mainwindow.actual_pixels"), "1"),
        ("reset_view", "reset", t("mainwindow.reset_view"), ""),
    ):
        command_action = QAction(_semantic_icon(main_window, icon_name), label, main_window)
        command_action.triggered.connect(
            lambda checked=False, requested=command: toolbar.viewer_command_requested.emit(requested)
        )
        toolbar.addAction(command_action)
        _tag_toolbar_action(toolbar, command_action, "browse", hint)

    # 5. Image transform menu
    transform_button = create_transform_button(main_window)
    _set_accessibility(transform_button, t("mainwindow.image_transform"))
    _add_toolbar_widget(toolbar, transform_button, "browse", role="menu")

    toolbar.addSeparator()

    # 6. 布局选择器按钮
    layout_button = create_layout_selector_button(main_window)
    _add_toolbar_widget(toolbar, layout_button, "compare", role="menu")

    # 7. Sync status and controls
    sync_button = create_sync_button(main_window)
    _add_toolbar_widget(toolbar, sync_button, "compare", role="sync")

    # Plane intersections and the patient-space cursor are independent
    # compare aids. Keep both discoverable instead of burying them in the
    # generic synchronization menu.
    try:
        from medimager.utils.settings import get_settings_manager

        compare_settings = getattr(main_window, "settings_manager", None)
        if compare_settings is None:
            compare_settings = get_settings_manager()
        reference_default = bool(
            compare_settings.get_setting("sync.reference_lines", True)
        )
        cursor_default = bool(
            compare_settings.get_setting("sync.shared_cursor", True)
        )
    except Exception:
        compare_settings = None
        reference_default = True
        cursor_default = True

    compare_toggle_actions = {}
    for key, name, icon_file, label, checked in (
        (
            "sync.reference_lines",
            "reference_lines",
            "reference-lines.svg",
            t("settingsdialog.sync_reference_lines"),
            reference_default,
        ),
        (
            "sync.shared_cursor",
            "shared_cursor",
            "shared-cursor.svg",
            t("settingsdialog.sync_shared_cursor"),
            cursor_default,
        ),
    ):
        icon_path = get_icon_path(icon_file)
        toggle = QAction(
            _themed_icon(main_window, icon_path, preserve_on_color=True),
            label,
            main_window,
        )
        toggle.setCheckable(True)
        toggle.setChecked(checked)
        toggle._icon_path = icon_path
        toggle._preserve_on_color = True
        toolbar.addAction(toggle)
        _tag_toolbar_action(toolbar, toggle, "compare", role="toggle")
        compare_toggle_actions[name] = toggle

        def _apply_compare_toggle(
            enabled=False,
            *,
            setting_key=key,
        ):
            if compare_settings is not None:
                compare_settings.set_setting(setting_key, bool(enabled))
            manager = getattr(main_window, "sync_manager", None)
            setter = getattr(manager, "set_cross_reference_visibility", None)
            if callable(setter):
                setter(
                    reference_lines=compare_toggle_actions[
                        "reference_lines"
                    ].isChecked(),
                    shared_cursor=compare_toggle_actions[
                        "shared_cursor"
                    ].isChecked(),
                )
            mode_getter = getattr(main_window, "_sync_mode_from_setting", None)
            if manager is not None and callable(mode_getter):
                manager.set_sync_mode(mode_getter())

        toggle.toggled.connect(_apply_compare_toggle)
    toolbar.reference_lines_action = compare_toggle_actions["reference_lines"]
    toolbar.shared_cursor_action = compare_toggle_actions["shared_cursor"]

    # 8. Orthogonal MPR workspace
    mpr_icon_path = get_icon_path('mpr.svg')
    mpr_action = QAction(
        _themed_icon(main_window, mpr_icon_path, preserve_on_color=True),
        t('mpr.enter'),
        main_window,
    )
    mpr_action.setCheckable(True)
    mpr_action.setEnabled(False)
    mpr_handler = getattr(main_window, '_toggle_mpr_workspace', None)
    if callable(mpr_handler):
        mpr_action.triggered.connect(mpr_handler)
    mpr_action._icon_path = mpr_icon_path
    mpr_action._preserve_on_color = True
    toolbar.addAction(mpr_action)
    _tag_toolbar_action(toolbar, mpr_action, 'advanced', 'M', role="toggle")
    main_window.mpr_action = mpr_action
    if not hasattr(main_window, '_image_required_actions'):
        main_window._image_required_actions = []
    main_window._image_required_actions.extend(
        [
            toolbar.reference_lines_action,
            toolbar.shared_cursor_action,
            mpr_action,
        ]
    )

    # 9. Cine playback
    cine_controls = create_cine_controls(main_window)
    _add_toolbar_widget(toolbar, cine_controls, "advanced", role="composite")

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

    toolbar.addSeparator()
    active_tool_chip = ActiveToolChip(
        toolbar,
        getattr(main_window, "theme_manager", None),
    )
    active_tool_action = _add_toolbar_widget(
        toolbar,
        active_tool_chip,
        "feedback",
        role="feedback",
    )
    _set_accessibility(active_tool_chip, t("mainwindow.current_tool"))

    def action_shortcut_hint(selected_action: QAction | None) -> str:
        if selected_action is None:
            return ""
        hint = str(selected_action.property("shortcutHint") or "").strip()
        if hint:
            return hint
        return selected_action.shortcut().toString().strip()

    def set_active_tool_feedback(tool_name: str) -> None:
        """Keep every interaction/annotation control visibly selected."""
        default_action.setChecked(tool_name == "default")
        for name, mode_action in interaction_actions.items():
            mode_action.setChecked(tool_name == name)
        wl_button.setChecked(tool_name == "window_level")
        roi_button.setChecked(tool_name in roi_tools)
        measure_button.setChecked(tool_name in measurement_tools)
        selected_action = main_window.tool_actions.get(tool_name)
        active_label = (
            selected_action.text()
            if selected_action is not None
            else t("mainwindow.pointer")
        )
        active_icon = (
            selected_action.icon()
            if selected_action is not None
            else default_action.icon()
        )
        shortcut_hint = action_shortcut_hint(selected_action)
        if tool_name == "window_level":
            active_label = t("toolbar.window_level")
            active_icon = wl_button.icon()
            shortcut_hint = "W"
        active_tool_chip.set_tool(
            active_icon,
            active_label,
            shortcut_hint,
            tool_name,
        )

    for tool_name, tool_action in main_window.tool_actions.items():
        tool_action.triggered.connect(
            lambda checked=False, name=tool_name: set_active_tool_feedback(name)
        )

    # Expose a small toolbar-level API for programmatic tool changes.
    toolbar.set_active_tool_feedback = set_active_tool_feedback
    toolbar.active_tool_chip = active_tool_chip
    toolbar.set_dicom_voi_options = wl_button.set_dicom_voi_options
    toolbar.set_cine_fps = cine_controls.set_fps
    toolbar.sync_button = sync_button
    set_active_tool_feedback("default")

    # QWidgetAction objects created by addWidget inherit their logical group
    # from the hosted widget so visibility and ordering have one source.
    for toolbar_action in toolbar.actions():
        widget = toolbar.widgetForAction(toolbar_action)
        if widget is not None and widget.property("toolbarGroup"):
            toolbar_action.setProperty(
                "toolbarGroup", widget.property("toolbarGroup")
            )

    grouped_actions = {}
    for toolbar_action in toolbar.actions():
        group = str(toolbar_action.property("toolbarGroup") or "")
        if group:
            grouped_actions.setdefault(group, []).append(toolbar_action)
    toolbar._group_actions = grouped_actions

    preference_state = {
        "icon_pixels": _ICON_SIZE.width(),
        "show_labels": False,
    }

    def _sync_action_widget_metadata() -> None:
        """Reapply metadata when Qt recreates QAction-backed buttons."""

        for toolbar_action in toolbar.actions():
            widget = toolbar.widgetForAction(toolbar_action)
            if not isinstance(widget, QToolButton):
                continue
            group = str(toolbar_action.property("toolbarGroup") or "")
            if not group:
                continue
            widget.setProperty("toolbarGroup", group)
            widget.setProperty(
                "toolbarRole",
                str(toolbar_action.property("toolbarRole") or "command"),
            )
            widget.setProperty("toolbarControl", True)
            _set_accessibility(
                widget,
                toolbar_action.text(),
                toolbar_action.toolTip() or toolbar_action.text(),
            )

    def _apply_control_geometry() -> None:
        """Apply one orientation-aware sizing and label strategy."""

        icon_pixels = int(preference_state["icon_pixels"])
        show_labels = bool(preference_state["show_labels"])
        orientation = toolbar.orientation()
        horizontal = orientation == Qt.Orientation.Horizontal
        icon_size_value = QSize(icon_pixels, icon_pixels)
        extent = _control_extent(icon_pixels)
        style = (
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            if horizontal
            else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        ) if show_labels else Qt.ToolButtonStyle.ToolButtonIconOnly

        toolbar.setIconSize(icon_size_value)
        toolbar.setToolButtonStyle(style)
        toolbar.setProperty("toolbarLabelsVisible", show_labels)
        toolbar.setProperty("toolbarControlExtent", extent)

        for host in getattr(toolbar, "_custom_hosts", ()):
            host.set_orientation(orientation)
        _sync_action_widget_metadata()

        controls = [
            button
            for button in toolbar.findChildren(QToolButton)
            if bool(button.property("toolbarControl"))
        ]
        for button in controls:
            button.setIconSize(icon_size_value)
            button.setToolButtonStyle(style)
            button.setMinimumSize(0, 0)
            button.setMaximumSize(16777215, 16777215)
            if not show_labels:
                button.setSizePolicy(
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Fixed,
                )
                button.setFixedSize(extent, extent)
            elif horizontal:
                button.setSizePolicy(
                    QSizePolicy.Policy.Preferred,
                    QSizePolicy.Policy.Fixed,
                )
                button.setMinimumWidth(extent)
                button.setFixedHeight(extent)

        if show_labels and not horizontal and controls:
            cell_width = max(extent, *(button.sizeHint().width() for button in controls))
            cell_height = max(extent, *(button.sizeHint().height() for button in controls))
            for button in controls:
                button.setSizePolicy(
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Fixed,
                )
                button.setFixedSize(cell_width, cell_height)

        main_window._cine_fps_spin.setFixedHeight(extent)
        toolbar.updateGeometry()
        toolbar.update()

    def apply_preferences(
        *,
        density: str = "compact",
        icon_size: int | None = None,
        show_labels: bool = False,
        visible_groups=None,
        group_order=None,
    ) -> None:
        density_pixels = {
            "compact": 24,
            "comfortable": 28,
            "standard": 28,
            "touch": 32,
        }.get(str(density), 24)
        try:
            icon_pixels = max(16, min(40, int(icon_size or density_pixels)))
        except (TypeError, ValueError):
            icon_pixels = density_pixels
        preference_state["icon_pixels"] = icon_pixels
        preference_state["show_labels"] = bool(show_labels)

        order = list(group_order or ("browse", "measure", "compare", "advanced"))
        order = [
            group for group in order
            if group in {"browse", "measure", "compare", "advanced"}
        ]
        for fallback in ("browse", "measure", "compare", "advanced"):
            if fallback not in order:
                order.append(fallback)
        visible = set(
            visible_groups
            or ("browse", "measure", "compare", "advanced")
        )

        for action in list(toolbar.actions()):
            toolbar.removeAction(action)
        # Keep the active-tool identity ahead of overflow-prone groups.  Qt
        # moves actions at the far end of a toolbar into its extension menu
        # first, so placing feedback last could collapse the icon/name/shortcut
        # to a few pixels at the canonical 1280px reading-workstation width.
        toolbar.addAction(active_tool_action)
        toolbar.addSeparator()
        added_visible_group = False
        for index, group in enumerate(order):
            actions = grouped_actions.get(group, ())
            group_is_visible = group in visible and bool(actions)
            if added_visible_group and group_is_visible:
                toolbar.addSeparator()
            for action in actions:
                action.setVisible(group in visible)
                toolbar.addAction(action)
            added_visible_group = added_visible_group or group_is_visible
        active_tool_chip.setVisible(True)
        toolbar.setProperty("groupOrder", ",".join(order))
        toolbar.setProperty("visibleGroups", ",".join(sorted(visible)))
        _apply_control_geometry()

    toolbar.apply_preferences = apply_preferences
    toolbar.apply_control_geometry = _apply_control_geometry
    toolbar.orientationChanged.connect(
        lambda _orientation: _apply_control_geometry()
    )
    try:
        from medimager.utils.settings import get_settings_manager

        settings = get_settings_manager()
        raw_order = settings.get_setting(
            "toolbar.group_order", ["browse", "measure", "compare", "advanced"]
        )
        if isinstance(raw_order, str):
            raw_order = [value for value in raw_order.split(",") if value]
        raw_visible = settings.get_setting(
            "toolbar.visible_groups",
            ["browse", "measure", "compare", "advanced"],
        )
        if isinstance(raw_visible, str):
            raw_visible = [value for value in raw_visible.split(",") if value]
        apply_preferences(
            density=str(settings.get_setting("ui.density", "compact")),
            icon_size=settings.get_setting("ui.icon_size", 24),
            show_labels=bool(
                settings.get_setting("toolbar.show_labels", False)
            ),
            visible_groups=raw_visible,
            group_order=raw_order,
        )
    except Exception:
        apply_preferences()
    set_active_tool_feedback("default")

    return toolbar


def _on_roi_tool_selected(main_window, roi_tool_button, action, tool_name):
    """当ROI工具被选中时，更新工具栏按钮并切换工具"""
    # 更新工具栏按钮的图标和文本
    roi_tool_button.setIcon(action.icon())
    roi_tool_button.setText(action.text())
    roi_tool_button.setToolTip(action.text())
    _set_accessibility(roi_tool_button, action.text())
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
    measure_button.setText(action.text())
    measure_button.setToolTip(action.text())
    _set_accessibility(measure_button, action.text())
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
    wl_button = SquareSplitToolButton(main_window)
    wl_button.setText(t("toolbar.window_level"))
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
            option_action = QAction(
                str(option.get("label") or t("toolbar.dicom_voi_fallback")),
                wl_menu,
            )
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
    btn.setText(t("mainwindow.image_transform"))
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
    layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
    container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # 播放/暂停按钮
    play_btn = QToolButton(main_window)
    play_icon_path = get_icon_path("play.svg")
    play_btn.setIcon(main_window.theme_manager.create_themed_icon(play_icon_path))
    play_btn.setText(t("mainwindow.cine_play_pause"))
    play_btn.setToolTip(t("mainwindow.cine_play_pause"))
    play_btn._icon_path = play_icon_path
    play_btn.setCheckable(True)
    _setup_button(play_btn)
    play_btn.toggled.connect(lambda checked: main_window._cine_toggle_play())
    layout.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignCenter)

    # 帧率控制
    fps_spin = QSpinBox(main_window)
    fps_spin.setRange(1, 60)
    fps_spin.setValue(max(1, min(60, int(getattr(main_window, "_cine_fps", 10)))))
    fps_spin.setSuffix(t("settingsdialog.fps_suffix"))
    fps_spin.setFixedWidth(72)
    fps_spin.setFixedHeight(_control_extent(_ICON_SIZE.width()))
    fps_spin.valueChanged.connect(main_window._cine_set_fps)
    layout.addWidget(fps_spin, 0, Qt.AlignmentFlag.AlignCenter)

    # 存储引用以便状态更新
    main_window._cine_play_btn = play_btn
    main_window._cine_fps_spin = fps_spin
    _set_accessibility(play_btn, t("mainwindow.cine_play_pause"), "Space")
    frame_rate_name = t("toolbar.cine.frame_rate")
    if frame_rate_name == "toolbar.cine.frame_rate":
        frame_rate_name = t("settingsdialog.default_frame_rate").rstrip(":：")
    fps_spin.setAccessibleName(frame_rate_name)
    fps_spin.setAccessibleDescription(frame_rate_name)
    fps_spin.setToolTip(frame_rate_name)

    def set_fps(value: int) -> None:
        blocker = QSignalBlocker(fps_spin)
        fps_spin.setValue(max(1, min(60, int(value))))
        del blocker

    container.set_fps = set_fps

    def set_orientation(orientation: Qt.Orientation) -> None:
        layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if orientation == Qt.Orientation.Horizontal
            else QBoxLayout.Direction.TopToBottom
        )
        container.updateGeometry()
        container.adjustSize()

    container.set_orientation = set_orientation

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
    layout_button.setText(t("mainwindow.select_view_layout"))
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
            preset_handler = getattr(
                main_window, "_apply_layout_preset_by_id", None
            )
            if callable(preset_handler):
                layout_dropdown.preset_requested.connect(preset_handler)
            save_handler = getattr(main_window, "_save_current_layout_preset", None)
            if callable(save_handler):
                layout_dropdown.save_current_requested.connect(save_handler)
            favorite_handler = getattr(
                main_window, "_toggle_layout_favorite", None
            )
            if callable(favorite_handler):
                layout_dropdown.favorite_toggled.connect(favorite_handler)
            layout_button._dropdown = layout_dropdown

        mpr_action = getattr(main_window, "mpr_action", None)
        reason = ""
        if mpr_action is not None:
            reason = mpr_action.toolTip() or mpr_action.statusTip()
            layout_button._dropdown.set_mpr_availability(
                mpr_action.isEnabled(), reason
            )
        layout_store = getattr(main_window, "_user_layout_store", None)
        if layout_store is not None:
            layout_button._dropdown.set_user_presets(layout_store.load())
        
        global_pos = layout_button.mapToGlobal(QPoint(0, layout_button.height()))
        layout_button._dropdown.show_at_position(global_pos)
    
    layout_button.clicked.connect(on_layout_button_clicked)
    
    def set_current_layout(layout_config):
        """设置当前布局显示"""
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            tooltip = (
                t("layoutselectorbutton.current_layout_size").replace("%1", str(rows)).replace("%2", str(cols))
            )
        else:
            tooltip = t("layoutselectorbutton.current_layout_special_layout")
        layout_button.setToolTip(tooltip)
        layout_button.setAccessibleDescription(tooltip)
    
    layout_button.set_current_layout = set_current_layout
    
    def refresh_icon():
        """刷新图标以适应主题变化"""
        icon_path = getattr(layout_button, '_icon_path', layout_icon_path)
        layout_icon = main_window.theme_manager.create_themed_icon(icon_path)
        layout_button.setIcon(layout_icon)
    
    layout_button.refresh_icon = refresh_icon
    main_window.layout_selector_button = layout_button
    
    return layout_button


def create_sync_button(main_window) -> QToolButton:
    """创建同步按钮"""
    sync_button = QToolButton(main_window)
    sync_button.setText(t("mainwindow.sync_settings"))
    sync_button.setToolTip(t("mainwindow.sync_settings"))
    sync_button.setCheckable(True)
    sync_button.setProperty("syncState", "partial")
    _setup_menu_button(sync_button)
    _set_accessibility(sync_button, t("mainwindow.sync_settings"))
    
    chain_icon_path = get_icon_path("chain.svg")
    sync_button.setIcon(
        _themed_icon(main_window, chain_icon_path, preserve_on_color=True)
    )
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
        state_label = t(f"toolbar.sync.state_{summary}")
        sync_button.setProperty("syncState", summary)
        sync_button.setChecked(summary != "off")
        sync_button.setToolTip(t("toolbar.sync.summary", state=state_label))
        sync_button.setAccessibleName(t("mainwindow.sync_settings"))
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
            new_icon = _themed_icon(
                main_window,
                icon_path,
                preserve_on_color=True,
            )
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
