#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题管理器

负责应用程序界面主题的加载和应用
"""

import toml
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QObject, Signal
from typing import Dict, Any, Optional
from medimager.utils.settings import SettingsManager
from medimager.utils.logger import get_logger


def get_theme_settings(category: str, theme_name: str = None) -> Dict[str, Any]:
    """
    统一的主题设置读取函数
    
    Args:
        category: 主题类别 ('roi', 'measurement', 'ui')
        theme_name: 主题名称，如果为None则从设置中获取当前主题
    
    Returns:
        包含主题设置的字典
    """
    try:
        # 如果没有指定主题名称，从设置中获取当前主题
        if theme_name is None:
            settings_manager = SettingsManager()
            theme_name = settings_manager.get_setting(f'{category}_theme', 'default')
        
        # 加载主题文件
        themes_dir = Path(__file__).parent.parent / "themes" / category
        theme_file = themes_dir / f"{theme_name}.toml"
        
        if theme_file.exists():
            return toml.load(theme_file)
        else:
            # 如果主题文件不存在，尝试加载默认主题
            default_theme_file = themes_dir / "default.toml"
            if default_theme_file.exists():
                return toml.load(default_theme_file)
            
    except Exception as e:
        print(f"加载{category}主题文件失败: {e}")
    
    # 返回空字典作为备用
    return {}


class ThemeManager(QObject):
    """主题管理器"""
    
    theme_changed = Signal(str)  # 主题改变信号
    
    def __init__(self, settings_manager: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.logger = get_logger(__name__)
        self.themes: Dict[str, Dict[str, Any]] = {}
        self._load_ui_themes()
    
    def _load_ui_themes(self):
        """加载UI主题文件"""
        themes_dir = Path(__file__).parent.parent / "themes" / "ui"
        if not themes_dir.exists():
            self.logger.warning(f"UI主题目录不存在: {themes_dir}")
            return
        
        for theme_file in themes_dir.glob("*.toml"):
            try:
                theme_data = toml.load(theme_file)
                theme_name = theme_file.stem
                self.themes[theme_name] = theme_data
                self.logger.info(f"加载UI主题: {theme_name}")
            except Exception as e:
                self.logger.error(f"加载主题文件失败 {theme_file}: {e}")
    
    def get_current_theme(self) -> str:
        """获取当前主题名称"""
        return self.settings_manager.get_setting('ui_theme', 'dark')  # 默认深色主题
    
    def set_theme(self, theme_name: str):
        """设置主题"""
        if theme_name not in self.themes:
            self.logger.warning(f"主题不存在: {theme_name}")
            return
        
        self.settings_manager.set_setting('ui_theme', theme_name)
        self.apply_current_theme()
        self.theme_changed.emit(theme_name)
    
    def apply_current_theme(self):
        """应用当前主题"""
        theme_name = self.get_current_theme()
        self.apply_theme(theme_name)
    
    def apply_theme(self, theme_name: str):
        """应用指定主题"""
        if theme_name not in self.themes:
            self.logger.warning(f"主题不存在: {theme_name}")
            return
        
        theme_data = self.themes[theme_name]
        stylesheet = self._generate_stylesheet(theme_data)
        
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet)
            self.logger.info(f"应用主题: {theme_name}")
    
    def _generate_stylesheet(self, theme_data: Dict[str, Any]) -> str:
        """根据主题数据生成样式表"""
        bg_color = theme_data.get('background_color', '#F0F0F0')
        text_color = theme_data.get('text_color', '#000000')
        highlight_color = theme_data.get('highlight_color', '#3498DB')
        
        # 计算衍生颜色
        border_color = self._adjust_color_brightness(bg_color, -20)
        hover_color = self._adjust_color_brightness(highlight_color, 20)
        pressed_color = self._adjust_color_brightness(highlight_color, -20)
        
        stylesheet = f"""
        /* 全局样式 */
        QMainWindow {{
            background-color: {bg_color};
            color: {text_color};
        }}
        
        QWidget {{
            background-color: {bg_color};
            color: {text_color};
        }}
        
        /* 菜单栏 */
        QMenuBar {{
            background-color: {bg_color};
            color: {text_color};
            border-bottom: 1px solid {border_color};
        }}
        
        QMenuBar::item {{
            background-color: transparent;
            padding: 4px 8px;
        }}
        
        QMenuBar::item:selected {{
            background-color: {highlight_color};
            color: white;
        }}
        
        QMenu {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
        }}
        
        QMenu::item {{
            padding: 6px 20px;
        }}
        
        QMenu::item:selected {{
            background-color: {highlight_color};
            color: white;
        }}
        
        /* 工具栏 */
        QToolBar {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            spacing: 2px;
        }}
        
        QToolButton {{
            background-color: transparent;
            border: 1px solid transparent;
            padding: 4px;
            margin: 1px;
        }}
        
        QToolButton:hover {{
            background-color: {hover_color};
            border: 1px solid {highlight_color};
        }}
        
        QToolButton:pressed {{
            background-color: {pressed_color};
        }}
        
        QToolButton:checked {{
            background-color: {highlight_color};
            color: white;
        }}
        
        /* 工具栏按钮菜单 */
        QToolButton::menu-button {{
            border: none;
            width: 16px;
        }}
        
        QToolButton::menu-arrow {{
            image: none;
            border: none;
            width: 8px;
            height: 8px;
        }}
        
        QToolButton::menu-arrow:open {{
            top: 1px;
            left: 1px;
        }}
        
        QToolButton[popupMode="1"] {{
            color: {text_color};
            padding-right: 16px;
        }}
        
        QToolButton[popupMode="1"]:hover {{
            color: white;
        }}
        
        QToolButton[popupMode="1"]:checked {{
            color: white;
        }}
        
        /* 状态栏 */
        QStatusBar {{
            background-color: {bg_color};
            color: {text_color};
            border-top: 1px solid {border_color};
        }}
        
        /* 分割器 */
        QSplitter::handle {{
            background-color: {border_color};
        }}
        
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        
        QSplitter::handle:vertical {{
            height: 2px;
        }}
        
        /* 面板 */
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {border_color};
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 4px;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px 0 4px;
        }}
        
        /* 按钮 */
        QPushButton {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            padding: 6px 12px;
            border-radius: 4px;
        }}
        
        QPushButton:hover {{
            background-color: {hover_color};
        }}
        
        QPushButton:pressed {{
            background-color: {pressed_color};
        }}
        
        QPushButton:disabled {{
            color: gray;
            border-color: gray;
        }}
        
        /* 输入框 */
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            padding: 4px;
            border-radius: 2px;
        }}
        
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
            border-color: {highlight_color};
        }}
        
        /* 下拉框 */
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        
        QComboBox::down-arrow {{
            width: 12px;
            height: 12px;
        }}
        
        QComboBox QAbstractItemView {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            selection-background-color: {highlight_color};
        }}
        
        /* 列表 */
        QListWidget {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            alternate-background-color: {self._adjust_color_brightness(bg_color, 5)};
        }}
        
        QListWidget::item {{
            padding: 4px;
            border-bottom: 1px solid {border_color};
        }}
        
        QListWidget::item:selected {{
            background-color: {highlight_color};
            color: white;
        }}
        
        QListWidget::item:hover {{
            background-color: {hover_color};
        }}
        
        /* 标签页 */
        QTabWidget::pane {{
            border: 1px solid {border_color};
        }}
        
        QTabBar::tab {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            padding: 6px 12px;
            margin-right: 2px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {highlight_color};
            color: white;
        }}
        
        QTabBar::tab:hover {{
            background-color: {hover_color};
        }}
        
        /* 滚动条 */
        QScrollBar:vertical {{
            background-color: {bg_color};
            width: 12px;
            border: 1px solid {border_color};
        }}
        
        QScrollBar::handle:vertical {{
            background-color: {border_color};
            border-radius: 4px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background-color: {highlight_color};
        }}
        
        QScrollBar:horizontal {{
            background-color: {bg_color};
            height: 12px;
            border: 1px solid {border_color};
        }}
        
        QScrollBar::handle:horizontal {{
            background-color: {border_color};
            border-radius: 4px;
            min-width: 20px;
        }}
        
        QScrollBar::handle:horizontal:hover {{
            background-color: {highlight_color};
        }}
        
        /* 对话框 */
        QDialog {{
            background-color: {bg_color};
        }}
        
        /* 设置对话框特殊样式 */
        QListWidget#settings_nav {{
            background-color: {self._adjust_color_brightness(bg_color, -5)};
            border: 1px solid {border_color};
            border-radius: 4px;
        }}
        
        QListWidget#settings_nav::item {{
            padding: 10px;
            border-bottom: 1px solid {border_color};
        }}
        
        QListWidget#settings_nav::item:selected {{
            background-color: {highlight_color};
            color: white;
        }}
        """
        
        return stylesheet
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            # 移除 # 符号
            color_hex = color_hex.lstrip('#')
            
            # 转换为RGB
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            
            # 调整亮度
            r = max(0, min(255, r + amount))
            g = max(0, min(255, g + amount))
            b = max(0, min(255, b + amount))
            
            # 转换回十六进制
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return color_hex  # 如果出错，返回原色
    
    def get_available_themes(self) -> list:
        """获取可用主题列表"""
        return list(self.themes.keys()) 