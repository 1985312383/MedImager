#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置对话框

根据设计文档重构的设置界面，包含左侧导航栏和右侧内容区。
"""

import toml
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QStackedWidget,
    QLabel, QColorDialog, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QComboBox, QCheckBox, QFrame,
    QDialogButtonBox, QListWidgetItem, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap, QIcon
from typing import Dict, Any
from medimager.utils.settings import SettingsManager
from medimager.utils.i18n import get_translation_manager, t
from medimager.utils.logger import get_logger
from medimager.utils.theme_colors import qcolor_from_theme

logger = get_logger(__name__)


SIMPLE_SETTING_DEFAULTS = {
    "display.window_level_strategy": "dicom",
    "display.smooth_interpolation": True,
    "display.show_view_title": True,
    "display.show_view_status": True,
    "interaction.left_drag_action": "browse",
    "interaction.middle_drag_action": "window",
    "interaction.right_drag_action": "zoom",
    "interaction.wheel_reverse": False,
    "cine.default_fps": 10,
    "dicom.recursive_scan": True,
    "dicom.include_extensionless": True,
    "dicom.strict_metadata": False,
    "roi.stats.show_mean": True,
    "roi.stats.show_std": True,
    "roi.stats.show_max": True,
    "roi.stats.show_min": True,
    "roi.stats.show_area": True,
    "roi.stats.show_count": True,
    "roi.stats.area_unit": "auto",
    "multiview.default_layout": "1x1",
    "multiview.default_sync_mode": "basic",
}


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
            self.setText(f"{t('colorbutton.select')} ({color.name()})")
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
        color = QColorDialog.getColor(self._color, self, t("colorbutton.select_color"))
        if color.isValid():
            self.setColor(color)


class SettingsDialog(QDialog):
    """设置对话框，采用左侧导航布局"""
    
    def __init__(self, settings_manager: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.translation_manager = get_translation_manager()
        self._language_changed = False
        self._original_ui_theme = self.settings_manager.get_setting('ui_theme', 'dark')
        self.setWindowTitle(t("settingsdialog.settings"))
        self.setMinimumSize(900, 700)
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
        content_layout = QHBoxLayout()
        
        # 左侧导航栏
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("settings_nav")  # 为主题样式设置ID
        self.nav_list.setFixedWidth(120)
        
        # 右侧内容区
        self.stacked_widget = QStackedWidget()
        
        content_layout.addWidget(self.nav_list)
        content_layout.addWidget(self.stacked_widget, 1)
        main_layout.addLayout(content_layout)
        
        # 添加页面
        self._add_page(t("settingsdialog.general"), self._create_general_page)
        self._add_page(t("settingsdialog.display"), self._create_display_page)
        self._add_page(t("settingsdialog.interaction"), self._create_interaction_page)
        self._add_page(t("settingsdialog.dicom_settings"), self._create_dicom_page)
        self._add_page(t("settingsdialog.tools"), self._create_tools_page)
        self._add_page(t("settingsdialog.multi_view"), self._create_multiview_page)
        self._add_page(t("settingsdialog.performance"), self._create_performance_page)
        
        # 移除导航栏的 currentRowChanged 连接，避免不必要的逻辑
        # self.nav_list.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.nav_list.itemClicked.connect(
            lambda item: self.stacked_widget.setCurrentIndex(self.nav_list.row(item))
        )
        self.nav_list.setCurrentRow(0)
        
        # 按钮栏
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore_defaults)
        
        # 手动设置按钮文本，确保翻译正确
        self._update_button_text()
        
        main_layout.addWidget(self.button_box)

    def _add_page(self, name: str, creation_func):
        """添加页面到导航栏和内容区"""
        item = QListWidgetItem(name)
        item.setTextAlignment(Qt.AlignCenter)
        self.nav_list.addItem(item)
        
        # 创建滚动区域包装页面内容
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        page = creation_func()
        scroll_area.setWidget(page)
        
        self.stacked_widget.addWidget(scroll_area)

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
        self.setting_widgets['language'] = language_combo
        
        # 移除语言切换的即时刷新信号
        # language_combo.currentTextChanged.connect(self._on_language_changed)
        
        language_layout.addRow(t("settingsdialog.language"), language_combo)
        layout.addWidget(language_group)
        
        # 界面主题
        ui_theme_group = QGroupBox(t("settingsdialog.interface_theme"))
        ui_theme_layout = QFormLayout(ui_theme_group)
        
        ui_theme_combo = QComboBox()
        self.setting_widgets['ui_theme'] = ui_theme_combo
        
        ui_theme_layout.addRow(t("settingsdialog.subject"), ui_theme_combo)
        layout.addWidget(ui_theme_group)
        
        # 连接UI主题变化处理逻辑
        def on_ui_theme_changed(index):
            theme_name = ui_theme_combo.itemData(index)
            if theme_name:
                # 预览主题变化；如果用户取消，会在 reject() 中恢复原主题。
                main_window = self.parent()
                if hasattr(main_window, 'theme_manager'):
                    main_window.theme_manager.set_theme(theme_name)
        
        ui_theme_combo.currentIndexChanged.connect(on_ui_theme_changed)
        
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

        layout.addStretch()
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
        fps_spin.setSuffix(" fps")
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
        layout.addWidget(sync_group)

        layout.addStretch()
        return page

    def _create_performance_page(self) -> QWidget:
        """创建性能设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # 页面标题
        title_label = QLabel(t("settingsdialog.performance_settings"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())
        
        # 应用性能设置
        performance_group = QGroupBox(t("settingsdialog.application_performance_settings"))
        performance_layout = QFormLayout(performance_group)
        
        # 缓存大小
        cache_size_spin = QSpinBox()
        cache_size_spin.setRange(64, 2048)
        cache_size_spin.setValue(256)
        cache_size_spin.setSuffix(" MB")
        self.setting_widgets['cache_size'] = cache_size_spin
        performance_layout.addRow(t("settingsdialog.cache_size"), cache_size_spin)
        
        # 线程数量
        thread_count_spin = QSpinBox()
        thread_count_spin.setRange(1, 16)
        thread_count_spin.setValue(4)
        thread_count_spin.setSuffix(t("settingsdialog.count_suffix"))
        self.setting_widgets['thread_count'] = thread_count_spin
        performance_layout.addRow(t("settingsdialog.number_of_threads"), thread_count_spin)

        cache_info = QLabel(self._get_cache_info_text())
        cache_info.setObjectName("cacheInfoLabel")
        performance_layout.addRow(t("settingsdialog.cache_status"), cache_info)

        clear_cache_btn = QPushButton(t("settingsdialog.clear_display_cache"))
        clear_cache_btn.clicked.connect(lambda: self._clear_cache(cache_info))
        performance_layout.addRow(clear_cache_btn)
        
        layout.addWidget(performance_group)
        layout.addStretch()
        return page

    def _create_roi_settings_group(self) -> QGroupBox:
        """创建ROI设置组"""
        group = QGroupBox(t("settingsdialog.roi_settings"))
        layout = QVBoxLayout(group)
        
        # 主题选择
        theme_layout = QFormLayout()
        roi_theme_combo = QComboBox()
        self.setting_widgets['roi_theme'] = roi_theme_combo
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
        self.setting_widgets['roi.custom.border_color'] = border_color_btn
        appearance_layout.addRow(t("settingsdialog.border_color"), border_color_btn)
        
        # 填充颜色
        fill_color_btn = ColorButton()
        self.setting_widgets['roi.custom.fill_color'] = fill_color_btn
        appearance_layout.addRow(t("settingsdialog.fill_color"), fill_color_btn)
        
        # 选中时颜色
        selected_color_btn = ColorButton()
        self.setting_widgets['roi.custom.selected_color'] = selected_color_btn
        appearance_layout.addRow(t("settingsdialog.color_when_selected"), selected_color_btn)
        
        # 边框粗细
        border_width_spin = QSpinBox()
        border_width_spin.setRange(1, 10)
        border_width_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.border_width'] = border_width_spin
        appearance_layout.addRow(t("settingsdialog.border_thickness"), border_width_spin)
        
        custom_layout.addWidget(appearance_group)
        
        # 锚点设置
        anchor_group = QGroupBox(t("settingsdialog.anchor"))
        anchor_layout = QFormLayout(anchor_group)
        
        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets['roi.custom.anchor_color'] = anchor_color_btn
        anchor_layout.addRow(t("settingsdialog.anchor_color"), anchor_color_btn)
        
        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.anchor_size'] = anchor_size_spin
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
        self.setting_widgets['roi.custom.info_bg_color'] = info_bg_color_btn
        info_appearance_layout.addRow(t("settingsdialog.background_color"), info_bg_color_btn)

        # 选中背景颜色
        info_selected_bg_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_selected_bg_color'] = info_selected_bg_color_btn
        info_appearance_layout.addRow(t("settingsdialog.selected_background_color"), info_selected_bg_color_btn)
        
        # 文本颜色
        info_text_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_text_color'] = info_text_color_btn
        info_appearance_layout.addRow(t("settingsdialog.color"), info_text_color_btn)
        
        # 边框颜色
        info_border_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_border_color'] = info_border_color_btn
        info_appearance_layout.addRow(t("settingsdialog.border_color"), info_border_color_btn)
        
        # 字体大小
        info_font_size_spin = QSpinBox()
        info_font_size_spin.setRange(8, 24)
        info_font_size_spin.setSuffix(" pt")
        self.setting_widgets['roi.custom.info_font_size'] = info_font_size_spin
        info_appearance_layout.addRow(t("settingsdialog.font_size"), info_font_size_spin)
        
        # 圆角半径
        info_radius_spin = QSpinBox()
        info_radius_spin.setRange(0, 20)
        info_radius_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.info_radius'] = info_radius_spin
        info_appearance_layout.addRow(t("settingsdialog.fillet_radius"), info_radius_spin)
        
        # 内边距
        info_padding_spin = QSpinBox()
        info_padding_spin.setRange(2, 20)
        info_padding_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.info_padding'] = info_padding_spin
        info_appearance_layout.addRow(t("settingsdialog.inner_margin"), info_padding_spin)
        
        info_layout.addWidget(info_appearance_group)
        
        # 显示选项子组
        info_display_group = QGroupBox(t("settingsdialog.display_options"))
        info_display_layout = QFormLayout(info_display_group)
        
        # 数值精度
        info_precision_spin = QSpinBox()
        info_precision_spin.setRange(0, 6)
        self.setting_widgets['roi.custom.info_precision'] = info_precision_spin
        info_display_layout.addRow(t("settingsdialog.numerical_precision"), info_precision_spin)
        
        # 自动隐藏
        info_auto_hide_check = QCheckBox(t("settingsdialog.automatically_hide_when_the_mouse_leaves"))
        self.setting_widgets['roi.custom.info_auto_hide'] = info_auto_hide_check
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
            is_custom = theme_name == 'custom'
            
            # 如果不是自定义主题，则先加载所选主题的颜色进行预览
            if not is_custom:
                theme_data = self.themes.get('roi', {}).get(theme_name, {})
                for key, value in theme_data.items():
                    if key == "name":
                        continue
                    widget_key = f"roi.custom.{key}"
                    if widget_key in self.setting_widgets:
                        widget = self.setting_widgets[widget_key]
                        if isinstance(widget, ColorButton):
                            widget.setColor(qcolor_from_theme(value))
                        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                            widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))
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
        self.setting_widgets['measurement_theme'] = measurement_theme_combo
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
        self.setting_widgets['measurement.custom.line_color'] = line_color_btn
        appearance_layout.addRow(t("settingsdialog.line_color"), line_color_btn)
        
        # 线条粗细
        line_width_spin = QSpinBox()
        line_width_spin.setRange(1, 10)
        line_width_spin.setSuffix(" px")
        self.setting_widgets['measurement.custom.line_width'] = line_width_spin
        appearance_layout.addRow(t("settingsdialog.line_thickness"), line_width_spin)
        
        custom_layout.addWidget(appearance_group)
        
        # 锚点设置
        anchor_group = QGroupBox(t("settingsdialog.anchor"))
        anchor_layout = QFormLayout(anchor_group)
        
        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.anchor_color'] = anchor_color_btn
        anchor_layout.addRow(t("settingsdialog.anchor_color"), anchor_color_btn)
        
        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets['measurement.custom.anchor_size'] = anchor_size_spin
        anchor_layout.addRow(t("settingsdialog.anchor_size"), anchor_size_spin)
        
        custom_layout.addWidget(anchor_group)
        
        # 文本设置
        text_group = QGroupBox(t("settingsdialog.display_text"))
        text_layout = QFormLayout(text_group)
        
        # 距离文本颜色
        text_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.text_color'] = text_color_btn
        text_layout.addRow(t("settingsdialog.distance_from_color"), text_color_btn)
        
        # 距离文本背景色
        bg_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.background_color'] = bg_color_btn
        text_layout.addRow(t("settingsdialog.distance_from_background_color"), bg_color_btn)
        
        # 字体大小
        font_size_spin = QSpinBox()
        font_size_spin.setRange(8, 24)
        font_size_spin.setSuffix(" pt")
        self.setting_widgets['measurement.custom.font_size'] = font_size_spin
        text_layout.addRow(t("settingsdialog.font_size"), font_size_spin)
        
        custom_layout.addWidget(text_group)
        layout.addWidget(custom_group)
        
        # 连接主题变化和加载主题设置的逻辑
        def on_measurement_theme_changed(index):
            theme_name = measurement_theme_combo.itemData(index)
            is_custom = theme_name == 'custom'

            # 先根据是否是自定义主题，来启用/禁用控件
            self._enable_measurement_custom_controls(is_custom)
            
            # 如果不是自定义主题，则加载所选主题的颜色进行预览
            if not is_custom:
                theme_data = self.themes.get('measurement', {}).get(theme_name, {})
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
                            widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))
                        elif isinstance(widget, QCheckBox):
                            widget.setChecked(bool(value))
        
        measurement_theme_combo.currentIndexChanged.connect(on_measurement_theme_changed)
        
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
                name = getattr(handler, "__name__", handler.__class__.__name__).split(".")[-1]
                available = handler.is_available() if hasattr(handler, "is_available") else True
                handlers.append(f"{name}: {'可用' if available else '不可用'}")
            return "\n".join(handlers) if handlers else t("settingsdialog.no_pixel_decoder_detected")
        except Exception as e:
            return t("settingsdialog.decoder_detection_failed_prefix") + str(e)

    def _get_cache_info_text(self) -> str:
        """返回性能缓存状态文本。"""
        try:
            info = self.settings_manager.get_performance_manager().get_cache_info()
            return t("settingsdialog.cache_status_summary").replace(
                "%1", str(info.get("size_mb", 0))
            ).replace(
                "%2", str(info.get("item_count", 0))
            ).replace(
                "%3", f"{info.get('estimated_usage_mb', 0):.1f}"
            )
        except Exception as e:
            return t("settingsdialog.cache_status_unavailable_prefix") + str(e)

    def _clear_cache(self, label: QLabel) -> None:
        """清空显示缓存并刷新状态标签。"""
        try:
            self.settings_manager.get_performance_manager().clear_cache()
            label.setText(self._get_cache_info_text())
        except Exception as e:
            label.setText(t("settingsdialog.clear_cache_failed_prefix") + str(e))

    def _create_separator(self) -> QFrame:
        """创建分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _load_themes(self):
        """从主题目录加载所有 TOML 主题文件"""
        self.themes.clear()
        base_themes_dir = Path(__file__).parent.parent.parent / "themes"
        if not base_themes_dir.is_dir():
            return

        for category_dir in base_themes_dir.iterdir():
            if category_dir.is_dir():
                category = category_dir.name
                self.themes[category] = {}
                for theme_file in category_dir.glob("*.toml"):
                    try:
                        theme_data = toml.load(theme_file)
                        theme_name = theme_file.stem
                        self.themes[category][theme_name] = theme_data
                    except Exception as e:
                        logger.warning(f"加载主题文件失败 {theme_file}: {e}")
        
        self._populate_theme_combos()

    def _populate_theme_combos(self):
        """填充主题下拉框"""
        # UI主题
        ui_combo = self.setting_widgets.get('ui_theme')
        if ui_combo:
            ui_combo.blockSignals(True)
            ui_combo.clear()
            ui_themes = self.themes.get('ui', {})
            for theme_name, theme_data in ui_themes.items():
                display_name = theme_data.get('name', theme_name)
                ui_combo.addItem(display_name, theme_name)
            ui_combo.blockSignals(False)
        
        # ROI主题
        roi_combo = self.setting_widgets.get('roi_theme')
        if roi_combo:
            roi_combo.blockSignals(True)
            roi_combo.clear()
            roi_themes = self.themes.get('roi', {})
            
            # 确保自定义主题文件存在
            self._ensure_custom_theme_exists('roi')
            
            for theme_name, theme_data in roi_themes.items():
                display_name = theme_data.get('name', theme_name)
                roi_combo.addItem(display_name, theme_name)
            roi_combo.blockSignals(False)
        
        # 测量工具主题
        measurement_combo = self.setting_widgets.get('measurement_theme')
        if measurement_combo:
            measurement_combo.blockSignals(True)
            measurement_combo.clear()
            measurement_themes = self.themes.get('measurement', {})
            
            # 确保自定义主题文件存在
            self._ensure_custom_theme_exists('measurement')
            
            for theme_name, theme_data in measurement_themes.items():
                display_name = theme_data.get('name', theme_name)
                measurement_combo.addItem(display_name, theme_name)
            measurement_combo.blockSignals(False)

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
                    widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))

    def _load_current_settings(self):
        """加载当前设置"""
        # 加载语言设置
        language_combo = self.setting_widgets.get('language')
        if language_combo:
            saved_language = self.settings_manager.get_setting('language', 'en_US')
            index = language_combo.findData(saved_language)
            if index != -1:
                language_combo.setCurrentIndex(index)
        
        # 加载UI主题
        ui_combo = self.setting_widgets.get('ui_theme')
        if ui_combo:
            saved_theme = self.settings_manager.get_setting('ui_theme', 'dark')
            index = ui_combo.findData(saved_theme)
            if index != -1:
                ui_combo.blockSignals(True)
                ui_combo.setCurrentIndex(index)
                ui_combo.blockSignals(False)
        
        # 加载ROI主题
        roi_combo = self.setting_widgets.get('roi_theme')
        if roi_combo:
            saved_theme = self.settings_manager.get_setting('roi_theme', 'default')
            index = roi_combo.findData(saved_theme)
            if index == -1:
                index = roi_combo.findData('default')
            if index != -1:
                roi_combo.setCurrentIndex(index)
                # 触发主题加载逻辑
                roi_combo.currentIndexChanged.emit(index)
        
        # 加载测量工具主题
        measurement_combo = self.setting_widgets.get('measurement_theme')
        if measurement_combo:
            saved_theme = self.settings_manager.get_setting('measurement_theme', 'default')
            index = measurement_combo.findData(saved_theme)
            if index == -1:
                index = measurement_combo.findData('default')
            if index != -1:
                measurement_combo.setCurrentIndex(index)
                # 触发主题加载逻辑
                measurement_combo.currentIndexChanged.emit(index)
        
        # 加载性能设置
        cache_size_spin = self.setting_widgets.get('cache_size')
        if cache_size_spin:
            saved_cache_size = self.settings_manager.get_setting('cache_size', 256)
            cache_size_spin.setValue(saved_cache_size)
        
        thread_count_spin = self.setting_widgets.get('thread_count')
        if thread_count_spin:
            saved_thread_count = self.settings_manager.get_setting('thread_count', 4)
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
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index != -1:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(self._to_bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))

    def _get_widget_value(self, widget: QWidget):
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        return None

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _load_custom_settings(self):
        """加载自定义设置"""
        for key, widget in self.setting_widgets.items():
            if '.custom.' not in key:
                continue
            
            category = key.split('.')[0]
            theme_combo = self.setting_widgets.get(f'{category}_theme')
            selected_theme = theme_combo.currentData() if isinstance(theme_combo, QComboBox) else None
            if selected_theme != 'custom':
                continue

            saved_value = self.settings_manager.get_setting(key)
            
            # 如果没有保存值，从 custom 主题文件获取；再回退到默认主题。
            if saved_value is None:
                parts = key.split('.')
                if len(parts) >= 3 and parts[1] == 'custom':
                    field_name = parts[2]
                    
                    category_themes = self.themes.get(category, {})
                    custom_theme_data = category_themes.get('custom', {})
                    saved_value = custom_theme_data.get(field_name)

                    if saved_value is None:
                        default_theme_data = category_themes.get('default', {})
                        saved_value = default_theme_data.get(field_name)
                        if saved_value is None and field_name == 'info_selected_bg_color':
                            saved_value = default_theme_data.get('info_bg_color')
            
            if saved_value is None:
                continue
            
            # 设置控件值
            if isinstance(widget, ColorButton):
                widget.setColor(qcolor_from_theme(saved_value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(int(saved_value) if isinstance(widget, QSpinBox) else float(saved_value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(saved_value))

    def _restore_defaults(self):
        """恢复默认设置"""
        # 恢复语言默认值
        language_combo = self.setting_widgets.get('language')
        if language_combo:
            index = language_combo.findData('en_US')
            if index != -1:
                language_combo.setCurrentIndex(index)
        
        # 恢复UI主题默认值
        ui_combo = self.setting_widgets.get('ui_theme')
        if ui_combo:
            index = ui_combo.findData('dark')
            if index != -1:
                ui_combo.setCurrentIndex(index)
        
        # 恢复ROI主题默认值
        roi_combo = self.setting_widgets.get('roi_theme')
        if roi_combo:
            index = roi_combo.findData('default')
            if index != -1:
                roi_combo.setCurrentIndex(index)
        
        # 恢复测量工具主题默认值
        measurement_combo = self.setting_widgets.get('measurement_theme')
        if measurement_combo:
            index = measurement_combo.findData('default')
            if index != -1:
                measurement_combo.setCurrentIndex(index)
        
        # 恢复性能设置默认值
        cache_size_spin = self.setting_widgets.get('cache_size')
        if cache_size_spin:
            cache_size_spin.setValue(256)
        
        thread_count_spin = self.setting_widgets.get('thread_count')
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

    def reject(self):
        """取消设置并恢复对话框内预览过的 UI 主题。"""
        self._restore_previewed_ui_theme()
        super().reject()

    def _restore_previewed_ui_theme(self):
        main_window = self.parent()
        if hasattr(main_window, 'theme_manager'):
            current_theme = main_window.theme_manager.get_current_theme()
            if current_theme != self._original_ui_theme:
                main_window.theme_manager.set_theme(self._original_ui_theme)

    def _save_settings(self):
        """从UI控件收集并保存所有设置"""
        # 检查语言是否发生变化
        old_language = self.settings_manager.get_setting('language', 'en_US')
        new_language = self.setting_widgets['language'].currentData()
        language_changed = old_language != new_language
        
        # 保存语言设置
        self.settings_manager.set_setting('language', new_language)
        
        # 保存UI主题
        ui_combo = self.setting_widgets.get('ui_theme')
        if ui_combo:
            theme = ui_combo.itemData(ui_combo.currentIndex())
            self.settings_manager.set_setting('ui_theme', theme)
        
        # 保存ROI主题
        roi_combo = self.setting_widgets.get('roi_theme')
        if roi_combo:
            theme = roi_combo.itemData(roi_combo.currentIndex())
            self.settings_manager.set_setting('roi_theme', theme)
            # 如果是自定义主题，保存设置到TOML文件
            if theme == 'custom':
                self._save_theme_to_file('roi', theme)
        
        # 保存测量工具主题
        measurement_combo = self.setting_widgets.get('measurement_theme')
        if measurement_combo:
            theme = measurement_combo.itemData(measurement_combo.currentIndex())
            self.settings_manager.set_setting('measurement_theme', theme)
            # 如果是自定义主题，保存设置到TOML文件
            if theme == 'custom':
                self._save_theme_to_file('measurement', theme)
        
        # 保存性能设置
        cache_size_spin = self.setting_widgets.get('cache_size')
        if cache_size_spin:
            self.settings_manager.set_setting('cache_size', cache_size_spin.value())
        
        thread_count_spin = self.setting_widgets.get('thread_count')
        if thread_count_spin:
            self.settings_manager.set_setting('thread_count', thread_count_spin.value())

        for key in SIMPLE_SETTING_DEFAULTS:
            widget = self.setting_widgets.get(key)
            if widget is not None:
                self.settings_manager.set_setting(key, self._get_widget_value(widget))
        
        self.settings_manager.save_settings()

        # 如果语言发生变化，立即应用翻译
        if language_changed:
            self.translation_manager.load_translation(new_language)
            # 记录语言变更标志，供调用方使用
            self._language_changed = True
    
    def _save_theme_to_file(self, category: str, theme_name: str):
        """保存主题设置到TOML文件"""
        if theme_name != 'custom':
            return
        
        # 收集当前自定义控件的值
        theme_data = {'name': t("settingsdialog.custom")}
        
        for key, widget in self.setting_widgets.items():
            if not key.startswith(f'{category}.custom.'):
                continue
                
            field_name = key.split('.')[-1]  # 获取最后一部分作为字段名
            
            if isinstance(widget, ColorButton):
                theme_data[field_name] = widget.color().name()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                theme_data[field_name] = widget.value()
            elif isinstance(widget, QCheckBox):
                theme_data[field_name] = widget.isChecked()
        
        # 保存到TOML文件
        try:
            base_themes_dir = Path(__file__).parent.parent.parent / "themes"
            theme_file = base_themes_dir / category / f"{theme_name}.toml"
            theme_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(theme_file, 'w', encoding='utf-8') as f:
                toml.dump(theme_data, f)
            

            
            # 重新加载主题数据
            self.themes[category][theme_name] = theme_data
            
        except Exception as e:
            logger.warning(f"保存主题文件失败 ({category}/{theme_name}): {e}")

    def _ensure_custom_theme_exists(self, category: str):
        """确保自定义主题文件存在"""
        try:
            base_themes_dir = Path(__file__).parent.parent.parent / "themes"
            custom_theme_file = base_themes_dir / category / "custom.toml"
            
            if not custom_theme_file.exists():
                # 如果自定义主题文件不存在，从默认主题创建
                default_theme_file = base_themes_dir / category / "default.toml"
                custom_theme_data = {'name': '自定义'}
                
                if default_theme_file.exists():
                    # 从默认主题复制设置
                    try:
                        default_data = toml.load(default_theme_file)
                        custom_theme_data.update(default_data)
                        custom_theme_data['name'] = t("settingsdialog.custom")  # 确保名称是"自定义"
                    except Exception as e:
                        logger.warning(f"读取默认主题失败: {e}")
                
                # 创建自定义主题文件
                custom_theme_file.parent.mkdir(parents=True, exist_ok=True)
                with open(custom_theme_file, 'w', encoding='utf-8') as f:
                    toml.dump(custom_theme_data, f)
                

                
                # 将新创建的主题添加到内存中的主题数据
                if category not in self.themes:
                    self.themes[category] = {}
                self.themes[category]['custom'] = custom_theme_data
                
        except Exception as e:
            logger.warning(f"创建自定义主题文件失败 ({category}): {e}")
    
    def _enable_roi_custom_controls(self, enabled: bool):
        """启用/禁用ROI自定义控件"""
        roi_controls = [
            'roi.custom.border_color', 'roi.custom.fill_color', 'roi.custom.selected_color',
            'roi.custom.border_width', 'roi.custom.anchor_color', 'roi.custom.anchor_size',
            'roi.custom.info_bg_color', 'roi.custom.info_selected_bg_color',
            'roi.custom.info_text_color', 'roi.custom.info_border_color',
            'roi.custom.info_font_size', 'roi.custom.info_radius', 'roi.custom.info_padding',
            'roi.custom.info_precision', 'roi.custom.info_auto_hide'
        ]
        for control_name in roi_controls:
            if control_name in self.setting_widgets:
                widget = self.setting_widgets[control_name]
                widget.setEnabled(enabled)
    
    def _enable_measurement_custom_controls(self, enabled: bool):
        """启用/禁用测量工具自定义控件"""
        measurement_controls = [
            'measurement.custom.line_color', 'measurement.custom.line_width',
            'measurement.custom.anchor_color', 'measurement.custom.anchor_size',
            'measurement.custom.text_color', 'measurement.custom.background_color',
            'measurement.custom.font_size'
        ]
        for control_name in measurement_controls:
            if control_name in self.setting_widgets:
                widget = self.setting_widgets[control_name]
                widget.setEnabled(enabled)
    
    def _load_roi_theme(self, theme_name: str):
        """加载ROI主题"""
        if theme_name:
            self._apply_theme('roi', theme_name)
    
    def _load_measurement_theme(self, theme_name: str):
        """加载测量工具主题"""
        if theme_name:
            self._apply_theme('measurement', theme_name)

    def _update_button_text(self):
        """更新按钮文本"""
        self.button_box.button(QDialogButtonBox.Ok).setText(t("settingsdialog.ok"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(t("settingsdialog.cancel"))
        self.button_box.button(QDialogButtonBox.RestoreDefaults).setText(t("settingsdialog.restore_default"))
