#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置对话框

根据设计文档重构的设置界面，包含左侧导航栏和右侧内容区。
"""

import toml
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QListWidget,
    QStackedWidget,
    QLabel,
    QColorDialog,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QFrame,
    QDialogButtonBox,
    QListWidgetItem,
    QScrollArea,
    QLineEdit,
    QMessageBox,
    QAbstractItemView,
)
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPixmap, QIcon
from typing import Dict, Any
from medimager.utils.settings import SettingsManager
from medimager.utils.i18n import get_translation_manager, t
from medimager.utils.logger import get_logger
from medimager.utils.theme_colors import qcolor_from_theme, qcolor_to_theme
from medimager.utils.theme_manager import get_user_themes_dir
from medimager.core.privacy import get_privacy_service
from medimager.core.settings_registry import (
    ApplyPolicy,
    DEFAULT_SETTINGS_REGISTRY,
    SettingsSession,
)
from medimager.core.storage_cleanup import StorageCategory, StorageCleanupService
from medimager.utils.resource_path import get_icon_path

logger = get_logger(__name__)


SIMPLE_SETTING_KEYS = (
    "ui.density",
    "ui.icon_size",
    "ui.font_scale",
    "toolbar.group_order",
    "toolbar.visible_groups",
    "toolbar.show_labels",
    "display.window_level_strategy",
    "display.smooth_interpolation",
    "display.show_view_title",
    "display.show_view_status",
    "overlay.show_orientation",
    "overlay.show_slice_position",
    "overlay.show_scale",
    "overlay.show_patient",
    "overlay.show_pixel_value",
    "interaction.left_drag_action",
    "interaction.middle_drag_action",
    "interaction.right_drag_action",
    "interaction.wheel_reverse",
    "cine.default_fps",
    "dicom.recursive_scan",
    "dicom.include_extensionless",
    "dicom.strict_metadata",
    "roi.stats.show_mean",
    "roi.stats.show_std",
    "roi.stats.show_max",
    "roi.stats.show_min",
    "roi.stats.show_area",
    "roi.stats.show_count",
    "roi.stats.area_unit",
    "multiview.default_layout",
    "multiview.default_sync_mode",
    "multiview.sync_group",
    "sync.position_mode",
    "sync.window_level",
    "sync.zoom",
    "sync.pan",
    "sync.reference_lines",
    "sync.shared_cursor",
    "workspace.startup_mode",
    "workspace.default_hanging_protocol",
    "workspace.history_limit",
    "workspace.restore_mpr",
    "recent_studies.max_items",
    "privacy.screen_mode",
    "cache.thumbnail.max_items",
    "cache.thumbnail.max_age_days",
    "cache.demo.keep",
)
SIMPLE_SETTING_DEFAULTS = {
    key: DEFAULT_SETTINGS_REGISTRY.require(key).default for key in SIMPLE_SETTING_KEYS
}


def _tr(key: str, fallback: str) -> str:
    translated = t(key)
    return fallback if translated == key else translated


class StringListEditor(QListWidget):
    """Compact editor for ordered or checkable lists of stable string values."""

    valueChanged = Signal()

    def __init__(self, items, *, checkable: bool = False, parent=None):
        super().__init__(parent)
        self._checkable = bool(checkable)
        self.setMaximumHeight(116)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if not self._checkable:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        for value, label in items:
            item = QListWidgetItem(label, self)
            item.setData(Qt.ItemDataRole.UserRole, value)
            if self._checkable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
        self.itemChanged.connect(lambda _item: self.valueChanged.emit())
        self.model().rowsMoved.connect(lambda *_args: self.valueChanged.emit())

    def setValue(self, values) -> None:
        normalized = [str(value) for value in (values or ())]
        blocker = QSignalBlocker(self)
        try:
            if self._checkable:
                selected = set(normalized)
                for row in range(self.count()):
                    item = self.item(row)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if str(item.data(Qt.ItemDataRole.UserRole)) in selected
                        else Qt.CheckState.Unchecked
                    )
                return
            items = {
                str(self.item(row).data(Qt.ItemDataRole.UserRole)): self.takeItem(row)
                for row in range(self.count() - 1, -1, -1)
            }
            for value in normalized:
                item = items.pop(value, None)
                if item is not None:
                    self.addItem(item)
            for item in reversed(tuple(items.values())):
                self.addItem(item)
        finally:
            del blocker

    def value(self) -> list[str]:
        values = []
        for row in range(self.count()):
            item = self.item(row)
            if self._checkable and item.checkState() is not Qt.CheckState.Checked:
                continue
            values.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return values


class ColorButton(QPushButton):
    """带颜色图标的颜色选择按钮"""

    colorChanged = Signal(QColor)

    def __init__(self, color: QColor = None, parent=None):
        super().__init__(parent)
        self._color = color or QColor(255, 255, 255)
        self.setText(t("colorbutton.select"))
        self.clicked.connect(self._choose_color)
        self._update_color_icon()

    def color(self) -> QColor:
        return self._color

    def setColor(self, color: QColor):
        if color.isValid():
            self._color = color
            self._update_color_icon()
            # 同时在按钮文本中显示颜色值
            color_text = qcolor_to_theme(color)
            if color.alpha() == 255:
                color_text = color_text[:7]
            self.setText(f"{t('colorbutton.select')} ({color_text})")
            self.colorChanged.emit(color)

    def _update_color_icon(self):
        """更新按钮上的颜色图标"""
        pixmap = QPixmap(24, 24)
        pixmap.fill(self._color)

        # 添加黑色边框以增强可见性
        from PySide6.QtGui import QPainter, QPen

        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawRect(0, 0, 23, 23)
        painter.end()

        # 创建一个在禁用状态下也能正常显示的图标
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Normal)
        icon.addPixmap(pixmap, QIcon.Disabled)  # 禁用状态下也使用相同的图标
        self.setIcon(icon)

    def _choose_color(self):
        """打开颜色选择对话框"""
        color = QColorDialog.getColor(
            self._color,
            self,
            t("colorbutton.select_color"),
            QColorDialog.ShowAlphaChannel,
        )
        if color.isValid():
            self.setColor(color)


class SettingsDialog(QDialog):
    """设置对话框，采用左侧导航布局"""

    settings_applied = Signal(object)

    def __init__(self, settings_manager: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.translation_manager = get_translation_manager()
        self._language_changed = False
        self._original_ui_theme = self.settings_manager.get_setting("ui_theme", "dark")
        self.privacy_service = get_privacy_service(self.settings_manager)
        self.storage_service = StorageCleanupService(self.settings_manager, self)
        self.settings_session = SettingsSession(
            self.settings_manager, self._apply_live_setting
        )
        self._modified_keys: set[str] = set()
        self._page_records = []
        self._storage_labels = {}
        self.setWindowTitle(t("settingsdialog.settings"))
        self.setMinimumSize(560, 420)
        preferred_width, preferred_height = 900, 700
        screen = (
            QGuiApplication.screenAt(self.cursor().pos())
            or QGuiApplication.primaryScreen()
        )
        if screen is not None:
            available = screen.availableGeometry()
            preferred_width = min(
                preferred_width, max(560, int(available.width() * 0.9))
            )
            preferred_height = min(
                preferred_height, max(420, int(available.height() * 0.9))
            )
        self.resize(preferred_width, preferred_height)
        self.setModal(True)

        # 存储所有主题数据
        self.themes: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # 存储所有设置控件
        self.setting_widgets: Dict[str, QWidget] = {}

        # 获取支持的语言
        self.supported_languages = self._get_supported_languages()

        self._init_ui()
        self._load_themes()
        self._load_current_settings()
        self._connect_change_tracking()
        self._update_change_status()

    def _get_supported_languages(self) -> Dict[str, str]:
        """自动检测支持的语言

        Returns:
            Dict[str, str]: 语言代码到显示名称的映射
        """
        return {
            info.code: info.name
            for info in self.translation_manager.available_language_info()
        }

    def _init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(
            _tr("settingsdialog.search_placeholder", "Search settings")
        )
        self.search_edit.setAccessibleName(self.search_edit.placeholderText())
        self.search_edit.textChanged.connect(self._filter_pages)
        search_row.addWidget(self.search_edit, 1)
        self.change_status_label = QLabel(self)
        self.change_status_label.setObjectName("settingsChangeStatus")
        search_row.addWidget(self.change_status_label)
        self.restart_badge = QLabel(self)
        self.restart_badge.setObjectName("settingsRestartBadge")
        self.restart_badge.setStyleSheet(
            "padding: 3px 7px; border: 1px solid palette(mid); border-radius: 8px;"
        )
        search_row.addWidget(self.restart_badge)
        main_layout.addLayout(search_row)
        content_layout = QHBoxLayout()

        # 左侧导航栏
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("settings_nav")  # 为主题样式设置ID
        # Eight fixed categories include deliberately descriptive names.  Give
        # them enough room at the 1280 release target and keep compact-window
        # behavior deterministic without a distracting horizontal scrollbar.
        self.nav_list.setMinimumWidth(216)
        self.nav_list.setMaximumWidth(260)
        self.nav_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.nav_list.setTextElideMode(Qt.TextElideMode.ElideRight)

        # 右侧内容区
        self.stacked_widget = QStackedWidget()

        content_layout.addWidget(self.nav_list)
        content_layout.addWidget(self.stacked_widget, 1)
        main_layout.addLayout(content_layout)

        # Settings Center 2.0 uses a stable information architecture. Keep this
        # order aligned with the product specification and focused UI tests.
        self._add_page(t("settingsdialog.general"), self._create_general_page)
        self._add_page(
            _tr("settingsdialog.workspace", "Workspace and startup"),
            self._create_workspace_page,
        )
        self._add_page(
            _tr("settingsdialog.privacy", "Display and privacy"),
            self._create_display_privacy_page,
        )
        self._add_page(t("settingsdialog.interaction"), self._create_interaction_page)
        self._add_page(
            _tr("settingsdialog.dicom_sources", "DICOM and sources"),
            self._create_dicom_page,
        )
        self._add_page(
            _tr(
                "settingsdialog.multiview_sync",
                "Multi-view and synchronization",
            ),
            self._create_multiview_page,
        )
        self._add_page(
            _tr("settingsdialog.tools_annotations", "Tools and annotations"),
            self._create_tools_page,
        )
        self._add_page(
            _tr(
                "settingsdialog.performance_storage",
                "Performance and storage",
            ),
            self._create_performance_page,
        )

        # currentRowChanged 同时覆盖鼠标、方向键和辅助技术导航。
        self.nav_list.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

        # 按钮栏
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
            | QDialogButtonBox.Apply
            | QDialogButtonBox.RestoreDefaults
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        self.button_box.button(QDialogButtonBox.Apply).clicked.connect(
            self._apply_without_close
        )

        # 手动设置按钮文本，确保翻译正确
        self._update_button_text()

        main_layout.addWidget(self.button_box)

    def _add_page(self, name: str, creation_func):
        """Add a searchable page with an independent defaults action."""
        item = QListWidgetItem(name)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        icon_names = {
            "_create_general_page": "setting.svg",
            "_create_display_page": "contrast.svg",
            "_create_display_privacy_page": "contrast.svg",
            "_create_interaction_page": "click.svg",
            "_create_dicom_page": "folder-open.svg",
            "_create_tools_page": "ruler.svg",
            "_create_multiview_page": "layout.svg",
            "_create_workspace_page": "panel-left.svg",
            "_create_privacy_page": "warning.svg",
            "_create_performance_page": "reset.svg",
        }
        icon_name = icon_names.get(getattr(creation_func, "__name__", ""))
        if icon_name:
            icon_path = get_icon_path(icon_name)
            theme_manager = getattr(self.parent(), "theme_manager", None)
            create_icon = getattr(theme_manager, "create_themed_icon", None)
            item.setIcon(
                create_icon(icon_path) if callable(create_icon) else QIcon(icon_path)
            )
        self.nav_list.addItem(item)

        before = set(self.setting_widgets)
        page = creation_func()
        page_keys = tuple(key for key in self.setting_widgets if key not in before)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        defaults_row = QHBoxLayout()
        defaults_row.addStretch(1)
        page_defaults = QPushButton(
            _tr("settingsdialog.restore_page_defaults", "Restore page defaults")
        )
        page_defaults.clicked.connect(
            lambda _checked=False, keys=page_keys: self._restore_page_defaults(keys)
        )
        defaults_row.addWidget(page_defaults)
        wrapper_layout.addLayout(defaults_row)
        wrapper_layout.addWidget(page)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setWidget(wrapper)
        self.stacked_widget.addWidget(scroll_area)
        self._page_records.append((item, scroll_area, wrapper, name, page_keys))

    def _filter_pages(self, query: str) -> None:
        needle = query.strip().casefold()
        first_visible = None
        current_visible = False
        for row, (item, _scroll, page, name, _keys) in enumerate(self._page_records):
            parts = [name]
            for widget in page.findChildren(QWidget):
                text_getter = getattr(widget, "text", None)
                if callable(text_getter):
                    try:
                        parts.append(str(text_getter()))
                    except TypeError:
                        pass
                parts.append(str(widget.toolTip() or ""))
                if isinstance(widget, QComboBox):
                    parts.extend(
                        widget.itemText(index) for index in range(widget.count())
                    )
            visible = not needle or needle in " ".join(parts).casefold()
            item.setHidden(not visible)
            if visible and first_visible is None:
                first_visible = row
            if visible and self.nav_list.currentRow() == row:
                current_visible = True
        if not current_visible and first_visible is not None:
            self.nav_list.setCurrentRow(first_visible)

    def _create_general_page(self) -> QWidget:
        """创建通用设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        # 页面标题
        title_label = QLabel(t("settingsdialog.general_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        # 界面语言
        language_group = QGroupBox(t("settingsdialog.interface_language"))
        language_layout = QFormLayout(language_group)

        language_combo = QComboBox()
        # 自动添加支持的语言
        for lang_code, display_name in self.supported_languages.items():
            language_combo.addItem(display_name, lang_code)
        self.setting_widgets["language"] = language_combo

        # 移除语言切换的即时刷新信号
        # language_combo.currentTextChanged.connect(self._on_language_changed)

        language_layout.addRow(t("settingsdialog.language"), language_combo)
        layout.addWidget(language_group)

        # 界面主题
        ui_theme_group = QGroupBox(t("settingsdialog.interface_theme"))
        ui_theme_layout = QFormLayout(ui_theme_group)

        ui_theme_combo = QComboBox()
        self.setting_widgets["ui_theme"] = ui_theme_combo

        ui_theme_layout.addRow(t("settingsdialog.subject"), ui_theme_combo)
        layout.addWidget(ui_theme_group)

        # 连接UI主题变化处理逻辑
        def on_ui_theme_changed(index):
            theme_name = ui_theme_combo.itemData(index)
            if theme_name:
                # 预览主题变化；如果用户取消，会在 reject() 中恢复原主题。
                main_window = self.parent()
                if hasattr(main_window, "theme_manager"):
                    main_window.theme_manager.set_theme(theme_name)

        ui_theme_combo.currentIndexChanged.connect(on_ui_theme_changed)

        appearance_group = QGroupBox(
            _tr("settingsdialog.interface_density", "Interface density and scale")
        )
        appearance_layout = QFormLayout(appearance_group)
        density_combo = QComboBox()
        density_combo.addItem(
            _tr("settingsdialog.density_compact", "Professional compact"),
            "compact",
        )
        density_combo.addItem(
            _tr("settingsdialog.density_comfortable", "Comfortable"),
            "comfortable",
        )
        self.setting_widgets["ui.density"] = density_combo
        appearance_layout.addRow(
            _tr("settingsdialog.ui_density", "UI density"), density_combo
        )

        icon_size = QSpinBox()
        icon_size.setRange(16, 40)
        icon_size.setSuffix(" px")
        self.setting_widgets["ui.icon_size"] = icon_size
        appearance_layout.addRow(
            _tr("settingsdialog.icon_size", "Toolbar icon size"), icon_size
        )

        font_scale = QSpinBox()
        font_scale.setRange(80, 150)
        font_scale.setSuffix("%")
        self.setting_widgets["ui.font_scale"] = font_scale
        appearance_layout.addRow(
            _tr("settingsdialog.font_scale", "Font scale"), font_scale
        )
        layout.addWidget(appearance_group)

        layout.addStretch()
        return page

    def _create_tools_page(self) -> QWidget:
        """创建工具设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        # 页面标题
        title_label = QLabel(t("settingsdialog.tool_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        # ROI设置
        roi_group = self._create_roi_settings_group()
        layout.addWidget(roi_group)

        # 测量工具设置
        measurement_group = self._create_measurement_settings_group()
        layout.addWidget(measurement_group)

        toolbar_group = QGroupBox(
            _tr("settingsdialog.toolbar_configuration", "Toolbar configuration")
        )
        toolbar_form = QFormLayout(toolbar_group)
        show_labels = QCheckBox(
            _tr("settingsdialog.toolbar_show_labels", "Show toolbar text labels")
        )
        self.setting_widgets["toolbar.show_labels"] = show_labels
        toolbar_form.addRow(show_labels)

        group_items = (
            ("browse", _tr("settingsdialog.toolbar_group_browse", "Browse")),
            ("measure", _tr("settingsdialog.toolbar_group_measure", "Measure")),
            ("compare", _tr("settingsdialog.toolbar_group_compare", "Compare")),
            ("advanced", _tr("settingsdialog.toolbar_group_advanced", "Advanced")),
        )
        group_order = StringListEditor(group_items)
        group_order.setToolTip(
            _tr(
                "settingsdialog.toolbar_group_order_hint",
                "Drag groups to set their toolbar order.",
            )
        )
        self.setting_widgets["toolbar.group_order"] = group_order
        toolbar_form.addRow(
            _tr("settingsdialog.toolbar_group_order", "Group order"), group_order
        )

        visible_groups = StringListEditor(group_items, checkable=True)
        browse_item = visible_groups.item(0)
        browse_item.setFlags(browse_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        self.setting_widgets["toolbar.visible_groups"] = visible_groups
        toolbar_form.addRow(
            _tr("settingsdialog.toolbar_visible_groups", "Visible groups"),
            visible_groups,
        )
        layout.addWidget(toolbar_group)

        layout.addStretch()
        return page

    def _create_display_page(self) -> QWidget:
        """创建显示设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        title_label = QLabel(t("settingsdialog.display_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        image_group = QGroupBox(t("settingsdialog.image_display"))
        image_layout = QFormLayout(image_group)
        wl_combo = QComboBox()
        wl_combo.addItem(t("settingsdialog.prefer_dicom_tags"), "dicom")
        wl_combo.addItem(t("settingsdialog.auto_calculate_by_pixel_range"), "auto")
        wl_combo.addItem(t("settingsdialog.fixed_default_400_40"), "fixed")
        self.setting_widgets["display.window_level_strategy"] = wl_combo
        image_layout.addRow(t("settingsdialog.default_window_level"), wl_combo)

        smooth_check = QCheckBox(t("settingsdialog.smooth_interpolation_on_zoom"))
        self.setting_widgets["display.smooth_interpolation"] = smooth_check
        image_layout.addRow(smooth_check)
        layout.addWidget(image_group)

        chrome_group = QGroupBox(t("settingsdialog.view_information"))
        chrome_layout = QFormLayout(chrome_group)
        title_check = QCheckBox(t("settingsdialog.show_view_title_bar"))
        self.setting_widgets["display.show_view_title"] = title_check
        chrome_layout.addRow(title_check)

        status_check = QCheckBox(t("settingsdialog.show_view_status_bar"))
        self.setting_widgets["display.show_view_status"] = status_check
        chrome_layout.addRow(status_check)
        layout.addWidget(chrome_group)

        overlay_group = QGroupBox(
            _tr("settingsdialog.image_overlays", "Image overlays")
        )
        overlay_layout = QVBoxLayout(overlay_group)
        for key, label in (
            (
                "overlay.show_orientation",
                _tr("settingsdialog.overlay_orientation", "Anatomical orientation"),
            ),
            (
                "overlay.show_slice_position",
                _tr("settingsdialog.overlay_slice_position", "Slice position"),
            ),
            ("overlay.show_scale", _tr("settingsdialog.overlay_scale", "Scale ruler")),
            (
                "overlay.show_patient",
                _tr("settingsdialog.overlay_patient", "Patient information"),
            ),
            (
                "overlay.show_pixel_value",
                _tr("settingsdialog.overlay_pixel_value", "Pixel value under pointer"),
            ),
        ):
            checkbox = QCheckBox(label)
            self.setting_widgets[key] = checkbox
            overlay_layout.addWidget(checkbox)
        layout.addWidget(overlay_group)

        layout.addStretch()
        return page

    def _create_display_privacy_page(self) -> QWidget:
        """Compose display and privacy controls into one searchable category."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        display_page = self._create_display_page()
        display_page.setObjectName("settingsDisplaySection")
        privacy_page = self._create_privacy_page()
        privacy_page.setObjectName("settingsPrivacySection")
        layout.addWidget(display_page)
        layout.addWidget(privacy_page)
        return page

    def _create_interaction_page(self) -> QWidget:
        """创建交互设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        title_label = QLabel(t("settingsdialog.interaction_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        mouse_group = QGroupBox(t("settingsdialog.mouse_drag"))
        mouse_layout = QFormLayout(mouse_group)
        action_items = [
            (t("settingsdialog.browse_slices"), "browse"),
            (t("settingsdialog.window_level"), "window"),
            (t("settingsdialog.zoom"), "zoom"),
            (t("settingsdialog.pan"), "pan"),
            (t("settingsdialog.no_action"), "none"),
        ]
        for key, label in [
            ("interaction.left_drag_action", t("settingsdialog.left_button_drag")),
            ("interaction.middle_drag_action", t("settingsdialog.middle_button_drag")),
            ("interaction.right_drag_action", t("settingsdialog.right_button_drag")),
        ]:
            combo = QComboBox()
            for text, value in action_items:
                combo.addItem(text, value)
            self.setting_widgets[key] = combo
            mouse_layout.addRow(label, combo)

        wheel_reverse = QCheckBox(t("settingsdialog.invert_wheel_slice_direction"))
        self.setting_widgets["interaction.wheel_reverse"] = wheel_reverse
        mouse_layout.addRow(wheel_reverse)
        layout.addWidget(mouse_group)

        cine_group = QGroupBox(t("settingsdialog.cine_playback"))
        cine_layout = QFormLayout(cine_group)
        fps_spin = QSpinBox()
        fps_spin.setRange(1, 60)
        fps_spin.setSuffix(t("settingsdialog.fps_suffix"))
        self.setting_widgets["cine.default_fps"] = fps_spin
        cine_layout.addRow(t("settingsdialog.default_frame_rate"), fps_spin)
        layout.addWidget(cine_group)

        layout.addStretch()
        return page

    def _create_dicom_page(self) -> QWidget:
        """创建 DICOM 加载设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        title_label = QLabel(t("settingsdialog.dicom_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        scan_group = QGroupBox(t("settingsdialog.folder_scan"))
        scan_layout = QFormLayout(scan_group)
        recursive_check = QCheckBox(t("settingsdialog.scan_subfolders_recursively"))
        self.setting_widgets["dicom.recursive_scan"] = recursive_check
        scan_layout.addRow(recursive_check)

        extensionless_check = QCheckBox(t("settingsdialog.include_extensionless_files"))
        self.setting_widgets["dicom.include_extensionless"] = extensionless_check
        scan_layout.addRow(extensionless_check)

        strict_check = QCheckBox(t("settingsdialog.strict_metadata_mode"))
        self.setting_widgets["dicom.strict_metadata"] = strict_check
        scan_layout.addRow(strict_check)
        layout.addWidget(scan_group)

        decoder_group = QGroupBox(t("settingsdialog.compressed_dicom_decoding"))
        decoder_layout = QVBoxLayout(decoder_group)
        decoder_layout.addWidget(QLabel(self._get_decoder_status_text()))
        layout.addWidget(decoder_group)

        layout.addStretch()
        return page

    def _create_multiview_page(self) -> QWidget:
        """创建多视图设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        title_label = QLabel(t("settingsdialog.multi_view_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        layout_group = QGroupBox(t("settingsdialog.default_layout"))
        layout_form = QFormLayout(layout_group)
        default_layout_combo = QComboBox()
        for text, value in [
            ("1 x 1", "1x1"),
            ("1 x 2", "1x2"),
            ("2 x 1", "2x1"),
            ("2 x 2", "2x2"),
        ]:
            default_layout_combo.addItem(text, value)
        self.setting_widgets["multiview.default_layout"] = default_layout_combo
        layout_form.addRow(t("settingsdialog.startup_layout"), default_layout_combo)
        layout.addWidget(layout_group)

        sync_group = QGroupBox(t("settingsdialog.default_sync"))
        sync_form = QFormLayout(sync_group)
        sync_combo = QComboBox()
        sync_combo.addItem(t("settingsdialog.close"), "none")
        sync_combo.addItem(t("settingsdialog.basic_slice_window_level"), "basic")
        sync_combo.addItem(t("settingsdialog.advanced_basic_zoom_pan"), "advanced")
        sync_combo.addItem(t("settingsdialog.full_advanced_cross_reference"), "full")
        self.setting_widgets["multiview.default_sync_mode"] = sync_combo
        sync_form.addRow(t("settingsdialog.sync_mode"), sync_combo)

        sync_scope_combo = QComboBox()
        sync_scope_combo.addItem(
            t("settingsdialog.sync_scope_same_study"), "same_study"
        )
        sync_scope_combo.addItem(
            t("settingsdialog.sync_scope_same_patient"), "same_patient"
        )
        sync_scope_combo.addItem(
            t("settingsdialog.sync_scope_same_modality"), "same_modality"
        )
        sync_scope_combo.addItem(t("settingsdialog.sync_scope_all_views"), "all_views")
        sync_scope_combo.setToolTip(t("settingsdialog.sync_scope_safety_hint"))
        self.setting_widgets["multiview.sync_group"] = sync_scope_combo
        sync_form.addRow(t("settingsdialog.sync_scope"), sync_scope_combo)
        position_mode = QComboBox()
        position_mode.addItem(
            _tr(
                "settingsdialog.sync_position_auto_lps", "Automatic patient-space (LPS)"
            ),
            "auto_lps",
        )
        position_mode.addItem(_tr("settingsdialog.sync_position_none", "Off"), "none")
        self.setting_widgets["sync.position_mode"] = position_mode
        sync_form.addRow(
            _tr("settingsdialog.sync_position", "Position synchronization"),
            position_mode,
        )
        for key, label in (
            (
                "sync.window_level",
                _tr("settingsdialog.sync_window_level", "Window level"),
            ),
            ("sync.zoom", _tr("settingsdialog.sync_zoom", "Zoom")),
            ("sync.pan", _tr("settingsdialog.sync_pan", "Pan")),
            (
                "sync.reference_lines",
                _tr("settingsdialog.sync_reference_lines", "Reference lines"),
            ),
            (
                "sync.shared_cursor",
                _tr("settingsdialog.sync_shared_cursor", "Shared 3D cursor"),
            ),
        ):
            checkbox = QCheckBox(label)
            self.setting_widgets[key] = checkbox
            sync_form.addRow(checkbox)
        layout.addWidget(sync_group)

        layout.addStretch()
        return page

    def _create_workspace_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(_tr("settingsdialog.workspace_settings", "Workspace settings"))
        title.setFont(self._get_title_font())
        layout.addWidget(title)
        layout.addWidget(self._create_separator())

        startup_group = QGroupBox(
            _tr("settingsdialog.workspace_startup", "Study workspace startup")
        )
        startup_form = QFormLayout(startup_group)
        startup_combo = QComboBox()
        for text_value, value in (
            (
                _tr(
                    "settingsdialog.workspace_startup_restore",
                    "Restore the saved study workspace",
                ),
                "restore",
            ),
            (
                _tr(
                    "settingsdialog.workspace_startup_layout", "Use the default layout"
                ),
                "default_layout",
            ),
            (
                _tr(
                    "settingsdialog.workspace_startup_hanging",
                    "Apply the default hanging preset",
                ),
                "hanging_protocol",
            ),
        ):
            startup_combo.addItem(text_value, value)
        self.setting_widgets["workspace.startup_mode"] = startup_combo
        startup_form.addRow(
            _tr("settingsdialog.startup_behavior", "Startup behavior"), startup_combo
        )

        hanging_combo = QComboBox()
        for text_value, value in (
            (_tr("settingsdialog.hanging_none", "None (choose manually)"), "none"),
            (
                _tr("settingsdialog.hanging_study_overview", "Study overview"),
                "study_overview",
            ),
            (_tr("settingsdialog.hanging_ct_phase", "CT phase comparison"), "ct_phase"),
            (_tr("settingsdialog.hanging_mr_neuro", "MR neuro series"), "mr_neuro"),
        ):
            hanging_combo.addItem(text_value, value)
        self.setting_widgets["workspace.default_hanging_protocol"] = hanging_combo
        startup_form.addRow(
            _tr("settingsdialog.default_hanging", "Default hanging preset"),
            hanging_combo,
        )

        history_spin = QSpinBox()
        history_spin.setRange(1, 100)
        self.setting_widgets["workspace.history_limit"] = history_spin
        startup_form.addRow(
            _tr("settingsdialog.workspace_history_limit", "Remembered studies"),
            history_spin,
        )

        recent_spin = QSpinBox()
        recent_spin.setRange(1, 100)
        self.setting_widgets["recent_studies.max_items"] = recent_spin
        startup_form.addRow(
            _tr("settingsdialog.recent_studies_limit", "Recent studies"),
            recent_spin,
        )

        restore_mpr = QCheckBox(
            _tr(
                "settingsdialog.workspace_restore_mpr",
                "Re-enter MPR when restoring a workspace",
            )
        )
        restore_mpr.setToolTip(
            _tr(
                "settingsdialog.workspace_restore_mpr_hint",
                "May rebuild a large volume during startup.",
            )
        )
        self.setting_widgets["workspace.restore_mpr"] = restore_mpr
        startup_form.addRow(restore_mpr)
        layout.addWidget(startup_group)
        layout.addStretch()
        return page

    def _create_privacy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(_tr("settingsdialog.privacy_settings", "Privacy settings"))
        title.setFont(self._get_title_font())
        layout.addWidget(title)
        layout.addWidget(self._create_separator())

        group = QGroupBox(_tr("settingsdialog.screen_privacy", "Screen privacy"))
        form = QFormLayout(group)
        privacy_check = QCheckBox(
            _tr(
                "settingsdialog.privacy_screen_mode",
                "Hide patient information on screen",
            )
        )
        privacy_check.setToolTip(
            _tr(
                "settingsdialog.privacy_screen_mode_hint",
                "Uses session-only aliases in navigation, overlays, and metadata panels.",
            )
        )
        self.setting_widgets["privacy.screen_mode"] = privacy_check
        privacy_check.toggled.connect(
            lambda enabled: self.settings_session.set("privacy.screen_mode", enabled)
        )
        form.addRow(privacy_check)
        warning = QLabel(
            _tr(
                "settingsdialog.privacy_burned_in_warning",
                "Privacy mode does not remove text burned into image pixels and does not modify source DICOM files.",
            )
        )
        warning.setWordWrap(True)
        warning.setObjectName("privacyWarningLabel")
        form.addRow(warning)
        layout.addWidget(group)
        layout.addStretch()
        return page

    def _create_performance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title_label = QLabel(t("settingsdialog.performance_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())

        performance_group = QGroupBox(
            t("settingsdialog.application_performance_settings")
        )
        performance_layout = QFormLayout(performance_group)
        cache_size_spin = QSpinBox()
        cache_size_spin.setRange(64, 2048)
        cache_size_spin.setSuffix(" MB")
        self.setting_widgets["cache_size"] = cache_size_spin
        performance_layout.addRow(t("settingsdialog.cache_size"), cache_size_spin)

        thread_count_spin = QSpinBox()
        thread_count_spin.setRange(1, 16)
        thread_count_spin.setSuffix(t("settingsdialog.count_suffix"))
        self.setting_widgets["thread_count"] = thread_count_spin
        performance_layout.addRow(
            t("settingsdialog.number_of_threads"), thread_count_spin
        )

        thumbnail_items = QSpinBox()
        thumbnail_items.setRange(64, 2048)
        self.setting_widgets["cache.thumbnail.max_items"] = thumbnail_items
        performance_layout.addRow(
            _tr("settingsdialog.thumbnail_cache_items", "Thumbnail cache items"),
            thumbnail_items,
        )
        thumbnail_age = QSpinBox()
        thumbnail_age.setRange(1, 365)
        thumbnail_age.setSuffix(_tr("settingsdialog.days_suffix", " days"))
        self.setting_widgets["cache.thumbnail.max_age_days"] = thumbnail_age
        performance_layout.addRow(
            _tr("settingsdialog.thumbnail_cache_age", "Thumbnail retention"),
            thumbnail_age,
        )
        keep_demo = QCheckBox(
            _tr("settingsdialog.keep_demo_cache", "Keep generated example studies")
        )
        self.setting_widgets["cache.demo.keep"] = keep_demo
        performance_layout.addRow(keep_demo)
        layout.addWidget(performance_group)

        storage_group = QGroupBox(
            _tr("settingsdialog.storage_usage", "Cache and recovery data")
        )
        storage_form = QFormLayout(storage_group)
        labels = {
            StorageCategory.DISPLAY_MEMORY: _tr(
                "settingsdialog.display_cache", "Display cache"
            ),
            StorageCategory.THUMBNAILS: _tr(
                "settingsdialog.thumbnail_cache", "Thumbnail cache"
            ),
            StorageCategory.DEMO_STUDIES: _tr(
                "demo.example_studies", "Example studies"
            ),
            StorageCategory.WORKSPACE_HISTORY: _tr(
                "settingsdialog.workspace_history", "Workspace history"
            ),
            StorageCategory.RECOVERY_DRAFTS: _tr(
                "settingsdialog.recovery_drafts", "Annotation recovery drafts"
            ),
        }
        for category, label_text in labels.items():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            usage_label = QLabel("—")
            self._storage_labels[category] = usage_label
            clear_button = QPushButton(_tr("settingsdialog.clear", "Clear"))
            clear_button.setObjectName(f"clear_{category.value}_button")
            clear_button.clicked.connect(
                lambda _checked=False, target=category: self._clear_storage(target)
            )
            row_layout.addWidget(usage_label, 1)
            row_layout.addWidget(clear_button)
            storage_form.addRow(label_text, row)

        clear_temporary = QPushButton(
            _tr("settingsdialog.clear_temporary_caches", "Clear all temporary caches")
        )
        clear_temporary.clicked.connect(self._clear_temporary_caches)
        storage_form.addRow(clear_temporary)
        refresh_button = QPushButton(
            _tr("settingsdialog.refresh_storage", "Refresh usage")
        )
        refresh_button.clicked.connect(self._refresh_storage_usage)
        storage_form.addRow(refresh_button)
        layout.addWidget(storage_group)
        layout.addStretch()
        self._refresh_storage_usage()
        return page

    def _create_roi_settings_group(self) -> QGroupBox:
        """创建ROI设置组"""
        group = QGroupBox(t("settingsdialog.roi_settings"))
        layout = QVBoxLayout(group)

        # 主题选择
        theme_layout = QFormLayout()
        roi_theme_combo = QComboBox()
        self.setting_widgets["roi_theme"] = roi_theme_combo
        theme_layout.addRow(t("settingsdialog.subject"), roi_theme_combo)
        layout.addLayout(theme_layout)

        # 自定义设置组
        custom_group = QGroupBox(t("settingsdialog.custom_settings"))
        custom_layout = QVBoxLayout(custom_group)

        # 外观设置
        appearance_group = QGroupBox(t("settingsdialog.appearance"))
        appearance_layout = QFormLayout(appearance_group)

        # 边框颜色
        border_color_btn = ColorButton()
        self.setting_widgets["roi.custom.border_color"] = border_color_btn
        appearance_layout.addRow(t("settingsdialog.border_color"), border_color_btn)

        # 填充颜色
        fill_color_btn = ColorButton()
        self.setting_widgets["roi.custom.fill_color"] = fill_color_btn
        appearance_layout.addRow(t("settingsdialog.fill_color"), fill_color_btn)

        # 选中时颜色
        selected_color_btn = ColorButton()
        self.setting_widgets["roi.custom.selected_color"] = selected_color_btn
        appearance_layout.addRow(
            t("settingsdialog.color_when_selected"), selected_color_btn
        )

        # 边框粗细
        border_width_spin = QSpinBox()
        border_width_spin.setRange(1, 10)
        border_width_spin.setSuffix(" px")
        self.setting_widgets["roi.custom.border_width"] = border_width_spin
        appearance_layout.addRow(
            t("settingsdialog.border_thickness"), border_width_spin
        )

        custom_layout.addWidget(appearance_group)

        # 锚点设置
        anchor_group = QGroupBox(t("settingsdialog.anchor"))
        anchor_layout = QFormLayout(anchor_group)

        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets["roi.custom.anchor_color"] = anchor_color_btn
        anchor_layout.addRow(t("settingsdialog.anchor_color"), anchor_color_btn)

        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets["roi.custom.anchor_size"] = anchor_size_spin
        anchor_layout.addRow(t("settingsdialog.anchor_size"), anchor_size_spin)

        custom_layout.addWidget(anchor_group)

        # 信息板设置
        info_group = QGroupBox(t("settingsdialog.message_board_settings"))
        info_layout = QVBoxLayout(info_group)

        # 外观子组
        info_appearance_group = QGroupBox(t("settingsdialog.appearance"))
        info_appearance_layout = QFormLayout(info_appearance_group)

        # 背景颜色
        info_bg_color_btn = ColorButton()
        self.setting_widgets["roi.custom.info_bg_color"] = info_bg_color_btn
        info_appearance_layout.addRow(
            t("settingsdialog.background_color"), info_bg_color_btn
        )

        # 选中背景颜色
        info_selected_bg_color_btn = ColorButton()
        self.setting_widgets["roi.custom.info_selected_bg_color"] = (
            info_selected_bg_color_btn
        )
        info_appearance_layout.addRow(
            t("settingsdialog.selected_background_color"), info_selected_bg_color_btn
        )

        # 文本颜色
        info_text_color_btn = ColorButton()
        self.setting_widgets["roi.custom.info_text_color"] = info_text_color_btn
        info_appearance_layout.addRow(t("settingsdialog.color"), info_text_color_btn)

        # 边框颜色
        info_border_color_btn = ColorButton()
        self.setting_widgets["roi.custom.info_border_color"] = info_border_color_btn
        info_appearance_layout.addRow(
            t("settingsdialog.border_color"), info_border_color_btn
        )

        # 字体大小
        info_font_size_spin = QSpinBox()
        info_font_size_spin.setRange(8, 24)
        info_font_size_spin.setSuffix(" pt")
        self.setting_widgets["roi.custom.info_font_size"] = info_font_size_spin
        info_appearance_layout.addRow(
            t("settingsdialog.font_size"), info_font_size_spin
        )

        # 圆角半径
        info_radius_spin = QSpinBox()
        info_radius_spin.setRange(0, 20)
        info_radius_spin.setSuffix(" px")
        self.setting_widgets["roi.custom.info_radius"] = info_radius_spin
        info_appearance_layout.addRow(
            t("settingsdialog.fillet_radius"), info_radius_spin
        )

        # 内边距
        info_padding_spin = QSpinBox()
        info_padding_spin.setRange(2, 20)
        info_padding_spin.setSuffix(" px")
        self.setting_widgets["roi.custom.info_padding"] = info_padding_spin
        info_appearance_layout.addRow(
            t("settingsdialog.inner_margin"), info_padding_spin
        )

        info_layout.addWidget(info_appearance_group)

        # 显示选项子组
        info_display_group = QGroupBox(t("settingsdialog.display_options"))
        info_display_layout = QFormLayout(info_display_group)

        # 数值精度
        info_precision_spin = QSpinBox()
        info_precision_spin.setRange(0, 6)
        self.setting_widgets["roi.custom.info_precision"] = info_precision_spin
        info_display_layout.addRow(
            t("settingsdialog.numerical_precision"), info_precision_spin
        )

        # 自动隐藏
        info_auto_hide_check = QCheckBox(
            t("settingsdialog.automatically_hide_when_the_mouse_leaves")
        )
        self.setting_widgets["roi.custom.info_auto_hide"] = info_auto_hide_check
        info_display_layout.addRow(info_auto_hide_check)

        stats_fields_group = QGroupBox(t("settingsdialog.statistics_fields"))
        stats_fields_layout = QFormLayout(stats_fields_group)
        for key, text in [
            ("roi.stats.show_mean", t("settingsdialog.show_mean")),
            ("roi.stats.show_std", t("settingsdialog.show_sd")),
            ("roi.stats.show_max", t("settingsdialog.show_max")),
            ("roi.stats.show_min", t("settingsdialog.show_min")),
            ("roi.stats.show_area", t("settingsdialog.show_area")),
            ("roi.stats.show_count", t("settingsdialog.show_pixel_count")),
        ]:
            check = QCheckBox(text)
            self.setting_widgets[key] = check
            stats_fields_layout.addRow(check)

        area_unit_combo = QComboBox()
        area_unit_combo.addItem(t("mainwindow.auto"), "auto")
        area_unit_combo.addItem("mm²", "mm2")
        area_unit_combo.addItem("cm²", "cm2")
        area_unit_combo.addItem("px²", "px")
        self.setting_widgets["roi.stats.area_unit"] = area_unit_combo
        stats_fields_layout.addRow(t("settingsdialog.area_unit"), area_unit_combo)

        info_layout.addWidget(info_display_group)
        info_layout.addWidget(stats_fields_group)
        custom_layout.addWidget(info_group)

        layout.addWidget(custom_group)

        # 连接主题变化和加载主题设置的逻辑
        def on_roi_theme_changed(index):
            theme_name = roi_theme_combo.itemData(index)
            is_custom = theme_name == "custom"

            # 如果不是自定义主题，则先加载所选主题的颜色进行预览
            if not is_custom:
                theme_data = self.themes.get("roi", {}).get(theme_name, {})
                for key, value in theme_data.items():
                    if key == "name":
                        continue
                    widget_key = f"roi.custom.{key}"
                    if widget_key in self.setting_widgets:
                        widget = self.setting_widgets[widget_key]
                        if isinstance(widget, ColorButton):
                            widget.setColor(qcolor_from_theme(value))
                        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                            widget.setValue(
                                int(value)
                                if isinstance(widget, QSpinBox)
                                else float(value)
                            )
                        elif isinstance(widget, QCheckBox):
                            widget.setChecked(bool(value))

            # 然后再根据是否是自定义主题，来启用/禁用控件
            self._enable_roi_custom_controls(is_custom)

        roi_theme_combo.currentIndexChanged.connect(on_roi_theme_changed)

        return group

    def _create_measurement_settings_group(self) -> QGroupBox:
        """创建测量工具设置组"""
        group = QGroupBox(t("settingsdialog.measurement_tools"))
        layout = QVBoxLayout(group)

        # 主题选择
        theme_layout = QFormLayout()
        measurement_theme_combo = QComboBox()
        self.setting_widgets["measurement_theme"] = measurement_theme_combo
        theme_layout.addRow(t("settingsdialog.subject"), measurement_theme_combo)
        layout.addLayout(theme_layout)

        # 自定义设置组
        custom_group = QGroupBox(t("settingsdialog.custom_settings"))
        custom_layout = QVBoxLayout(custom_group)

        # 外观设置
        appearance_group = QGroupBox(t("settingsdialog.appearance"))
        appearance_layout = QFormLayout(appearance_group)

        # 线条颜色
        line_color_btn = ColorButton()
        self.setting_widgets["measurement.custom.line_color"] = line_color_btn
        appearance_layout.addRow(t("settingsdialog.line_color"), line_color_btn)

        # 线条粗细
        line_width_spin = QSpinBox()
        line_width_spin.setRange(1, 10)
        line_width_spin.setSuffix(" px")
        self.setting_widgets["measurement.custom.line_width"] = line_width_spin
        appearance_layout.addRow(t("settingsdialog.line_thickness"), line_width_spin)

        custom_layout.addWidget(appearance_group)

        # 锚点设置
        anchor_group = QGroupBox(t("settingsdialog.anchor"))
        anchor_layout = QFormLayout(anchor_group)

        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets["measurement.custom.anchor_color"] = anchor_color_btn
        anchor_layout.addRow(t("settingsdialog.anchor_color"), anchor_color_btn)

        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets["measurement.custom.anchor_size"] = anchor_size_spin
        anchor_layout.addRow(t("settingsdialog.anchor_size"), anchor_size_spin)

        custom_layout.addWidget(anchor_group)

        # 文本设置
        text_group = QGroupBox(t("settingsdialog.display_text"))
        text_layout = QFormLayout(text_group)

        # 距离文本颜色
        text_color_btn = ColorButton()
        self.setting_widgets["measurement.custom.text_color"] = text_color_btn
        text_layout.addRow(t("settingsdialog.distance_from_color"), text_color_btn)

        # 距离文本背景色
        bg_color_btn = ColorButton()
        self.setting_widgets["measurement.custom.background_color"] = bg_color_btn
        text_layout.addRow(
            t("settingsdialog.distance_from_background_color"), bg_color_btn
        )

        # 字体大小
        font_size_spin = QSpinBox()
        font_size_spin.setRange(8, 24)
        font_size_spin.setSuffix(" pt")
        self.setting_widgets["measurement.custom.font_size"] = font_size_spin
        text_layout.addRow(t("settingsdialog.font_size"), font_size_spin)

        custom_layout.addWidget(text_group)
        layout.addWidget(custom_group)

        # 连接主题变化和加载主题设置的逻辑
        def on_measurement_theme_changed(index):
            theme_name = measurement_theme_combo.itemData(index)
            is_custom = theme_name == "custom"

            # 先根据是否是自定义主题，来启用/禁用控件
            self._enable_measurement_custom_controls(is_custom)

            # 如果不是自定义主题，则加载所选主题的颜色进行预览
            if not is_custom:
                theme_data = self.themes.get("measurement", {}).get(theme_name, {})
                for key, value in theme_data.items():
                    if key == "name":
                        continue
                    widget_key = f"measurement.custom.{key}"
                    if widget_key in self.setting_widgets:
                        widget = self.setting_widgets[widget_key]
                        if isinstance(widget, ColorButton):
                            color = qcolor_from_theme(value)
                            widget.setColor(color)
                        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                            widget.setValue(
                                int(value)
                                if isinstance(widget, QSpinBox)
                                else float(value)
                            )
                        elif isinstance(widget, QCheckBox):
                            widget.setChecked(bool(value))

        measurement_theme_combo.currentIndexChanged.connect(
            on_measurement_theme_changed
        )

        return group

    def _get_title_font(self) -> QFont:
        """获取标题字体"""
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        return font

    def _get_decoder_status_text(self) -> str:
        """返回当前 pydicom 像素解码处理器状态。"""
        try:
            import pydicom.config

            handlers = []
            for handler in pydicom.config.pixel_data_handlers:
                name = getattr(handler, "__name__", handler.__class__.__name__).split(
                    "."
                )[-1]
                available = (
                    handler.is_available() if hasattr(handler, "is_available") else True
                )
                status = t(
                    "settingsdialog.decoder_available"
                    if available
                    else "settingsdialog.decoder_unavailable"
                )
                handlers.append(f"{name}: {status}")
            return (
                "\n".join(handlers)
                if handlers
                else t("settingsdialog.no_pixel_decoder_detected")
            )
        except Exception as e:
            return t("settingsdialog.decoder_detection_failed_prefix") + str(e)

    def _get_cache_info_text(self) -> str:
        """返回性能缓存状态文本。"""
        try:
            info = self.settings_manager.get_performance_manager().get_cache_info()
            return (
                t("settingsdialog.cache_status_summary")
                .replace("%1", str(info.get("size_mb", 0)))
                .replace("%2", str(info.get("item_count", 0)))
                .replace("%3", f"{info.get('estimated_usage_mb', 0):.1f}")
            )
        except Exception as e:
            return t("settingsdialog.cache_status_unavailable_prefix") + str(e)

    def _clear_cache(self, label: QLabel) -> None:
        """Backward-compatible display-cache action."""
        try:
            self.storage_service.clear(StorageCategory.DISPLAY_MEMORY)
            label.setText(self._get_cache_info_text())
            self._refresh_storage_usage()
        except Exception as error:
            label.setText(t("settingsdialog.clear_cache_failed_prefix") + str(error))

    @staticmethod
    def _format_bytes(byte_count: int) -> str:
        value = float(max(0, byte_count))
        for suffix in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or suffix == "GB":
                return f"{value:.1f} {suffix}" if suffix != "B" else f"{int(value)} B"
            value /= 1024.0
        return "0 B"

    def _refresh_storage_usage(self) -> None:
        try:
            for usage in self.storage_service.inspect():
                label = self._storage_labels.get(usage.category)
                if label is not None:
                    label.setText(
                        _tr("settingsdialog.storage_summary", "%1 items · %2")
                        .replace("%1", str(usage.item_count))
                        .replace("%2", self._format_bytes(usage.bytes))
                    )
        except Exception as error:
            logger.warning(
                "Storage usage inspection failed: %s", error.__class__.__name__
            )

    def _clear_storage(self, category: StorageCategory) -> None:
        if category in {
            StorageCategory.WORKSPACE_HISTORY,
            StorageCategory.RECOVERY_DRAFTS,
        }:
            answer = QMessageBox.question(
                self,
                _tr("settingsdialog.confirm_clear_title", "Confirm clear"),
                _tr(
                    "settingsdialog.confirm_clear_recovery",
                    "This removes saved recovery state. Formal annotation files are not deleted. Continue?",
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.storage_service.clear(category)
        self._refresh_storage_usage()

    def _clear_temporary_caches(self) -> None:
        self.storage_service.clear_temporary_caches()
        self._refresh_storage_usage()

    def _apply_live_setting(self, key: str, value, preview: bool) -> None:
        if key != "privacy.screen_mode":
            return
        if preview:
            self.privacy_service.set_preview(bool(value))
        else:
            self.privacy_service.clear_preview()

    def _create_separator(self) -> QFrame:
        """创建分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _load_themes(self):
        """Load bundled themes and overlay writable user themes."""
        self.themes.clear()
        bundled_themes_dir = Path(__file__).parent.parent.parent / "themes"
        user_themes_dir = get_user_themes_dir(self.settings_manager)

        for base_themes_dir in (bundled_themes_dir, user_themes_dir):
            if not base_themes_dir.is_dir():
                continue
            for category_dir in base_themes_dir.iterdir():
                if not category_dir.is_dir():
                    continue
                category = category_dir.name
                self.themes.setdefault(category, {})
                for theme_file in category_dir.glob("*.toml"):
                    try:
                        self.themes[category][theme_file.stem] = toml.load(theme_file)
                    except Exception as e:
                        logger.warning(f"加载主题文件失败 {theme_file}: {e}")

        self._populate_theme_combos()

    def _populate_theme_combos(self):
        """填充主题下拉框"""
        # UI主题
        ui_combo = self.setting_widgets.get("ui_theme")
        if ui_combo:
            ui_combo.blockSignals(True)
            ui_combo.clear()
            ui_themes = self.themes.get("ui", {})
            for theme_name, theme_data in ui_themes.items():
                display_name = self._theme_display_name("ui", theme_name, theme_data)
                ui_combo.addItem(display_name, theme_name)
            ui_combo.blockSignals(False)

        # ROI主题
        roi_combo = self.setting_widgets.get("roi_theme")
        if roi_combo:
            roi_combo.blockSignals(True)
            roi_combo.clear()
            roi_themes = self.themes.get("roi", {})

            # 确保自定义主题文件存在
            self._ensure_custom_theme_exists("roi")

            for theme_name, theme_data in roi_themes.items():
                display_name = self._theme_display_name("roi", theme_name, theme_data)
                roi_combo.addItem(display_name, theme_name)
            roi_combo.blockSignals(False)

        # 测量工具主题
        measurement_combo = self.setting_widgets.get("measurement_theme")
        if measurement_combo:
            measurement_combo.blockSignals(True)
            measurement_combo.clear()
            measurement_themes = self.themes.get("measurement", {})

            # 确保自定义主题文件存在
            self._ensure_custom_theme_exists("measurement")

            for theme_name, theme_data in measurement_themes.items():
                display_name = self._theme_display_name(
                    "measurement", theme_name, theme_data
                )
                measurement_combo.addItem(display_name, theme_name)
            measurement_combo.blockSignals(False)

    @staticmethod
    def _theme_display_name(category: str, theme_name: str, theme_data: dict) -> str:
        key = f"themes.{category}.{theme_name}"
        known_names = {
            "themes.ui.dark",
            "themes.ui.light",
            "themes.roi.default",
            "themes.roi.custom",
            "themes.roi.radiant",
            "themes.measurement.default",
            "themes.measurement.custom",
        }
        return t(key) if key in known_names else str(theme_data.get("name", theme_name))

    def _apply_theme(self, category: str, theme_name: str):
        """应用主题到控件"""
        theme_data = self.themes.get(category, {}).get(theme_name, {})
        for key, value in theme_data.items():
            if key == "name":
                continue
            widget_key = f"{category}.custom.{key}"
            if widget_key in self.setting_widgets:
                widget = self.setting_widgets[widget_key]
                if isinstance(widget, ColorButton):
                    widget.setColor(qcolor_from_theme(value))
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(
                        int(value) if isinstance(widget, QSpinBox) else float(value)
                    )
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))

    def _load_current_settings(self):
        """加载当前设置"""
        # 加载语言设置
        language_combo = self.setting_widgets.get("language")
        if language_combo:
            saved_language = self.settings_manager.get_setting("language", "en_US")
            index = language_combo.findData(saved_language)
            if index != -1:
                language_combo.setCurrentIndex(index)

        # 加载UI主题
        ui_combo = self.setting_widgets.get("ui_theme")
        if ui_combo:
            saved_theme = self.settings_manager.get_setting("ui_theme", "dark")
            index = ui_combo.findData(saved_theme)
            if index != -1:
                ui_combo.blockSignals(True)
                ui_combo.setCurrentIndex(index)
                ui_combo.blockSignals(False)

        # 加载ROI主题
        roi_combo = self.setting_widgets.get("roi_theme")
        if roi_combo:
            saved_theme = self.settings_manager.get_setting("roi_theme", "default")
            index = roi_combo.findData(saved_theme)
            if index == -1:
                index = roi_combo.findData("default")
            if index != -1:
                roi_combo.setCurrentIndex(index)
                # 触发主题加载逻辑
                roi_combo.currentIndexChanged.emit(index)

        # 加载测量工具主题
        measurement_combo = self.setting_widgets.get("measurement_theme")
        if measurement_combo:
            saved_theme = self.settings_manager.get_setting(
                "measurement_theme", "default"
            )
            index = measurement_combo.findData(saved_theme)
            if index == -1:
                index = measurement_combo.findData("default")
            if index != -1:
                measurement_combo.setCurrentIndex(index)
                # 触发主题加载逻辑
                measurement_combo.currentIndexChanged.emit(index)

        # 加载性能设置
        cache_size_spin = self.setting_widgets.get("cache_size")
        if cache_size_spin:
            saved_cache_size = self.settings_manager.get_setting("cache_size", 256)
            cache_size_spin.setValue(saved_cache_size)

        thread_count_spin = self.setting_widgets.get("thread_count")
        if thread_count_spin:
            saved_thread_count = self.settings_manager.get_setting("thread_count", 4)
            thread_count_spin.setValue(saved_thread_count)

        self._load_simple_settings()

        # 加载自定义设置
        self._load_custom_settings()

    def _load_simple_settings(self):
        """加载通用设置控件。"""
        for key, default_value in SIMPLE_SETTING_DEFAULTS.items():
            widget = self.setting_widgets.get(key)
            if widget is None:
                continue
            value = self.settings_manager.get_setting(key, default_value)
            self._set_widget_value(widget, value)

    def _set_widget_value(self, widget: QWidget, value: Any):
        if isinstance(widget, StringListEditor):
            widget.setValue(value)
        elif isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index != -1:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(self._to_bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(
                int(value) if isinstance(widget, QSpinBox) else float(value)
            )

    def _get_widget_value(self, widget: QWidget):
        if isinstance(widget, StringListEditor):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        return None

    def _connect_change_tracking(self) -> None:
        for key, widget in self.setting_widgets.items():

            def callback(*_args, setting_key=key):
                self._mark_setting_modified(setting_key)

            if isinstance(widget, StringListEditor):
                widget.valueChanged.connect(callback)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(callback)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(callback)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(callback)
            elif isinstance(widget, ColorButton):
                widget.colorChanged.connect(callback)

    def _mark_setting_modified(self, key: str) -> None:
        widget = self.setting_widgets.get(key)
        spec = DEFAULT_SETTINGS_REGISTRY.spec(key)
        current = self._get_widget_value(widget) if widget is not None else None
        if spec is not None and current == self.settings_manager.get_setting(
            key, spec.default
        ):
            self._modified_keys.discard(key)
        else:
            self._modified_keys.add(key)
        self._update_change_status()

    def _update_change_status(self) -> None:
        count = len(self._modified_keys)
        self.change_status_label.setText(
            _tr("settingsdialog.modified_count", "{count} modified").format(count=count)
            if count
            else _tr("settingsdialog.no_pending_changes", "No pending changes")
        )
        restart_required = any(
            (spec := DEFAULT_SETTINGS_REGISTRY.spec(key)) is not None
            and spec.apply_policy is ApplyPolicy.RESTART
            for key in self._modified_keys
        )
        self.restart_badge.setText(
            _tr("settingsdialog.restart_required", "Restart required")
        )
        self.restart_badge.setVisible(restart_required)

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _load_custom_settings(self):
        """加载自定义设置"""
        for key, widget in self.setting_widgets.items():
            if ".custom." not in key:
                continue

            category = key.split(".")[0]
            theme_combo = self.setting_widgets.get(f"{category}_theme")
            selected_theme = (
                theme_combo.currentData()
                if isinstance(theme_combo, QComboBox)
                else None
            )
            if selected_theme != "custom":
                continue

            saved_value = self.settings_manager.get_setting(key)

            # 如果没有保存值，从 custom 主题文件获取；再回退到默认主题。
            if saved_value is None:
                parts = key.split(".")
                if len(parts) >= 3 and parts[1] == "custom":
                    field_name = parts[2]

                    category_themes = self.themes.get(category, {})
                    custom_theme_data = category_themes.get("custom", {})
                    saved_value = custom_theme_data.get(field_name)

                    if saved_value is None:
                        default_theme_data = category_themes.get("default", {})
                        saved_value = default_theme_data.get(field_name)
                        if (
                            saved_value is None
                            and field_name == "info_selected_bg_color"
                        ):
                            saved_value = default_theme_data.get("info_bg_color")

            if saved_value is None:
                continue

            # 设置控件值
            if isinstance(widget, ColorButton):
                widget.setColor(qcolor_from_theme(saved_value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(
                    int(saved_value)
                    if isinstance(widget, QSpinBox)
                    else float(saved_value)
                )
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(saved_value))

    def _restore_page_defaults(self, keys) -> None:
        for key in keys:
            widget = self.setting_widgets.get(key)
            if widget is None:
                continue
            spec = DEFAULT_SETTINGS_REGISTRY.spec(key)
            if spec is not None:
                self._set_widget_value(widget, spec.default)
                continue
            defaults = {
                "language": "en_US",
                "ui_theme": "dark",
                "roi_theme": "default",
                "measurement_theme": "default",
                "cache_size": 256,
                "thread_count": 4,
            }
            if key in defaults:
                self._set_widget_value(widget, defaults[key])

    def _restore_defaults(self):
        """恢复默认设置"""
        # 恢复语言默认值
        language_combo = self.setting_widgets.get("language")
        if language_combo:
            index = language_combo.findData("en_US")
            if index != -1:
                language_combo.setCurrentIndex(index)

        # 恢复UI主题默认值
        ui_combo = self.setting_widgets.get("ui_theme")
        if ui_combo:
            index = ui_combo.findData("dark")
            if index != -1:
                ui_combo.setCurrentIndex(index)

        # 恢复ROI主题默认值
        roi_combo = self.setting_widgets.get("roi_theme")
        if roi_combo:
            index = roi_combo.findData("default")
            if index != -1:
                roi_combo.setCurrentIndex(index)

        # 恢复测量工具主题默认值
        measurement_combo = self.setting_widgets.get("measurement_theme")
        if measurement_combo:
            index = measurement_combo.findData("default")
            if index != -1:
                measurement_combo.setCurrentIndex(index)

        # 恢复性能设置默认值
        cache_size_spin = self.setting_widgets.get("cache_size")
        if cache_size_spin:
            cache_size_spin.setValue(256)

        thread_count_spin = self.setting_widgets.get("thread_count")
        if thread_count_spin:
            thread_count_spin.setValue(4)

        for key, default_value in SIMPLE_SETTING_DEFAULTS.items():
            widget = self.setting_widgets.get(key)
            if widget is not None:
                self._set_widget_value(widget, default_value)

    def accept(self):
        """保存设置并关闭对话框"""
        self._save_settings()
        super().accept()

    def _apply_without_close(self) -> None:
        self._save_settings()
        self._original_ui_theme = self.settings_manager.get_setting("ui_theme", "dark")

    def reject(self):
        """取消设置并恢复所有尚未应用的实时预览。"""
        self.settings_session.discard()
        self.privacy_service.clear_preview()
        self._restore_previewed_ui_theme()
        super().reject()

    def _restore_previewed_ui_theme(self):
        main_window = self.parent()
        if hasattr(main_window, "theme_manager"):
            current_theme = main_window.theme_manager.get_current_theme()
            if current_theme != self._original_ui_theme:
                main_window.theme_manager.set_theme(self._original_ui_theme)

    def _save_settings(self):
        """Collect, validate, and commit the current settings page."""
        old_language = self.settings_manager.get_setting("language", "en_US")
        new_language = self.setting_widgets["language"].currentData()
        direct_values = {"language": new_language}

        for key in ("ui_theme", "roi_theme", "measurement_theme"):
            combo = self.setting_widgets.get(key)
            if isinstance(combo, QComboBox):
                direct_values[key] = combo.currentData()
        for key in ("cache_size", "thread_count"):
            spin = self.setting_widgets.get(key)
            if isinstance(spin, (QSpinBox, QDoubleSpinBox)):
                direct_values[key] = spin.value()

        changed = {
            key
            for key, value in direct_values.items()
            if self.settings_manager.get_setting(key) != value
        }
        self.settings_manager.set_many(direct_values)

        for category in ("roi", "measurement"):
            if direct_values.get(f"{category}_theme") == "custom":
                self._save_theme_to_file(category, "custom")

        for key in SIMPLE_SETTING_DEFAULTS:
            widget = self.setting_widgets.get(key)
            if widget is not None:
                self.settings_session.set(key, self._get_widget_value(widget))
        changed.update(self.settings_session.commit())
        self.settings_manager.save_settings()
        self.privacy_service.clear_preview()

        if old_language != new_language:
            self._language_changed = True
        self.settings_applied.emit(tuple(sorted(changed)))
        self._modified_keys.clear()
        self._update_change_status()
        return tuple(sorted(changed))

    def _save_theme_to_file(self, category: str, theme_name: str):
        """保存主题设置到TOML文件"""
        if theme_name != "custom":
            return

        # 收集当前自定义控件的值
        theme_data = {"name": t("settingsdialog.custom")}

        for key, widget in self.setting_widgets.items():
            if not key.startswith(f"{category}.custom."):
                continue

            field_name = key.split(".")[-1]  # 获取最后一部分作为字段名

            if isinstance(widget, ColorButton):
                theme_data[field_name] = qcolor_to_theme(widget.color())
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                theme_data[field_name] = widget.value()
            elif isinstance(widget, QCheckBox):
                theme_data[field_name] = widget.isChecked()

        # 保存到TOML文件
        try:
            base_themes_dir = get_user_themes_dir(self.settings_manager)
            theme_file = base_themes_dir / category / f"{theme_name}.toml"
            theme_file.parent.mkdir(parents=True, exist_ok=True)

            with open(theme_file, "w", encoding="utf-8") as f:
                toml.dump(theme_data, f)

            # 重新加载主题数据
            self.themes[category][theme_name] = theme_data

        except Exception as e:
            logger.warning(f"保存主题文件失败 ({category}/{theme_name}): {e}")

    def _ensure_custom_theme_exists(self, category: str):
        """Ensure an in-memory custom theme without writing the install tree."""
        category_themes = self.themes.setdefault(category, {})
        if "custom" in category_themes:
            return
        custom_theme_data = dict(category_themes.get("default", {}))
        custom_theme_data["name"] = t("settingsdialog.custom")
        category_themes["custom"] = custom_theme_data

    def _enable_roi_custom_controls(self, enabled: bool):
        """启用/禁用ROI自定义控件"""
        roi_controls = [
            "roi.custom.border_color",
            "roi.custom.fill_color",
            "roi.custom.selected_color",
            "roi.custom.border_width",
            "roi.custom.anchor_color",
            "roi.custom.anchor_size",
            "roi.custom.info_bg_color",
            "roi.custom.info_selected_bg_color",
            "roi.custom.info_text_color",
            "roi.custom.info_border_color",
            "roi.custom.info_font_size",
            "roi.custom.info_radius",
            "roi.custom.info_padding",
            "roi.custom.info_precision",
            "roi.custom.info_auto_hide",
        ]
        for control_name in roi_controls:
            if control_name in self.setting_widgets:
                widget = self.setting_widgets[control_name]
                widget.setEnabled(enabled)

    def _enable_measurement_custom_controls(self, enabled: bool):
        """启用/禁用测量工具自定义控件"""
        measurement_controls = [
            "measurement.custom.line_color",
            "measurement.custom.line_width",
            "measurement.custom.anchor_color",
            "measurement.custom.anchor_size",
            "measurement.custom.text_color",
            "measurement.custom.background_color",
            "measurement.custom.font_size",
        ]
        for control_name in measurement_controls:
            if control_name in self.setting_widgets:
                widget = self.setting_widgets[control_name]
                widget.setEnabled(enabled)

    def _load_roi_theme(self, theme_name: str):
        """加载ROI主题"""
        if theme_name:
            self._apply_theme("roi", theme_name)

    def _load_measurement_theme(self, theme_name: str):
        """加载测量工具主题"""
        if theme_name:
            self._apply_theme("measurement", theme_name)

    def _update_button_text(self):
        """更新按钮文本"""
        self.button_box.button(QDialogButtonBox.Ok).setText(t("settingsdialog.ok"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(
            t("settingsdialog.cancel")
        )
        self.button_box.button(QDialogButtonBox.RestoreDefaults).setText(
            t("settingsdialog.restore_default")
        )
        self.button_box.button(QDialogButtonBox.Apply).setText(
            _tr("settingsdialog.apply", "Apply")
        )
