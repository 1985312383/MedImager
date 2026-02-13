#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题管理器

负责应用程序界面主题的加载和应用
"""

import toml
import weakref
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QObject, Signal, QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from typing import Dict, Any, Optional
from medimager.utils.settings import SettingsManager
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


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
        self.available_themes = self._load_ui_themes()
        self.current_theme = self.get_current_theme()
        
        # 注册的主题组件列表 - 使用WeakSet防止内存泄漏
        # 当Qt组件被销毁时，弱引用自动失效，不会保留悬空引用
        self._registered_components = weakref.WeakSet()

    def register_component(self, component) -> None:
        """注册需要主题管理的组件

        Args:
            component: 需要主题管理的组件，应该实现以下方法之一：
                      - update_theme(theme_name: str)
                      - _on_theme_changed(theme_name: str)
                      - apply_theme(theme_name: str)
        """
        if component not in self._registered_components:
            self._registered_components.add(component)
            logger.debug(f"[ThemeManager.register_component] 注册主题组件: {component.__class__.__name__}")

            # 立即应用当前主题
            self._apply_theme_to_component(component, self.current_theme)
        else:
            logger.debug(f"[ThemeManager.register_component] 组件 {component.__class__.__name__} 已经注册，跳过")

    def unregister_component(self, component) -> None:
        """取消注册主题组件"""
        self._registered_components.discard(component)
        logger.debug(f"[ThemeManager.unregister_component] 取消注册主题组件: {component.__class__.__name__}")

    def _apply_theme_to_component(self, component, theme_name: str) -> None:
        """为单个组件应用主题"""
        try:
            if hasattr(component, 'update_theme'):
                component.update_theme(theme_name)
            elif hasattr(component, '_on_theme_changed'):
                component._on_theme_changed(theme_name)
            elif hasattr(component, 'apply_theme'):
                component.apply_theme(theme_name)
            else:
                logger.warning(f"[ThemeManager._apply_theme_to_component] 组件 {component.__class__.__name__} 没有实现主题更新方法")

        except Exception as e:
            logger.error(f"[ThemeManager._apply_theme_to_component] 为组件 {component.__class__.__name__} 应用主题失败: {e}", exc_info=True)

    def _apply_theme_to_all_components(self, theme_name: str) -> None:
        """为所有注册的组件应用主题"""
        # 迭代WeakSet的快照，防止迭代期间集合变化
        components = list(self._registered_components)
        logger.debug(f"[ThemeManager._apply_theme_to_all_components] 开始为 {len(components)} 个组件应用主题: {theme_name}")

        if not components:
            return

        success_count = 0
        for component in components:
            try:
                self._apply_theme_to_component(component, theme_name)
                success_count += 1
            except Exception as e:
                logger.error(f"[ThemeManager._apply_theme_to_all_components] 为组件应用主题失败: {e}")

        logger.debug(f"[ThemeManager._apply_theme_to_all_components] 主题应用完成: 成功 {success_count}/{len(components)} 个组件")
    
    def _load_ui_themes(self):
        """加载UI主题文件"""
        themes_dir = Path(__file__).parent.parent / "themes" / "ui"
        themes = {}
        
        if not themes_dir.exists():
            logger.warning(f"UI主题目录不存在: {themes_dir}")
            return themes
        
        for theme_file in themes_dir.glob("*.toml"):
            try:
                theme_data = toml.load(theme_file)
                theme_name = theme_file.stem
                themes[theme_name] = theme_data
                logger.info(f"加载UI主题: {theme_name}")
            except Exception as e:
                logger.error(f"加载主题文件失败 {theme_file}: {e}")
        
        self.themes = themes  # 保持向后兼容
        return themes
    
    def get_current_theme(self) -> str:
        """获取当前主题名称"""
        return self.settings_manager.get_setting('ui_theme', 'dark')  # 默认深色主题
    
    def set_theme(self, theme_name: str):
        """设置主题"""
        logger.info(f"[ThemeManager.set_theme] 开始设置主题: {theme_name}")
        
        if theme_name not in self.themes:
            logger.warning(f"[ThemeManager.set_theme] 主题不存在: {theme_name}")
            return
        
        logger.info(f"[ThemeManager.set_theme] 当前注册组件数量: {len(self._registered_components)}")
        for i, comp in enumerate(self._registered_components):
            logger.info(f"[ThemeManager.set_theme] 注册组件 {i+1}: {comp.__class__.__name__} (ID: {id(comp)})")
        
        self.current_theme = theme_name
        self.settings_manager.set_setting('ui_theme', theme_name)
        logger.info(f"[ThemeManager.set_theme] 应用全局主题样式")
        self.apply_current_theme()
        
        # 为所有注册的组件应用新主题
        logger.info(f"[ThemeManager.set_theme] 开始为注册组件应用主题")
        self._apply_theme_to_all_components(theme_name)
        
        logger.info(f"[ThemeManager.set_theme] 发送主题变更信号")
        self.theme_changed.emit(theme_name)
        logger.info(f"[ThemeManager.set_theme] 主题设置完成: {theme_name}")
    
    def apply_current_theme(self):
        """应用当前主题"""
        theme_name = self.get_current_theme()
        self.apply_theme(theme_name)
    
    def apply_theme(self, theme_name: str):
        """应用指定主题"""
        if theme_name not in self.themes:
            logger.warning(f"主题不存在: {theme_name}")
            return
        
        theme_data = self.themes[theme_name]
        stylesheet = self._generate_stylesheet(theme_data)
        
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet)
            logger.info(f"应用主题: {theme_name}")
        else:
            logger.error("无法获取QApplication实例")
    
    def _generate_stylesheet(self, theme_data: Dict[str, Any]) -> str:
        """生成样式表"""
        logger.debug(f"[ThemeManager._generate_stylesheet] 生成样式表: {theme_data.get('name', 'unknown')}")
        
        # 获取基本颜色
        bg_color = theme_data.get('background_color', '#F0F0F0')
        text_color = theme_data.get('text_color', '#000000')
        border_color = theme_data.get('border_color', '#CCCCCC')
        highlight_color = theme_data.get('highlight_color', '#0078D4')
        
        # 计算背景色亮度来决定悬浮效果方向
        bg_brightness = self._get_color_brightness(bg_color)
        is_dark_bg = bg_brightness < 128  # 亮度小于128认为是深色背景
        
        # 根据背景色亮度决定悬浮效果方向
        hover_brightness_delta = 30 if is_dark_bg else -30
        pressed_brightness_delta = 50 if is_dark_bg else -50
        checked_brightness_delta = 40 if is_dark_bg else -40
        checked_hover_brightness_delta = 60 if is_dark_bg else -60
        border_hover_delta = 40 if is_dark_bg else -40
        border_pressed_delta = 60 if is_dark_bg else -60
        border_checked_delta = 50 if is_dark_bg else -50
        border_checked_hover_delta = 70 if is_dark_bg else -70
        
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
        
        /* 工具栏按钮 */
        QToolButton {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 6px;
            margin: 1px;
            icon-size: 16px;
        }}
        
        QToolButton:hover {{
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_hover_delta)};
        }}
        
        QToolButton:pressed {{
            background-color: {self._adjust_color_brightness(bg_color, pressed_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_pressed_delta)};
        }}
        
        QToolButton:checked {{
            background-color: {self._adjust_color_brightness(bg_color, checked_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_checked_delta)};
        }}
        
        QToolButton:checked:hover {{
            background-color: {self._adjust_color_brightness(bg_color, checked_hover_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_checked_hover_delta)};
        }}
        
        QToolButton:disabled {{
            background-color: {self._adjust_color_brightness(bg_color, -10)};
            color: {self._adjust_color_brightness(text_color, 50)};
            border: 1px solid {self._adjust_color_brightness(border_color, 20)};
        }}
        
        /* 工具栏按钮菜单 */
        QToolButton::menu-button {{
            border: none;
            width: 12px;
            height: 12px;
            subcontrol-origin: padding;
            subcontrol-position: bottom right;
        }}
        
        QToolButton::menu-arrow {{
            image: none;
            border: none;
            width: 6px;
            height: 6px;
            subcontrol-origin: padding;
            subcontrol-position: bottom right;
            right: 2px;
            bottom: 2px;
        }}
        
        QToolButton::menu-arrow:open {{
            top: 1px;
            left: 1px;
        }}
        
        QToolButton[popupMode="1"] {{
            color: {text_color};
            padding-right: 12px;
        }}
        
        QToolButton[popupMode="1"]:hover {{
            color: {text_color};
        }}
        
        QToolButton[popupMode="1"]:checked {{
            background-color: {self._adjust_color_brightness(bg_color, checked_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_checked_delta)};
        }}
        
        /* 布局选择器按钮 - 与工具栏按钮样式保持一致 */
        QPushButton[objectName="LayoutSelectorButton"] {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 6px;
            margin: 1px;
            min-width: 32px;
            min-height: 32px;
            icon-size: 16px;
            text-align: center;
        }}
        
        QPushButton[objectName="LayoutSelectorButton"]:hover {{
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_hover_delta)};
        }}
        
        QPushButton[objectName="LayoutSelectorButton"]:pressed {{
            background-color: {self._adjust_color_brightness(bg_color, pressed_brightness_delta)};
            color: {text_color};
            border: 1px solid {self._adjust_color_brightness(border_color, border_pressed_delta)};
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
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
        }}
        
        QPushButton:pressed {{
            background-color: {self._adjust_color_brightness(bg_color, pressed_brightness_delta)};
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
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
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
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
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
        """调整颜色亮度
        
        Args:
            color_hex: 十六进制颜色值 (如 '#FF0000')
            amount: 亮度调整量 (-255 到 255)
            
        Returns:
            调整后的十六进制颜色值
        """
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
        
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def _get_color_brightness(self, color_hex: str) -> int:
        """计算颜色亮度
        
        Args:
            color_hex: 十六进制颜色值 (如 '#FF0000')
            
        Returns:
            颜色亮度值 (0-255)
        """
        # 移除 # 符号
        color_hex = color_hex.lstrip('#')
        
        # 转换为RGB
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
        
        # 使用感知亮度公式 (ITU-R BT.709)
        brightness = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return int(brightness)
    
    def get_available_themes(self) -> list:
        """获取可用主题列表"""
        return list(self.themes.keys())
    
    def get_theme_settings(self, category: str, theme_name: str = None) -> Dict[str, Any]:
        """获取主题设置
        
        Args:
            category: 主题类别 ('roi', 'measurement', 'ui')
            theme_name: 主题名称，如果为None则使用当前主题
            
        Returns:
            包含主题设置的字典
        """
        if category == 'ui':
            # 对于UI主题，使用内部的themes字典
            if theme_name is None:
                theme_name = self.current_theme
            return self.themes.get(theme_name, {})
        else:
            # 对于其他类别，使用全局函数
            return get_theme_settings(category, theme_name)
    
    def create_themed_icon(self, svg_path: str) -> QIcon:
        """根据当前主题创建合适颜色的图标
        
        Args:
            svg_path: SVG图标文件路径
            
        Returns:
            主题适配的QIcon对象
        """
        try:
            # 获取当前主题颜色
            theme_data = get_theme_settings('ui', self.get_current_theme())
            bg_color = theme_data.get('background_color', '#F0F0F0')
            
            # 计算背景色亮度
            bg_brightness = self._get_color_brightness(bg_color)
            
            # 根据背景色亮度选择图标颜色
            icon_color = "#FFFFFF" if bg_brightness < 128 else "#000000"
            
            # 读取SVG内容并替换颜色
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 替换currentColor为具体颜色
            svg_content = svg_content.replace('currentColor', icon_color)
            
            # 使用QSvgRenderer创建图标
            svg_bytes = QByteArray(svg_content.encode('utf-8'))
            renderer = QSvgRenderer(svg_bytes)
            
            # 创建QPixmap
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            
            return QIcon(pixmap)
            
        except Exception as e:
            logger.warning(f"[ThemeManager.create_themed_icon] 创建主题图标失败: {e}")
            # 回退到原始图标
            return QIcon(svg_path)