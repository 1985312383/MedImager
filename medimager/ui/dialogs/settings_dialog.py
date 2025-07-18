#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置对话框

根据设计文档重构的设置界面，包含左侧导航栏和右侧内容区。
"""

import os
import toml
import glob
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QStackedWidget,
    QLabel, QColorDialog, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QComboBox, QCheckBox, QFrame,
    QDialogButtonBox, QListWidgetItem, QScrollArea, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap, QIcon
from typing import Dict, Any, List, Tuple, Optional
from medimager.utils.settings import SettingsManager
from medimager.utils.i18n import TranslationManager


class ColorButton(QPushButton):
    """带颜色图标的颜色选择按钮"""
    colorChanged = Signal(QColor)
    
    def __init__(self, color: QColor = None, parent=None):
        super().__init__(parent)
        self._color = color or QColor(255, 255, 255)
        self.setText(self.tr("选择..."))
        self.clicked.connect(self._choose_color)
        self._update_color_icon()
    
    def color(self) -> QColor:
        return self._color
    
    def setColor(self, color: QColor):
        if color.isValid():
            self._color = color
            self._update_color_icon()
            # 同时在按钮文本中显示颜色值
            self.setText(f"{self.tr('选择...')} ({color.name()})")
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
        color = QColorDialog.getColor(self._color, self, self.tr("选择颜色"))
        if color.isValid():
            self.setColor(color)


class SettingsDialog(QDialog):
    """设置对话框，采用左侧导航布局"""
    
    def __init__(self, settings_manager: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.translation_manager = TranslationManager()
        self.setWindowTitle(self.tr("设置"))
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
        # 语言代码到显示名称的映射
        language_names = {
            'zh_CN': '简体中文',
            'en_US': 'English',
            'fr_FR': 'Français',
            'de_DE': 'Deutsch',
            'es_ES': 'Español',
            'it_IT': 'Italiano',
            'pt_PT': 'Português',
            'ru_RU': 'Русский',
            'ja_JP': '日本語',
            'ko_KR': '한국어'
        }
        
        # 获取translations目录路径
        current_dir = Path(__file__).parent.parent.parent  # medimager目录
        translations_dir = current_dir / 'translations'
        
        supported = {}
        
        # 默认支持中文
        supported['zh_CN'] = language_names.get('zh_CN', '简体中文')
        
        if translations_dir.exists():
            # 查找所有.qm文件
            qm_files = list(translations_dir.glob('*.qm'))
            for qm_file in qm_files:
                lang_code = qm_file.stem  # 文件名不含扩展名
                if lang_code != 'zh_CN':  # 中文已经添加
                    display_name = language_names.get(lang_code, lang_code)
                    supported[lang_code] = display_name
        
        return supported
    
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
        self._add_page(self.tr("通用"), self._create_general_page)
        self._add_page(self.tr("工具"), self._create_tools_page)
        self._add_page(self.tr("性能"), self._create_performance_page)
        
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
        title_label = QLabel(self.tr("通用设置"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())
        
        # 界面语言
        language_group = QGroupBox(self.tr("界面语言"))
        language_layout = QFormLayout(language_group)
        
        language_combo = QComboBox()
        # 自动添加支持的语言
        for lang_code, display_name in self.supported_languages.items():
            language_combo.addItem(display_name, lang_code)
        self.setting_widgets['language'] = language_combo
        
        # 移除语言切换的即时刷新信号
        # language_combo.currentTextChanged.connect(self._on_language_changed)
        
        language_layout.addRow(self.tr("语言:"), language_combo)
        layout.addWidget(language_group)
        
        # 界面主题
        ui_theme_group = QGroupBox(self.tr("界面主题"))
        ui_theme_layout = QFormLayout(ui_theme_group)
        
        ui_theme_combo = QComboBox()
        self.setting_widgets['ui_theme'] = ui_theme_combo
        
        ui_theme_layout.addRow(self.tr("主题:"), ui_theme_combo)
        layout.addWidget(ui_theme_group)
        
        # 连接UI主题变化处理逻辑
        def on_ui_theme_changed(index):
            theme_name = ui_theme_combo.itemData(index)
            if theme_name:
                # 立即应用主题变化
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
        title_label = QLabel(self.tr("工具设置"))
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

    def _create_performance_page(self) -> QWidget:
        """创建性能设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # 页面标题
        title_label = QLabel(self.tr("性能设置"))
        title_label.setFont(self._get_title_font())
        layout.addWidget(title_label)
        layout.addWidget(self._create_separator())
        
        # 应用性能设置
        performance_group = QGroupBox(self.tr("应用性能设置"))
        performance_layout = QFormLayout(performance_group)
        
        # 缓存大小
        cache_size_spin = QSpinBox()
        cache_size_spin.setRange(64, 2048)
        cache_size_spin.setValue(256)
        cache_size_spin.setSuffix(" MB")
        self.setting_widgets['cache_size'] = cache_size_spin
        performance_layout.addRow(self.tr("缓存大小:"), cache_size_spin)
        
        # 线程数量
        thread_count_spin = QSpinBox()
        thread_count_spin.setRange(1, 16)
        thread_count_spin.setValue(4)
        thread_count_spin.setSuffix(self.tr(" 个"))
        self.setting_widgets['thread_count'] = thread_count_spin
        performance_layout.addRow(self.tr("线程数量:"), thread_count_spin)
        
        layout.addWidget(performance_group)
        layout.addStretch()
        return page

    def _create_roi_settings_group(self) -> QGroupBox:
        """创建ROI设置组"""
        group = QGroupBox(self.tr("ROI设置"))
        layout = QVBoxLayout(group)
        
        # 主题选择
        theme_layout = QFormLayout()
        roi_theme_combo = QComboBox()
        self.setting_widgets['roi_theme'] = roi_theme_combo
        theme_layout.addRow(self.tr("主题:"), roi_theme_combo)
        layout.addLayout(theme_layout)
        
        # 自定义设置组
        custom_group = QGroupBox(self.tr("自定义设置"))
        custom_layout = QVBoxLayout(custom_group)
        
        # 外观设置
        appearance_group = QGroupBox(self.tr("外观"))
        appearance_layout = QFormLayout(appearance_group)
        
        # 边框颜色
        border_color_btn = ColorButton()
        self.setting_widgets['roi.custom.border_color'] = border_color_btn
        appearance_layout.addRow(self.tr("边框颜色:"), border_color_btn)
        
        # 填充颜色
        fill_color_btn = ColorButton()
        self.setting_widgets['roi.custom.fill_color'] = fill_color_btn
        appearance_layout.addRow(self.tr("填充颜色:"), fill_color_btn)
        
        # 选中时颜色
        selected_color_btn = ColorButton()
        self.setting_widgets['roi.custom.selected_color'] = selected_color_btn
        appearance_layout.addRow(self.tr("选中时颜色:"), selected_color_btn)
        
        # 边框粗细
        border_width_spin = QSpinBox()
        border_width_spin.setRange(1, 10)
        border_width_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.border_width'] = border_width_spin
        appearance_layout.addRow(self.tr("边框粗细:"), border_width_spin)
        
        custom_layout.addWidget(appearance_group)
        
        # 锚点设置
        anchor_group = QGroupBox(self.tr("锚点"))
        anchor_layout = QFormLayout(anchor_group)
        
        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets['roi.custom.anchor_color'] = anchor_color_btn
        anchor_layout.addRow(self.tr("锚点颜色:"), anchor_color_btn)
        
        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.anchor_size'] = anchor_size_spin
        anchor_layout.addRow(self.tr("锚点大小:"), anchor_size_spin)
        
        custom_layout.addWidget(anchor_group)
        
        # 信息板设置
        info_group = QGroupBox(self.tr("信息板设置"))
        info_layout = QVBoxLayout(info_group)
        
        # 外观子组
        info_appearance_group = QGroupBox(self.tr("外观"))
        info_appearance_layout = QFormLayout(info_appearance_group)
        
        # 背景颜色
        info_bg_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_bg_color'] = info_bg_color_btn
        info_appearance_layout.addRow(self.tr("背景颜色:"), info_bg_color_btn)
        
        # 文本颜色
        info_text_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_text_color'] = info_text_color_btn
        info_appearance_layout.addRow(self.tr("文本颜色:"), info_text_color_btn)
        
        # 边框颜色
        info_border_color_btn = ColorButton()
        self.setting_widgets['roi.custom.info_border_color'] = info_border_color_btn
        info_appearance_layout.addRow(self.tr("边框颜色:"), info_border_color_btn)
        
        # 字体大小
        info_font_size_spin = QSpinBox()
        info_font_size_spin.setRange(8, 24)
        info_font_size_spin.setSuffix(" pt")
        self.setting_widgets['roi.custom.info_font_size'] = info_font_size_spin
        info_appearance_layout.addRow(self.tr("字体大小:"), info_font_size_spin)
        
        # 圆角半径
        info_radius_spin = QSpinBox()
        info_radius_spin.setRange(0, 20)
        info_radius_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.info_radius'] = info_radius_spin
        info_appearance_layout.addRow(self.tr("圆角半径:"), info_radius_spin)
        
        # 内边距
        info_padding_spin = QSpinBox()
        info_padding_spin.setRange(2, 20)
        info_padding_spin.setSuffix(" px")
        self.setting_widgets['roi.custom.info_padding'] = info_padding_spin
        info_appearance_layout.addRow(self.tr("内边距:"), info_padding_spin)
        
        info_layout.addWidget(info_appearance_group)
        
        # 显示选项子组
        info_display_group = QGroupBox(self.tr("显示选项"))
        info_display_layout = QFormLayout(info_display_group)
        
        # 数值精度
        info_precision_spin = QSpinBox()
        info_precision_spin.setRange(0, 6)
        self.setting_widgets['roi.custom.info_precision'] = info_precision_spin
        info_display_layout.addRow(self.tr("数值精度:"), info_precision_spin)
        
        # 自动隐藏
        info_auto_hide_check = QCheckBox(self.tr("鼠标离开时自动隐藏"))
        self.setting_widgets['roi.custom.info_auto_hide'] = info_auto_hide_check
        info_display_layout.addRow(info_auto_hide_check)
        
        info_layout.addWidget(info_display_group)
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
                            widget.setColor(QColor(value))
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
        group = QGroupBox(self.tr("测量工具"))
        layout = QVBoxLayout(group)
        
        # 主题选择
        theme_layout = QFormLayout()
        measurement_theme_combo = QComboBox()
        self.setting_widgets['measurement_theme'] = measurement_theme_combo
        theme_layout.addRow(self.tr("主题:"), measurement_theme_combo)
        layout.addLayout(theme_layout)
        
        # 自定义设置组
        custom_group = QGroupBox(self.tr("自定义设置"))
        custom_layout = QVBoxLayout(custom_group)
        
        # 外观设置
        appearance_group = QGroupBox(self.tr("外观"))
        appearance_layout = QFormLayout(appearance_group)
        
        # 线条颜色
        line_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.line_color'] = line_color_btn
        appearance_layout.addRow(self.tr("线条颜色:"), line_color_btn)
        
        # 线条粗细
        line_width_spin = QSpinBox()
        line_width_spin.setRange(1, 10)
        line_width_spin.setSuffix(" px")
        self.setting_widgets['measurement.custom.line_width'] = line_width_spin
        appearance_layout.addRow(self.tr("线条粗细:"), line_width_spin)
        
        custom_layout.addWidget(appearance_group)
        
        # 锚点设置
        anchor_group = QGroupBox(self.tr("锚点"))
        anchor_layout = QFormLayout(anchor_group)
        
        # 锚点颜色
        anchor_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.anchor_color'] = anchor_color_btn
        anchor_layout.addRow(self.tr("锚点颜色:"), anchor_color_btn)
        
        # 锚点大小
        anchor_size_spin = QSpinBox()
        anchor_size_spin.setRange(4, 20)
        anchor_size_spin.setSuffix(" px")
        self.setting_widgets['measurement.custom.anchor_size'] = anchor_size_spin
        anchor_layout.addRow(self.tr("锚点大小:"), anchor_size_spin)
        
        custom_layout.addWidget(anchor_group)
        
        # 文本设置
        text_group = QGroupBox(self.tr("文本"))
        text_layout = QFormLayout(text_group)
        
        # 距离文本颜色
        text_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.text_color'] = text_color_btn
        text_layout.addRow(self.tr("距离文本颜色:"), text_color_btn)
        
        # 距离文本背景色
        bg_color_btn = ColorButton()
        self.setting_widgets['measurement.custom.background_color'] = bg_color_btn
        text_layout.addRow(self.tr("距离文本背景色:"), bg_color_btn)
        
        # 字体大小
        font_size_spin = QSpinBox()
        font_size_spin.setRange(8, 24)
        font_size_spin.setSuffix(" pt")
        self.setting_widgets['measurement.custom.font_size'] = font_size_spin
        text_layout.addRow(self.tr("字体大小:"), font_size_spin)
        
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
                            color = QColor(value)
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
                        pass  # 静默处理主题加载失败
        
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
                    widget.setColor(QColor(value))
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))

    def _load_current_settings(self):
        """加载当前设置"""
        # 加载语言设置
        language_combo = self.setting_widgets.get('language')
        if language_combo:
            saved_language = self.settings_manager.get_setting('language', 'zh_CN')
            index = language_combo.findData(saved_language)
            if index != -1:
                language_combo.setCurrentIndex(index)
        
        # 加载UI主题
        ui_combo = self.setting_widgets.get('ui_theme')
        if ui_combo:
            saved_theme = self.settings_manager.get_setting('ui_theme', 'light')
            index = ui_combo.findData(saved_theme)
            if index != -1:
                ui_combo.setCurrentIndex(index)
        
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
        
        # 加载自定义设置
        self._load_custom_settings()

    def _load_custom_settings(self):
        """加载自定义设置"""
        for key, widget in self.setting_widgets.items():
            if '.custom.' not in key:
                continue
            
            saved_value = self.settings_manager.get_setting(key)
            
            # 如果没有保存值，从主题文件获取默认值
            if saved_value is None:
                parts = key.split('.')
                if len(parts) >= 3 and parts[1] == 'custom':
                    category = parts[0]
                    field_name = parts[2]
                    
                    # 获取默认主题数据
                    category_themes = self.themes.get(category, {})
                    if 'default' in category_themes:
                        default_theme_data = category_themes['default']
                    elif category_themes:
                        first_theme_name = list(category_themes.keys())[0]
                        default_theme_data = category_themes[first_theme_name]
                    else:
                        default_theme_data = {}
                    
                    saved_value = default_theme_data.get(field_name)
            
            if saved_value is None:
                continue
            
            # 设置控件值
            if isinstance(widget, ColorButton):
                widget.setColor(QColor(saved_value))
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

    def accept(self):
        """保存设置并关闭对话框"""
        self._save_settings()
        super().accept()

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
        
        self.settings_manager.save_settings()
        
        # 如果语言发生变化，提示用户重启应用
        if language_changed:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                self.tr("语言设置"),
                self.tr("语言设置将在下次启动时完全生效。")
            )
    
    def _save_theme_to_file(self, category: str, theme_name: str):
        """保存主题设置到TOML文件"""
        if theme_name != 'custom':
            return
        
        # 收集当前自定义控件的值
        theme_data = {'name': self.tr('自定义')}
        
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
            pass  # 静默处理保存失败

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
                        custom_theme_data['name'] = self.tr('自定义')  # 确保名称是"自定义"
                    except Exception as e:
                        pass  # 静默处理读取失败
                
                # 创建自定义主题文件
                custom_theme_file.parent.mkdir(parents=True, exist_ok=True)
                with open(custom_theme_file, 'w', encoding='utf-8') as f:
                    toml.dump(custom_theme_data, f)
                

                
                # 将新创建的主题添加到内存中的主题数据
                if category not in self.themes:
                    self.themes[category] = {}
                self.themes[category]['custom'] = custom_theme_data
                
        except Exception as e:
            pass  # 静默处理创建失败
    
    def _enable_roi_custom_controls(self, enabled: bool):
        """启用/禁用ROI自定义控件"""
        roi_controls = [
            'roi.custom.border_color', 'roi.custom.fill_color', 'roi.custom.selected_color',
            'roi.custom.border_width', 'roi.custom.anchor_color', 'roi.custom.anchor_size',
            'roi.custom.info_bg_color', 'roi.custom.info_text_color', 'roi.custom.info_border_color',
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
        self.button_box.button(QDialogButtonBox.Ok).setText(self.tr("确定"))
        self.button_box.button(QDialogButtonBox.Cancel).setText(self.tr("取消"))
        self.button_box.button(QDialogButtonBox.RestoreDefaults).setText(self.tr("恢复默认"))