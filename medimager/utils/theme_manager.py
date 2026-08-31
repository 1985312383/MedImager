#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题管理器

负责应用程序界面主题的加载和应用
"""

import toml
import weakref
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QStandardPaths
from PySide6.QtGui import QColor, QIcon
from typing import Dict, Any, Optional
from medimager.utils.settings import SettingsManager, get_settings_manager
from medimager.utils.logger import get_logger
from medimager.utils.icon_registry import IconRegistry

logger = get_logger(__name__)


# Medical image pixels must not inherit a bright application theme. Keeping
# this invariant here makes custom/legacy UI themes safe by construction.
MEDICAL_CANVAS_COLOR = "#080A0C"


def _shift_color(color_text: str, delta: int) -> str:
    color = QColor(str(color_text))
    if not color.isValid():
        color = QColor("#808080")
    return QColor(
        max(0, min(255, color.red() + delta)),
        max(0, min(255, color.green() + delta)),
        max(0, min(255, color.blue() + delta)),
    ).name(QColor.NameFormat.HexRgb)


def normalize_ui_theme(theme_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a complete semantic UI palette while accepting legacy themes.

    Older themes only define background/text/highlight/border. All semantic
    values are derived from those keys, so user themes remain usable without
    migration. Explicit semantic values take precedence except for the image
    canvas, which intentionally remains neutral black in every theme.
    """
    raw = dict(theme_data or {})
    background = str(raw.get("background_color", "#F0F0F0"))
    text = str(raw.get("text_color", "#111418"))
    highlight = str(raw.get("highlight_color", "#0063B1"))
    border = str(raw.get("border_color", "#C8C8C8"))
    color = QColor(background)
    is_dark = color.isValid() and color.lightness() < 128
    direction = 1 if is_dark else -1

    defaults = {
        "background_color": background,
        "window_color": background,
        "canvas_color": MEDICAL_CANVAS_COLOR,
        "surface_color": _shift_color(background, 6 * direction),
        "surface_raised_color": _shift_color(background, 14 * direction),
        "surface_sunken_color": _shift_color(background, -6 * direction),
        "text_color": text,
        "text_secondary_color": _shift_color(text, -58 if is_dark else 70),
        "text_disabled_color": _shift_color(text, -112 if is_dark else 128),
        "icon_color": str(raw.get("icon_color", text)),
        "icon_active_color": str(raw.get("icon_active_color", highlight)),
        "icon_selected_color": str(raw.get("icon_selected_color", "#FFFFFF")),
        "border_color": border,
        "border_subtle_color": _shift_color(border, 12 * direction),
        "highlight_color": highlight,
        "highlight_hover_color": _shift_color(highlight, 18),
        "highlight_pressed_color": _shift_color(highlight, -18),
        "focus_color": str(raw.get("focus_color", "#42A5F5")),
        "success_color": str(raw.get("success_color", "#2EAD67")),
        "warning_color": str(raw.get("warning_color", "#E5A50A")),
        "error_color": str(raw.get("error_color", "#D64545")),
        "overlay_background_color": str(raw.get("overlay_background_color", "#000000B8")),
        "annotation_color": str(raw.get("annotation_color", "#FFD740")),
        "measurement_color": str(raw.get("measurement_color", "#38D9FF")),
        "reference_line_color": str(raw.get("reference_line_color", "#E757FF")),
        "image_text_color": str(raw.get("image_text_color", "#F5F7FA")),
    }
    normalized = {
        **raw,
        **{key: raw.get(key, value) for key, value in defaults.items()},
    }
    normalized["canvas_color"] = MEDICAL_CANVAS_COLOR
    normalized["highlight_text_color"] = str(
        raw.get("highlight_text_color", ThemeManager._contrasting_text_color(highlight))
    )
    return normalized


def get_user_themes_dir(settings_manager: Optional[SettingsManager] = None) -> Path:
    """Return a writable per-user theme directory.

    JSON-backed test/portable settings already expose a concrete config
    directory. Native QSettings may be registry-backed on Windows, so the
    cross-platform AppConfigLocation is the reliable filesystem fallback.
    """
    if settings_manager is not None and getattr(settings_manager, "use_json", False):
        return settings_manager.get_config_directory() / "themes"
    config_location = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not config_location:
        config_location = str(Path.home() / ".config" / "MedImager")
    return Path(config_location) / "themes"


class ThemeAwareMixin:
    """Mixin 为 QWidget 子类提供统一的主题管理器注册/注销逻辑。

    子类需要实现 ``update_theme(self, theme_name: str)`` 方法。
    在 ``__init__`` 末尾调用 ``self._register_to_theme_manager()`` 即可完成注册。
    """

    _theme_manager: "Optional[ThemeManager]" = None

    # ------------------------------------------------------------------
    def _register_to_theme_manager(self) -> None:
        """尝试从父窗口或 QApplication 获取 ThemeManager 并注册自身。"""
        if self._theme_manager is not None:
            return  # 已注册

        try:
            tm = self._find_theme_manager()
            if tm is not None:
                self._theme_manager = tm
                tm.register_component(self)
                logger.debug(f"[{self.__class__.__name__}] 成功注册到主题管理器")
        except Exception as e:
            logger.debug(f"[{self.__class__.__name__}] 注册主题管理器失败: {e}")

    def _find_theme_manager(self) -> "Optional[ThemeManager]":
        """查找 ThemeManager 实例。"""
        # 1. 从 window() 获取
        main_window = self.window()  # type: ignore[attr-defined]
        if main_window is not None and hasattr(main_window, 'theme_manager'):
            tm = main_window.theme_manager
            if tm is not None:
                return tm

        # 2. 从 QApplication 获取
        app = QApplication.instance()
        if app is not None and hasattr(app, 'main_window'):
            mw = app.main_window
            if mw is not None and hasattr(mw, 'theme_manager'):
                return mw.theme_manager

        return None

    def _unregister_from_theme_manager(self) -> None:
        """从 ThemeManager 注销自身。"""
        if self._theme_manager is not None:
            self._theme_manager.unregister_component(self)
            self._theme_manager = None

    # 便捷的 Qt 事件钩子 —— 子类可直接调用 super()
    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)  # type: ignore[misc]
        if self._theme_manager is None:
            self._register_to_theme_manager()

    def closeEvent(self, event):  # type: ignore[override]
        self._unregister_from_theme_manager()
        super().closeEvent(event)  # type: ignore[misc]

    # ------------------------------------------------------------------
    # 颜色工具方法（之前在多个类中重复）
    # ------------------------------------------------------------------
    @staticmethod
    def adjust_color_brightness(color_hex: str, amount: int) -> str:
        """调整十六进制颜色的亮度。"""
        try:
            color_hex = color_hex.lstrip('#')
            r = max(0, min(255, int(color_hex[0:2], 16) + amount))
            g = max(0, min(255, int(color_hex[2:4], 16) + amount))
            b = max(0, min(255, int(color_hex[4:6], 16) + amount))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color_hex

    @staticmethod
    def get_color_brightness(color_hex: str) -> int:
        """计算颜色感知亮度 (ITU-R BT.709)。"""
        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
        return int(0.2126 * r + 0.7152 * g + 0.0722 * b)


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
            settings_manager = get_settings_manager()
            theme_name = settings_manager.get_setting(f'{category}_theme', 'default')
        
        bundled_dir = Path(__file__).parent.parent / "themes" / category
        user_dir = get_user_themes_dir(settings_manager) / category

        # A user theme intentionally shadows the bundled read-only preset.
        for theme_file in (
            user_dir / f"{theme_name}.toml",
            bundled_dir / f"{theme_name}.toml",
            bundled_dir / "default.toml",
        ):
            if theme_file.exists():
                return toml.load(theme_file)
            
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
        self.icon_registry = IconRegistry(self)
        
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
        themes = {}
        bundled_dir = Path(__file__).parent.parent / "themes" / "ui"
        user_dir = get_user_themes_dir(self.settings_manager) / "ui"

        for themes_dir in (bundled_dir, user_dir):
            if not themes_dir.exists():
                continue
            for theme_file in themes_dir.glob("*.toml"):
                try:
                    theme_data = normalize_ui_theme(toml.load(theme_file))
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
        logger.info("[ThemeManager.set_theme] 应用全局主题样式")
        self.apply_current_theme()
        
        # 为所有注册的组件应用新主题
        logger.info("[ThemeManager.set_theme] 开始为注册组件应用主题")
        self._apply_theme_to_all_components(theme_name)
        
        logger.info("[ThemeManager.set_theme] 发送主题变更信号")
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
        tokens = normalize_ui_theme(theme_data)
        logger.debug(f"[ThemeManager._generate_stylesheet] 生成样式表: {tokens.get('name', 'unknown')}")
        bg_color = tokens['window_color']
        surface_color = tokens['surface_color']
        surface_raised_color = tokens['surface_raised_color']
        surface_sunken_color = tokens['surface_sunken_color']
        canvas_color = tokens['canvas_color']
        text_color = tokens['text_color']
        text_disabled_color = tokens['text_disabled_color']
        border_color = tokens['border_color']
        border_subtle_color = tokens['border_subtle_color']
        highlight_color = tokens['highlight_color']
        highlight_hover_color = tokens['highlight_hover_color']
        highlight_pressed_color = tokens['highlight_pressed_color']
        highlight_text_color = tokens['highlight_text_color']
        focus_color = tokens['focus_color']
        success_color = tokens['success_color']
        warning_color = tokens['warning_color']
        is_dark_bg = self._get_color_brightness(bg_color) < 128
        hover_brightness_delta = 18 if is_dark_bg else -18  # legacy selector fallback

        # 下拉箭头图标路径（根据主题亮度选择）
        from medimager.utils.resource_path import get_icon_path
        arrow_svg = "dropdown_arrow_light.svg" if is_dark_bg else "dropdown_arrow_dark.svg"
        arrow_icon_path = get_icon_path(arrow_svg).replace("\\", "/")

        stylesheet = f"""
        /* 全局样式 */
        QMainWindow {{
            background-color: {bg_color};
            color: {text_color};
        }}
        
        QWidget {{
            background-color: {surface_color};
            color: {text_color};
        }}

        QGraphicsView {{
            background-color: {canvas_color};
        }}
        
        /* 菜单栏 */
        QMenuBar {{
            background-color: {surface_color};
            color: {text_color};
            border-bottom: 1px solid {border_color};
        }}
        
        QMenuBar::item {{
            background-color: transparent;
            padding: 4px 8px;
        }}
        
        QMenuBar::item:selected {{
            background-color: {highlight_color};
            color: {highlight_text_color};
        }}
        
        QMenu {{
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {border_color};
        }}
        
        QMenu::item {{
            padding: 6px 20px;
        }}
        
        QMenu::item:selected {{
            background-color: {highlight_color};
            color: {highlight_text_color};
        }}
        
        /* 工具栏 */
        QToolBar {{
            background-color: {surface_color};
            border: 1px solid {border_color};
            spacing: 4px;
        }}

        /* 工具栏按钮 */
        QToolButton {{
            background-color: {surface_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 4px;
            margin: 1px;
        }}
        
        QToolButton:hover {{
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {highlight_hover_color};
        }}
        
        QToolButton:pressed {{
            background-color: {highlight_pressed_color};
            color: {text_color};
            border: 1px solid {highlight_pressed_color};
        }}
        
        QToolButton:checked {{
            background-color: {highlight_color};
            color: {highlight_text_color};
            border: 1px solid {highlight_color};
        }}
        
        QToolButton:checked:hover {{
            background-color: {highlight_color};
            color: {highlight_text_color};
            border: 1px solid {highlight_text_color};
        }}
        
        QToolButton:disabled {{
            background-color: {surface_sunken_color};
            color: {text_disabled_color};
            border: 1px solid {border_subtle_color};
        }}

        QToolButton:focus, QPushButton:focus {{
            border: 2px solid {focus_color};
        }}

        QToolButton[syncState="partial"] {{
            border: 1px solid {warning_color};
        }}

        QToolButton[syncState="all"] {{
            border: 1px solid {success_color};
        }}

        /* Main-toolbar hierarchy: modes are solid; persistent aids are outlined. */
        QToolBar#MainToolBar QToolButton[toolbarRole="toggle"]:checked {{
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {highlight_color};
            border-bottom: 3px solid {highlight_color};
        }}

        QToolBar#MainToolBar QToolButton[toolbarRole="sync"][syncState="off"] {{
            background-color: {surface_color};
            color: {text_color};
            border: 1px solid {border_color};
        }}

        QToolBar#MainToolBar QToolButton[toolbarRole="sync"][syncState="partial"] {{
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {warning_color};
            border-bottom: 3px solid {warning_color};
        }}

        QToolBar#MainToolBar QToolButton[toolbarRole="sync"][syncState="all"] {{
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {success_color};
            border-bottom: 3px solid {success_color};
        }}
        
        /* 工具栏下拉按钮 - 右侧箭头条 */
        QToolButton::menu-button {{
            border-left: 1px solid {border_color};
            border-top: none;
            border-right: none;
            border-bottom: none;
            width: 14px;
            subcontrol-origin: border;
            subcontrol-position: center right;
            border-top-right-radius: 4px;
            border-bottom-right-radius: 4px;
        }}

        QToolButton::menu-button:hover {{
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
        }}

        QToolButton::menu-arrow {{
            image: url({arrow_icon_path});
            width: 8px;
            height: 8px;
            subcontrol-origin: content;
            subcontrol-position: center center;
        }}

        /* InstantPopup 按钮右下角小三角指示 */
        QToolButton::menu-indicator {{
            image: url({arrow_icon_path});
            width: 6px;
            height: 6px;
            subcontrol-origin: padding;
            subcontrol-position: bottom right;
            right: 1px;
            bottom: 1px;
        }}
        
        /* 布局选择器按钮 - 与工具栏按钮样式保持一致 */
        QPushButton[objectName="LayoutSelectorButton"] {{
            background-color: {surface_color};
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
            background-color: {surface_raised_color};
            color: {text_color};
            border: 1px solid {highlight_hover_color};
        }}
        
        QPushButton[objectName="LayoutSelectorButton"]:pressed {{
            background-color: {highlight_pressed_color};
            color: {text_color};
            border: 1px solid {highlight_pressed_color};
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
            background-color: {surface_color};
            border: 1px solid {border_color};
            padding: 6px 12px;
            border-radius: 4px;
        }}
        
        QPushButton:hover {{
            background-color: {surface_raised_color};
        }}
        
        QPushButton:pressed {{
            background-color: {highlight_pressed_color};
        }}
        
        QPushButton:disabled {{
            color: {text_disabled_color};
            border-color: {border_subtle_color};
        }}
        
        /* 输入框 */
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {surface_sunken_color};
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
            background-color: {surface_raised_color};
            border: 1px solid {border_color};
            selection-background-color: {highlight_color};
            selection-color: {highlight_text_color};
        }}
        
        /* 列表 */
        QListWidget {{
            background-color: {surface_sunken_color};
            border: 1px solid {border_color};
            alternate-background-color: {surface_color};
        }}
        
        QListWidget::item {{
            padding: 4px;
            border-bottom: 1px solid {border_color};
        }}
        
        QListWidget::item:selected {{
            background-color: {highlight_color};
            color: {highlight_text_color};
        }}
        
        QListWidget::item:hover {{
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
        }}
        
        /* 标签页 */
        QTabWidget::pane {{
            border: 1px solid {border_color};
        }}
        
        QTabBar::tab {{
            background-color: {surface_color};
            border: 1px solid {border_color};
            padding: 6px 12px;
            margin-right: 2px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {highlight_color};
            color: {highlight_text_color};
        }}
        
        QTabBar::tab:hover {{
            background-color: {self._adjust_color_brightness(bg_color, hover_brightness_delta)};
        }}
        
        /* 滚动条 */
        QScrollBar:vertical {{
            background-color: {surface_sunken_color};
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
            background-color: {surface_sunken_color};
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
            background-color: {surface_color};
        }}
        
        /* 设置对话框特殊样式 */
        QListWidget#settings_nav {{
            background-color: {surface_sunken_color};
            border: 1px solid {border_color};
            border-radius: 4px;
        }}
        
        QListWidget#settings_nav::item {{
            padding: 10px;
            border-bottom: 1px solid {border_color};
        }}
        
        QListWidget#settings_nav::item:selected {{
            background-color: {highlight_color};
            color: {highlight_text_color};
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

    @staticmethod
    def _contrasting_text_color(background: str) -> str:
        """Choose black or white with the higher WCAG contrast ratio."""
        color = QColor(background)
        if not color.isValid():
            return "#000000"

        def luminance(channel: int) -> float:
            value = channel / 255.0
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        relative = (
            0.2126 * luminance(color.red())
            + 0.7152 * luminance(color.green())
            + 0.0722 * luminance(color.blue())
        )
        white_contrast = 1.05 / (relative + 0.05)
        black_contrast = (relative + 0.05) / 0.05
        return "#FFFFFF" if white_contrast >= black_contrast else "#000000"
    
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
            return normalize_ui_theme(self.themes.get(theme_name, {}))
        else:
            # 对于其他类别，使用全局函数
            return get_theme_settings(category, theme_name)
    
    def create_themed_icon(
        self,
        svg_path: str,
        *,
        preserve_on_color: bool = False,
    ) -> QIcon:
        """Create a semantic, high-DPI vector icon from an SVG path."""
        return self.icon_registry.icon_from_path(
            svg_path,
            preserve_on_color=preserve_on_color,
        )

    def create_icon(
        self,
        semantic_name: str,
        *,
        preserve_on_color: bool = False,
    ) -> QIcon:
        """Create an icon by a stable semantic registry name."""
        return self.icon_registry.icon(
            semantic_name,
            preserve_on_color=preserve_on_color,
        )

    def get_theme_tokens(self, theme_name: Optional[str] = None) -> Dict[str, Any]:
        """Return the complete semantic token set for the selected UI theme."""
        selected = theme_name or self.current_theme
        return normalize_ui_theme(self.themes.get(selected, {}))
