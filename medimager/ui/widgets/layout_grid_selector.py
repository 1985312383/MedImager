"""
布局网格选择器组件

提供简约的布局选择功能，包含预设布局和动态调整。
"""

from typing import Tuple, Optional, List, Dict
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QApplication, QGridLayout, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QSize, QTimer, QByteArray
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QMouseEvent, QPaintEvent, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer

from medimager.utils.logger import get_logger
from medimager.utils.theme_manager import ThemeManager

logger = get_logger(__name__)


class LayoutPresetButton(QPushButton):
    """布局预设按钮 - 使用图标显示布局"""
    
    layout_selected = Signal(tuple)  # 发送布局配置元组
    
    def __init__(self, layout_config: tuple, layout_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.layout_config = layout_config  # 布局配置，可以是(rows, cols)或复杂布局配置
        self.layout_name = layout_name
        self.setFixedSize(60, 45)
        self.clicked.connect(self._on_clicked)
        
        # 设置工具提示
        self.setToolTip(self.tr(layout_name))
        
        # 获取主题管理器并注册
        self.theme_manager = None
        self._register_to_theme_manager()
        
        self._load_theme_colors()
        self._setup_style()
        
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            logger.info(f"[LayoutPresetButton._register_to_theme_manager] 获取父窗口: {main_window.__class__.__name__ if main_window else 'None'}")
            logger.info(f"[LayoutPresetButton._register_to_theme_manager] 父窗口是否有theme_manager: {hasattr(main_window, 'theme_manager') if main_window else False}")
            
            if hasattr(main_window, 'theme_manager') and main_window.theme_manager is not None:
                self.theme_manager = main_window.theme_manager
                logger.info(f"[LayoutPresetButton._register_to_theme_manager] 找到主题管理器: {self.theme_manager.__class__.__name__}")
                self.theme_manager.register_component(self)
                logger.info("[LayoutPresetButton._register_to_theme_manager] 成功注册到主题管理器")
                # 立即应用当前主题
                current_theme = self.theme_manager.get_current_theme()
                logger.info(f"[LayoutPresetButton._register_to_theme_manager] 当前主题: {current_theme}")
                self.update_theme(current_theme)
                logger.info(f"[LayoutPresetButton._register_to_theme_manager] 已应用当前主题: {current_theme}")
            else:
                # 尝试通过QApplication获取主题管理器
                logger.info("[LayoutPresetButton._register_to_theme_manager] 尝试通过QApplication获取主题管理器")
                app = QApplication.instance()
                logger.info(f"[LayoutPresetButton._register_to_theme_manager] QApplication实例: {app.__class__.__name__ if app else 'None'}")
                if app and hasattr(app, 'main_window'):
                    logger.info(f"[LayoutPresetButton._register_to_theme_manager] app.main_window: {app.main_window.__class__.__name__ if hasattr(app, 'main_window') else 'None'}")
                    if hasattr(app.main_window, 'theme_manager'):
                        self.theme_manager = app.main_window.theme_manager
                        self.theme_manager.register_component(self)
                        logger.info("[LayoutPresetButton._register_to_theme_manager] 通过QApplication成功注册到主题管理器")
                        current_theme = self.theme_manager.get_current_theme()
                        self.update_theme(current_theme)
                        logger.info(f"[LayoutPresetButton._register_to_theme_manager] 已应用当前主题: {current_theme}")
                    else:
                        logger.warning("[LayoutPresetButton._register_to_theme_manager] app.main_window没有theme_manager属性")
                else:
                    logger.warning("[LayoutPresetButton._register_to_theme_manager] 无法通过QApplication获取主题管理器")
                    logger.warning("[LayoutPresetButton._register_to_theme_manager] 未找到主题管理器，使用默认颜色")
        except Exception as e:
            logger.error(f"[LayoutPresetButton._register_to_theme_manager] 注册到主题管理器失败: {e}", exc_info=True)
    
    def showEvent(self, event):
        """显示事件 - 确保主题管理器注册"""
        logger.info(f"[LayoutPresetButton.showEvent] 显示事件触发")
        super().showEvent(event)
        if not self.theme_manager:
            logger.info("[LayoutPresetButton.showEvent] 主题管理器未设置，重新尝试注册")
            self._register_to_theme_manager()
        else:
            logger.info("[LayoutPresetButton.showEvent] 主题管理器已设置")
    
    def closeEvent(self, event):
        """关闭事件 - 取消注册"""
        logger.debug(f"[LayoutPresetButton.closeEvent] 关闭事件触发")
        if self.theme_manager:
            logger.debug("[LayoutPresetButton.closeEvent] 取消注册主题管理器")
            self.theme_manager.unregister_component(self)
        super().closeEvent(event)
        
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[LayoutPresetButton.update_theme] 收到主题更新请求: {theme_name}")
        try:
            logger.info("[LayoutPresetButton.update_theme] 开始加载主题颜色")
            self._load_theme_colors()
            logger.info("[LayoutPresetButton.update_theme] 主题颜色加载完成")
            logger.info("[LayoutPresetButton.update_theme] 开始设置样式")
            self._setup_style()
            logger.info("[LayoutPresetButton.update_theme] 样式设置完成")
            self.update()  # 重绘按钮
            logger.info("[LayoutPresetButton.update_theme] 重绘完成")
        except Exception as e:
            logger.error(f"[LayoutPresetButton.update_theme] 主题更新失败: {e}", exc_info=True)
    

        
    def _load_theme_colors(self) -> None:
        """加载主题颜色"""
        try:
            if self.theme_manager:
                theme_data = self.theme_manager.get_theme_settings('ui')
                self.bg_color = theme_data.get('background_color', '#FFFFFF')
                self.text_color = theme_data.get('text_color', '#333333')
                self.border_color = theme_data.get('border_color', '#CCCCCC')
                self.highlight_color = theme_data.get('highlight_color', '#3498DB')
            else:
                # 默认颜色
                self.bg_color = '#FFFFFF'
                self.text_color = '#333333'
                self.border_color = '#CCCCCC'
                self.highlight_color = '#3498DB'
        except Exception as e:
            logger.warning(f"[LayoutPresetButton._load_theme_colors] 加载主题颜色失败: {e}")
            self.bg_color = '#FFFFFF'
            self.text_color = '#333333'
            self.border_color = '#CCCCCC'
            self.highlight_color = '#3498DB'
    
    def _setup_style(self) -> None:
        """设置按钮样式 - 使用蓝色选中效果，不用边框色"""
        self.setStyleSheet(f"""
            LayoutPresetButton {{
                border: 1px solid {self.border_color};
                border-radius: 4px;
                background-color: {self.bg_color};
                margin: 2px;
            }}
            LayoutPresetButton:hover {{
                background-color: {self.highlight_color};
                border-color: {self.highlight_color};
            }}
            LayoutPresetButton:pressed {{
                background-color: {self._adjust_color_brightness(self.highlight_color, -20)};
            }}
        """)
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            color_hex = color_hex.lstrip('#')
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            
            r = max(0, min(255, r + amount))
            g = max(0, min(255, g + amount))
            b = max(0, min(255, b + amount))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color_hex
    
    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制布局图标"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 计算绘制区域
        margin = 8
        draw_width = self.width() - 2 * margin
        draw_height = self.height() - 2 * margin
        
        # 根据按钮状态设置绘制颜色 - 与其他工具按钮保持一致
        if self.isDown():
            # 按下状态：使用高亮色
            painter.setPen(QPen(QColor(self.highlight_color), 1.5))
            painter.setBrush(QBrush(QColor(self.highlight_color)))
        elif self.underMouse():
            # 悬停状态：使用稍亮的文字颜色
            hover_color = self._adjust_color_brightness(self.text_color, 30)
            painter.setPen(QPen(QColor(hover_color), 1.5))
            painter.setBrush(QBrush(QColor(hover_color)))
        else:
            # 默认状态：使用普通文字颜色
            painter.setPen(QPen(QColor(self.text_color), 1.5))
            painter.setBrush(QBrush(QColor(self.text_color)))
        
        # 根据布局配置绘制不同的图标
        self._draw_layout_icon(painter, margin, draw_width, draw_height)
        
        painter.end()
    
    def _draw_layout_icon(self, painter: QPainter, margin: int, width: int, height: int) -> None:
        """根据布局配置绘制图标"""
        if isinstance(self.layout_config, tuple) and len(self.layout_config) == 2:
            # 规则网格布局
            rows, cols = self.layout_config
            self._draw_grid_layout(painter, margin, width, height, rows, cols)
        elif isinstance(self.layout_config, dict):
            # 特殊布局
            self._draw_special_layout(painter, margin, width, height, self.layout_config)
    
    def _draw_grid_layout(self, painter: QPainter, margin: int, width: int, height: int, rows: int, cols: int) -> None:
        """绘制规则网格布局"""
        cell_width = width / cols
        cell_height = height / rows
        
        for row in range(rows):
            for col in range(cols):
                x = margin + col * cell_width
                y = margin + row * cell_height
                rect = QRect(int(x + 1), int(y + 1), int(cell_width - 2), int(cell_height - 2))
                painter.drawRect(rect)
    
    def _draw_special_layout(self, painter: QPainter, margin: int, width: int, height: int, config: dict) -> None:
        """绘制特殊布局"""
        layout_type = config.get('type', '')
        
        if layout_type == 'vertical_split':
            # 上下分割布局
            top_height = height * config.get('top_ratio', 0.5)
            bottom_height = height - top_height
            
            # 上半部分
            top_rect = QRect(margin + 1, margin + 1, int(width - 2), int(top_height - 2))
            painter.drawRect(top_rect)
            
            # 下半部分
            if config.get('bottom_split', False):
                # 下半部分左右分割
                bottom_left_width = width * 0.5
                bottom_right_width = width - bottom_left_width
                
                bottom_left_rect = QRect(margin + 1, int(margin + top_height + 1), 
                                       int(bottom_left_width - 2), int(bottom_height - 2))
                painter.drawRect(bottom_left_rect)
                
                bottom_right_rect = QRect(int(margin + bottom_left_width + 1), int(margin + top_height + 1), 
                                        int(bottom_right_width - 2), int(bottom_height - 2))
                painter.drawRect(bottom_right_rect)
            else:
                # 下半部分整体
                bottom_rect = QRect(margin + 1, int(margin + top_height + 1), 
                                  int(width - 2), int(bottom_height - 2))
                painter.drawRect(bottom_rect)
        
        elif layout_type == 'horizontal_split':
            # 左右分割布局
            left_width = width * config.get('left_ratio', 0.5)
            right_width = width - left_width
            
            # 左半部分
            left_rect = QRect(margin + 1, margin + 1, int(left_width - 2), int(height - 2))
            painter.drawRect(left_rect)
            
            # 右半部分
            if config.get('right_split', False):
                # 右半部分上下分割
                right_top_height = height * 0.5
                right_bottom_height = height - right_top_height
                
                right_top_rect = QRect(int(margin + left_width + 1), margin + 1, 
                                     int(right_width - 2), int(right_top_height - 2))
                painter.drawRect(right_top_rect)
                
                right_bottom_rect = QRect(int(margin + left_width + 1), int(margin + right_top_height + 1), 
                                        int(right_width - 2), int(right_bottom_height - 2))
                painter.drawRect(right_bottom_rect)
            else:
                # 右半部分整体
                right_rect = QRect(int(margin + left_width + 1), margin + 1, 
                                 int(right_width - 2), int(height - 2))
                painter.drawRect(right_rect)
        
        elif layout_type == 'triple_column_right_split':
            # 左右三等分+右边上下等分
            left_ratio = config.get('left_ratio', 0.33)
            middle_ratio = config.get('middle_ratio', 0.34)
            right_ratio = 1.0 - left_ratio - middle_ratio
            
            left_width = width * left_ratio
            middle_width = width * middle_ratio
            right_width = width * right_ratio
            
            # 左列
            left_rect = QRect(margin + 1, margin + 1, int(left_width - 2), int(height - 2))
            painter.drawRect(left_rect)
            
            # 中列
            middle_rect = QRect(int(margin + left_width + 1), margin + 1, 
                              int(middle_width - 2), int(height - 2))
            painter.drawRect(middle_rect)
            
            # 右列分为上下两部分
            right_top_height = height * 0.5
            right_bottom_height = height - right_top_height
            
            right_top_rect = QRect(int(margin + left_width + middle_width + 1), margin + 1, 
                                 int(right_width - 2), int(right_top_height - 2))
            painter.drawRect(right_top_rect)
            
            right_bottom_rect = QRect(int(margin + left_width + middle_width + 1), int(margin + right_top_height + 1), 
                                    int(right_width - 2), int(right_bottom_height - 2))
            painter.drawRect(right_bottom_rect)
        
        elif layout_type == 'triple_column_middle_right_split':
            # 左右三等分+中间和右边上下等分
            left_ratio = config.get('left_ratio', 0.33)
            middle_ratio = config.get('middle_ratio', 0.34)
            right_ratio = 1.0 - left_ratio - middle_ratio
            
            left_width = width * left_ratio
            middle_width = width * middle_ratio
            right_width = width * right_ratio
            
            # 左列
            left_rect = QRect(margin + 1, margin + 1, int(left_width - 2), int(height - 2))
            painter.drawRect(left_rect)
            
            # 中列分为上下两部分
            middle_top_height = height * 0.5
            middle_bottom_height = height - middle_top_height
            
            middle_top_rect = QRect(int(margin + left_width + 1), margin + 1, 
                                  int(middle_width - 2), int(middle_top_height - 2))
            painter.drawRect(middle_top_rect)
            
            middle_bottom_rect = QRect(int(margin + left_width + 1), int(margin + middle_top_height + 1), 
                                     int(middle_width - 2), int(middle_bottom_height - 2))
            painter.drawRect(middle_bottom_rect)
            
            # 右列分为上下两部分
            right_top_height = height * 0.5
            right_bottom_height = height - right_top_height
            
            right_top_rect = QRect(int(margin + left_width + middle_width + 1), margin + 1, 
                                 int(right_width - 2), int(right_top_height - 2))
            painter.drawRect(right_top_rect)
            
            right_bottom_rect = QRect(int(margin + left_width + middle_width + 1), int(margin + right_top_height + 1), 
                                    int(right_width - 2), int(right_bottom_height - 2))
            painter.drawRect(right_bottom_rect)

    
    def _on_clicked(self) -> None:
        """处理点击事件"""
        logger.debug(f"[LayoutPresetButton._on_clicked] 选择布局: {self.layout_name}")
        self.layout_selected.emit(self.layout_config)


class DynamicLayoutSelector(QFrame):
    """动态布局选择器 - 最大支持3×4"""
    
    layout_selected = Signal(int, int)
    
    def __init__(self, max_rows: int = 3, max_cols: int = 4, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.max_rows = max_rows
        self.max_cols = max_cols
        self.cell_size = 25
        self.cell_spacing = 3
        self.hovered_rows = 0
        self.hovered_cols = 0
        
        # 获取主题管理器并注册
        self.theme_manager = None
        self._register_to_theme_manager()
        
        self._load_theme_colors()
        self._setup_ui()
        
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] 获取父窗口: {main_window.__class__.__name__ if main_window else 'None'}")
            logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] 父窗口是否有theme_manager: {hasattr(main_window, 'theme_manager') if main_window else False}")
            
            if hasattr(main_window, 'theme_manager') and main_window.theme_manager is not None:
                self.theme_manager = main_window.theme_manager
                self.theme_manager.register_component(self)
                logger.info("[DynamicLayoutSelector._register_to_theme_manager] 成功注册到主题管理器")
                # 立即应用当前主题
                current_theme = self.theme_manager.get_current_theme()
                self.update_theme(current_theme)
                logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] 已应用当前主题: {current_theme}")
            else:
                # 尝试通过QApplication获取主题管理器
                logger.info("[DynamicLayoutSelector._register_to_theme_manager] 尝试通过QApplication获取主题管理器")
                app = QApplication.instance()
                logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] QApplication实例: {app.__class__.__name__ if app else 'None'}")
                if app and hasattr(app, 'main_window'):
                    logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] app.main_window: {app.main_window.__class__.__name__ if hasattr(app, 'main_window') else 'None'}")
                    if hasattr(app.main_window, 'theme_manager'):
                        self.theme_manager = app.main_window.theme_manager
                        self.theme_manager.register_component(self)
                        logger.info("[DynamicLayoutSelector._register_to_theme_manager] 通过QApplication成功注册到主题管理器")
                        current_theme = self.theme_manager.get_current_theme()
                        self.update_theme(current_theme)
                        logger.info(f"[DynamicLayoutSelector._register_to_theme_manager] 已应用当前主题: {current_theme}")
                    else:
                        logger.warning("[DynamicLayoutSelector._register_to_theme_manager] app.main_window没有theme_manager属性")
                else:
                    logger.warning("[DynamicLayoutSelector._register_to_theme_manager] 无法通过QApplication获取主题管理器")
                    logger.warning("[DynamicLayoutSelector._register_to_theme_manager] 未找到主题管理器，使用默认颜色")
        except Exception as e:
            logger.error(f"[DynamicLayoutSelector._register_to_theme_manager] 注册到主题管理器失败: {e}", exc_info=True)
    
    def showEvent(self, event):
        """显示事件 - 确保主题管理器注册"""
        logger.info("[DynamicLayoutSelector.showEvent] 显示事件触发")
        super().showEvent(event)
        if not self.theme_manager:
            logger.info("[DynamicLayoutSelector.showEvent] 主题管理器未设置，重新尝试注册")
            self._register_to_theme_manager()
        else:
            logger.info("[DynamicLayoutSelector.showEvent] 主题管理器已设置")
    
    def closeEvent(self, event):
        """关闭事件 - 取消注册"""
        if self.theme_manager:
            self.theme_manager.unregister_component(self)
        super().closeEvent(event)
        
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[DynamicLayoutSelector.update_theme] 开始更新主题: {theme_name}")
        self._load_theme_colors()
        self._update_styles()
        if hasattr(self, 'grid_widget'):
            self.grid_widget.update()  # 重绘网格
        logger.info(f"[DynamicLayoutSelector.update_theme] 主题更新完成: {theme_name}")
        
    def _load_theme_colors(self) -> None:
        """加载主题颜色"""
        try:
            if self.theme_manager:
                theme_data = self.theme_manager.get_theme_settings('ui')
                self.bg_color = theme_data.get('background_color', '#FFFFFF')
                self.text_color = theme_data.get('text_color', '#333333')
                self.border_color = theme_data.get('border_color', '#CCCCCC')
                self.highlight_color = theme_data.get('highlight_color', '#3498DB')
                self.cell_bg_color = self._adjust_color_brightness(self.bg_color, -5)
            else:
                # 默认颜色
                self.bg_color = '#FFFFFF'
                self.text_color = '#333333'
                self.border_color = '#CCCCCC'
                self.highlight_color = '#3498DB'
                self.cell_bg_color = '#F8F9FA'
        except Exception as e:
            logger.warning(f"[DynamicLayoutSelector._load_theme_colors] 加载主题颜色失败: {e}")
            self.bg_color = '#FFFFFF'
            self.text_color = '#333333'
            self.border_color = '#CCCCCC'
            self.highlight_color = '#3498DB'
            self.cell_bg_color = '#F8F9FA'
    
    def _update_styles(self) -> None:
        """更新样式"""
        # 更新标题样式
        if hasattr(self, 'title_label'):
            self.title_label.setStyleSheet(f"color: {self.text_color};")
        
        # 更新选择标签样式
        if hasattr(self, 'selection_label'):
            self.selection_label.setStyleSheet(f"color: {self.text_color};")
        
        # 更新框架样式
        self.setStyleSheet(f"""
            DynamicLayoutSelector {{
                background-color: {self.bg_color};
                border: 1px solid {self.border_color};
                border-radius: 4px;
            }}
        """)
    
    def _setup_ui(self) -> None:
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 标题 - 左对齐
        self.title_label = QLabel(self.tr("自定义网格"))
        self.title_label.setAlignment(Qt.AlignLeft)  # 改为左对齐
        self.title_label.setFont(QFont("", 9, QFont.Bold))
        self.title_label.setStyleSheet(f"color: {self.text_color};")
        layout.addWidget(self.title_label)
        
        # 网格区域
        self.grid_widget = QWidget()
        grid_width = self.max_cols * (self.cell_size + self.cell_spacing) - self.cell_spacing
        grid_height = self.max_rows * (self.cell_size + self.cell_spacing) - self.cell_spacing
        self.grid_widget.setFixedSize(grid_width, grid_height)
        self.grid_widget.setMouseTracking(True)
        layout.addWidget(self.grid_widget, 0, Qt.AlignCenter)
        
        # 当前选择标签
        self.selection_label = QLabel(self.tr("1 × 1 网格"))
        self.selection_label.setAlignment(Qt.AlignCenter)
        self.selection_label.setFont(QFont("", 8))
        self.selection_label.setStyleSheet(f"color: {self.text_color};")
        layout.addWidget(self.selection_label)
        
        # 设置鼠标事件
        self.grid_widget.mouseMoveEvent = self._on_mouse_move
        self.grid_widget.mousePressEvent = self._on_mouse_press
        self.grid_widget.leaveEvent = self._on_mouse_leave
        self.grid_widget.paintEvent = self._paint_grid
        
        self.setStyleSheet(f"""
            DynamicLayoutSelector {{
                background-color: {self.bg_color};
                border: 1px solid {self.border_color};
                border-radius: 4px;
            }}
        """)
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            color_hex = color_hex.lstrip('#')
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            
            r = max(0, min(255, r + amount))
            g = max(0, min(255, g + amount))
            b = max(0, min(255, b + amount))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color_hex
    
    def _paint_grid(self, event: QPaintEvent) -> None:
        """绘制网格"""
        painter = QPainter(self.grid_widget)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for row in range(self.max_rows):
            for col in range(self.max_cols):
                x = col * (self.cell_size + self.cell_spacing)
                y = row * (self.cell_size + self.cell_spacing)
                rect = QRect(x, y, self.cell_size, self.cell_size)
                
                is_hovered = (row < self.hovered_rows and col < self.hovered_cols)
                
                if is_hovered:
                    painter.setBrush(QBrush(QColor(self.highlight_color)))
                    painter.setPen(QPen(QColor(self.highlight_color).darker(120), 1))
                else:
                    painter.setBrush(QBrush(QColor(self.cell_bg_color)))
                    painter.setPen(QPen(QColor(self.border_color), 1))
                
                painter.drawRect(rect)
        
        painter.end()
    
    def _on_mouse_move(self, event: QMouseEvent) -> None:
        """处理鼠标移动"""
        pos = event.position().toPoint()
        col = min(int(pos.x() // (self.cell_size + self.cell_spacing)) + 1, self.max_cols)
        row = min(int(pos.y() // (self.cell_size + self.cell_spacing)) + 1, self.max_rows)
        
        col = max(1, col)
        row = max(1, row)
        
        if self.hovered_rows != row or self.hovered_cols != col:
            self.hovered_rows = row
            self.hovered_cols = col
            self.selection_label.setText(self.tr(f"{row} × {col} 网格"))
            self.grid_widget.update()
    
    def _on_mouse_press(self, event: QMouseEvent) -> None:
        """处理鼠标点击"""
        if event.button() == Qt.LeftButton and self.hovered_rows > 0 and self.hovered_cols > 0:
            logger.info(f"[DynamicLayoutSelector._on_mouse_press] 选择动态布局: {self.hovered_rows}x{self.hovered_cols}")
            self.layout_selected.emit(self.hovered_rows, self.hovered_cols)
    
    def _on_mouse_leave(self, event) -> None:
        """处理鼠标离开"""
        self.hovered_rows = 0
        self.hovered_cols = 0
        self.selection_label.setText(self.tr("1 × 1 网格"))
        self.grid_widget.update()


class LayoutDropdown(QFrame):
    """布局下拉菜单"""
    
    layout_selected = Signal(tuple)  # 修改为发送布局配置
    auto_assign_requested = Signal()
    clear_bindings_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        logger.debug("[LayoutDropdown.__init__] 初始化布局下拉菜单")
        
        # 获取主题管理器并注册
        self.theme_manager = None
        self._register_to_theme_manager()
        
        self._load_theme_colors()
        self._setup_ui()
        self._setup_style()
        
        logger.debug("[LayoutDropdown.__init__] 布局下拉菜单初始化完成")
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            logger.info(f"[LayoutDropdown._register_to_theme_manager] 获取父窗口: {main_window.__class__.__name__ if main_window else 'None'}")
            logger.info(f"[LayoutDropdown._register_to_theme_manager] 父窗口是否有theme_manager: {hasattr(main_window, 'theme_manager') if main_window else False}")
            
            if hasattr(main_window, 'theme_manager') and main_window.theme_manager is not None:
                self.theme_manager = main_window.theme_manager
                self.theme_manager.register_component(self)
                logger.info("[LayoutDropdown._register_to_theme_manager] 成功注册到主题管理器")
                # 立即应用当前主题
                current_theme = self.theme_manager.get_current_theme()
                self.update_theme(current_theme)
                logger.info(f"[LayoutDropdown._register_to_theme_manager] 已应用当前主题: {current_theme}")
            else:
                # 尝试通过QApplication获取主题管理器
                logger.info("[LayoutDropdown._register_to_theme_manager] 尝试通过QApplication获取主题管理器")
                app = QApplication.instance()
                logger.info(f"[LayoutDropdown._register_to_theme_manager] QApplication实例: {app.__class__.__name__ if app else 'None'}")
                if app and hasattr(app, 'main_window'):
                    logger.info(f"[LayoutDropdown._register_to_theme_manager] app.main_window: {app.main_window.__class__.__name__ if hasattr(app, 'main_window') else 'None'}")
                    if hasattr(app.main_window, 'theme_manager'):
                        self.theme_manager = app.main_window.theme_manager
                        self.theme_manager.register_component(self)
                        logger.info("[LayoutDropdown._register_to_theme_manager] 通过QApplication成功注册到主题管理器")
                        current_theme = self.theme_manager.get_current_theme()
                        self.update_theme(current_theme)
                        logger.info(f"[LayoutDropdown._register_to_theme_manager] 已应用当前主题: {current_theme}")
                    else:
                        logger.warning("[LayoutDropdown._register_to_theme_manager] app.main_window没有theme_manager属性")
                else:
                    logger.warning("[LayoutDropdown._register_to_theme_manager] 无法通过QApplication获取主题管理器")
                    logger.warning("[LayoutDropdown._register_to_theme_manager] 未找到主题管理器，使用默认颜色")
        except Exception as e:
            logger.error(f"[LayoutDropdown._register_to_theme_manager] 注册到主题管理器失败: {e}", exc_info=True)
    
    def showEvent(self, event):
        """显示事件 - 确保主题管理器注册"""
        logger.info("[LayoutDropdown.showEvent] 显示事件触发")
        super().showEvent(event)
        if not self.theme_manager:
            logger.info("[LayoutDropdown.showEvent] 主题管理器未设置，重新尝试注册")
            self._register_to_theme_manager()
        else:
            logger.info("[LayoutDropdown.showEvent] 主题管理器已设置")
    
    def closeEvent(self, event):
        """关闭事件 - 取消注册"""
        if self.theme_manager:
            self.theme_manager.unregister_component(self)
        super().closeEvent(event)
        
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[LayoutDropdown.update_theme] 开始更新主题: {theme_name}")
        self._load_theme_colors()
        self._update_styles()
        
        # 同时更新子组件的主题
        if hasattr(self, 'dynamic_selector') and hasattr(self.dynamic_selector, 'update_theme'):
            self.dynamic_selector.update_theme(theme_name)
            logger.info("[LayoutDropdown.update_theme] 已更新DynamicLayoutSelector主题")
        
        logger.info(f"[LayoutDropdown.update_theme] 主题更新完成: {theme_name}")
        
    def _load_theme_colors(self) -> None:
        """加载主题颜色"""
        try:
            if self.theme_manager:
                theme_data = self.theme_manager.get_theme_settings('ui')
                self.bg_color = theme_data.get('background_color', '#FFFFFF')
                self.text_color = theme_data.get('text_color', '#333333')
                self.border_color = theme_data.get('border_color', '#CCCCCC')
                self.highlight_color = theme_data.get('highlight_color', '#3498DB')
            else:
                # 默认颜色
                self.bg_color = '#FFFFFF'
                self.text_color = '#333333'
                self.border_color = '#CCCCCC'
                self.highlight_color = '#3498DB'
        except Exception as e:
            logger.warning(f"[LayoutDropdown._load_theme_colors] 加载主题颜色失败: {e}")
            self.bg_color = '#FFFFFF'
            self.text_color = '#333333'
            self.border_color = '#CCCCCC'
            self.highlight_color = '#3498DB'
    
    def _update_styles(self) -> None:
        """更新样式"""
        # 更新标签样式
        if hasattr(self, 'preset_label'):
            self.preset_label.setStyleSheet(f"color: {self.text_color};")
        if hasattr(self, 'action_label'):
            self.action_label.setStyleSheet(f"color: {self.text_color};")
        
        # 更新分隔线样式
        if hasattr(self, 'separator1'):
            self.separator1.setStyleSheet(f"color: {self.border_color};")
        if hasattr(self, 'separator2'):
            self.separator2.setStyleSheet(f"color: {self.border_color};")
        
        # 重新设置整体样式
        self._setup_style()
    
    def _setup_ui(self) -> None:
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 预设布局区域 - 标题左对齐
        self.preset_label = QLabel(self.tr("预设布局"))
        self.preset_label.setAlignment(Qt.AlignLeft)  # 改为左对齐
        self.preset_label.setFont(QFont("", 9, QFont.Bold))
        self.preset_label.setStyleSheet(f"color: {self.text_color};")
        layout.addWidget(self.preset_label)
        
        # 预设布局网格 - 只保留特殊布局
        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        
        # 定义预设布局（只保留指定的4种特殊布局）
        presets = [
            # 用户指定的4种特殊布局
            ({'type': 'vertical_split', 'top_ratio': 0.6, 'bottom_split': True}, "上下分割+下分左右"),
            ({'type': 'horizontal_split', 'left_ratio': 0.6, 'right_split': True}, "左右分割+右分上下"),
            ({'type': 'triple_column_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'right_split': True}, "左右三等分+右边上下等分"),
            ({'type': 'triple_column_middle_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'middle_split': True, 'right_split': True}, "左右三等分+中间和右边上下等分"),
        ]
        
        for i, (config, name) in enumerate(presets):
            preset_btn = LayoutPresetButton(config, name)
            preset_btn.layout_selected.connect(self._on_preset_selected)
            row = i // 4
            col = i % 4
            preset_grid.addWidget(preset_btn, row, col)
        
        layout.addLayout(preset_grid)
        
        # 分隔线
        self.separator1 = QFrame()
        self.separator1.setFrameShape(QFrame.HLine)
        self.separator1.setFrameShadow(QFrame.Sunken)
        self.separator1.setStyleSheet(f"color: {self.border_color};")
        layout.addWidget(self.separator1)
        
        # 动态布局选择器
        self.dynamic_selector = DynamicLayoutSelector()
        self.dynamic_selector.layout_selected.connect(self._on_dynamic_selected)
        layout.addWidget(self.dynamic_selector)
        
        # 分隔线
        self.separator2 = QFrame()
        self.separator2.setFrameShape(QFrame.HLine)
        self.separator2.setFrameShadow(QFrame.Sunken)
        self.separator2.setStyleSheet(f"color: {self.border_color};")
        layout.addWidget(self.separator2)
        
        # 操作按钮区域 - 标题左对齐
        self.action_label = QLabel(self.tr("序列操作"))
        self.action_label.setAlignment(Qt.AlignLeft)  # 改为左对齐
        self.action_label.setFont(QFont("", 9, QFont.Bold))
        self.action_label.setStyleSheet(f"color: {self.text_color};")
        layout.addWidget(self.action_label)
        
        # 操作按钮
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        auto_assign_btn = QPushButton(self.tr("自动分配"))
        auto_assign_btn.setToolTip(self.tr("自动将序列分配到可用视图"))
        auto_assign_btn.clicked.connect(self._on_auto_assign)
        action_layout.addWidget(auto_assign_btn)
        
        clear_bindings_btn = QPushButton(self.tr("清除绑定"))
        clear_bindings_btn.setToolTip(self.tr("清除所有序列绑定"))
        clear_bindings_btn.clicked.connect(self._on_clear_bindings)
        action_layout.addWidget(clear_bindings_btn)
        
        layout.addLayout(action_layout)
    
    def _setup_style(self) -> None:
        """设置样式"""
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        
        self.setStyleSheet(f"""
            LayoutDropdown {{
                background-color: {self.bg_color};
                border: 1px solid {self.border_color};
                border-radius: 6px;
            }}
            QPushButton {{
                padding: 6px 12px;
                border: 1px solid {self.border_color};
                border-radius: 4px;
                background-color: {self._adjust_color_brightness(self.bg_color, -5)};
                color: {self.text_color};
            }}
            QPushButton:hover {{
                background-color: {self._adjust_color_brightness(self.highlight_color, 40)};
                border-color: {self.highlight_color};
            }}
            QPushButton:pressed {{
                background-color: {self._adjust_color_brightness(self.highlight_color, 20)};
            }}
        """)
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            color_hex = color_hex.lstrip('#')
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            
            r = max(0, min(255, r + amount))
            g = max(0, min(255, g + amount))
            b = max(0, min(255, b + amount))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color_hex
    
    def _on_preset_selected(self, layout_config: tuple) -> None:
        """处理预设布局选择"""
        logger.info(f"[LayoutDropdown._on_preset_selected] 选择预设布局: {layout_config}")
        self.layout_selected.emit(layout_config)
        self.hide()
    
    def _on_dynamic_selected(self, rows: int, cols: int) -> None:
        """处理动态布局选择"""
        logger.info(f"[LayoutDropdown._on_dynamic_selected] 选择动态布局: {rows}x{cols}")
        self.layout_selected.emit((rows, cols))
        self.hide()
    
    def _on_auto_assign(self) -> None:
        """处理自动分配"""
        logger.info("[LayoutDropdown._on_auto_assign] 请求自动分配")
        self.auto_assign_requested.emit()
        self.hide()
    
    def _on_clear_bindings(self) -> None:
        """处理清除绑定"""
        logger.info("[LayoutDropdown._on_clear_bindings] 请求清除绑定")
        self.clear_bindings_requested.emit()
        self.hide()
    
    def show_at_position(self, global_pos: QPoint) -> None:
        """在指定位置显示下拉菜单"""
        logger.info(f"[LayoutDropdown.show_at_position] 显示布局下拉菜单: {global_pos}")
        
        # 确保在显示前注册到主题管理器
        if not self.theme_manager:
            logger.info("[LayoutDropdown.show_at_position] 主题管理器未设置，重新尝试注册")
            self._register_to_theme_manager()
            logger.info("[LayoutDropdown.show_at_position] 重新尝试注册主题管理器完成")
        else:
            logger.info("[LayoutDropdown.show_at_position] 主题管理器已设置")
        
        self.adjustSize()
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        
        # 计算显示位置
        x = global_pos.x()
        y = global_pos.y()
        
        if x + self.width() > screen.right():
            x = screen.right() - self.width()
        if y + self.height() > screen.bottom():
            y = global_pos.y() - self.height()
        
        self.move(max(0, x), max(0, y))
        logger.info(f"[LayoutDropdown.show_at_position] 准备显示下拉菜单，位置: ({max(0, x)}, {max(0, y)})")
        self.show()
        self.raise_()
        self.activateWindow()
        logger.info("[LayoutDropdown.show_at_position] 下拉菜单显示完成")


class LayoutSelectorButton(QPushButton):
    """布局选择器按钮
    
    点击时显示简约的布局选择下拉菜单。
    
    Signals:
        layout_selected (tuple): 当选择布局时发出，参数为布局配置
        auto_assign_requested: 当请求自动分配时发出
        clear_bindings_requested: 当请求清除绑定时发出
    """
    
    layout_selected = Signal(tuple)  # 修改为发送布局配置
    auto_assign_requested = Signal()
    clear_bindings_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化布局选择器按钮"""
        super().__init__(parent)
        logger.debug("[LayoutSelectorButton.__init__] 初始化布局选择器按钮")
        
        # 设置对象名称，确保样式生效
        self.setObjectName("LayoutSelectorButton")
        
        # 获取主题管理器
        self.theme_manager = None
        self._register_to_theme_manager()
        
        # 使用图标而不是文字
        self._create_layout_icon()
        self.setToolTip(self.tr("选择视图布局"))
        
        # 创建下拉菜单
        self.dropdown = LayoutDropdown()
        self.dropdown.layout_selected.connect(self._on_layout_selected)
        self.dropdown.auto_assign_requested.connect(self._on_auto_assign_requested)
        self.dropdown.clear_bindings_requested.connect(self._on_clear_bindings_requested)
        
        # 连接点击事件
        self.clicked.connect(self._show_dropdown)
        
        # 监听主题变化
        self._connect_theme_signals()
        
        logger.debug("[LayoutSelectorButton.__init__] 布局选择器按钮初始化完成")
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            logger.info(f"[LayoutSelectorButton._register_to_theme_manager] 获取父窗口: {main_window.__class__.__name__ if main_window else 'None'}")
            logger.info(f"[LayoutSelectorButton._register_to_theme_manager] 父窗口是否有theme_manager: {hasattr(main_window, 'theme_manager') if main_window else False}")
            
            if hasattr(main_window, 'theme_manager') and main_window.theme_manager is not None:
                self.theme_manager = main_window.theme_manager
                self.theme_manager.register_component(self)
                logger.info("[LayoutSelectorButton._register_to_theme_manager] 成功注册到主题管理器")
                # 立即应用当前主题
                current_theme = self.theme_manager.get_current_theme()
                self.update_theme(current_theme)
                logger.info(f"[LayoutSelectorButton._register_to_theme_manager] 已应用当前主题: {current_theme}")
            else:
                # 尝试通过QApplication获取主题管理器
                logger.info("[LayoutSelectorButton._register_to_theme_manager] 尝试通过QApplication获取主题管理器")
                app = QApplication.instance()
                logger.info(f"[LayoutSelectorButton._register_to_theme_manager] QApplication实例: {app.__class__.__name__ if app else 'None'}")
                if app and hasattr(app, 'main_window'):
                    logger.info(f"[LayoutSelectorButton._register_to_theme_manager] app.main_window: {app.main_window.__class__.__name__ if hasattr(app, 'main_window') else 'None'}")
                    if hasattr(app.main_window, 'theme_manager'):
                        self.theme_manager = app.main_window.theme_manager
                        self.theme_manager.register_component(self)
                        logger.info("[LayoutSelectorButton._register_to_theme_manager] 通过QApplication成功注册到主题管理器")
                        current_theme = self.theme_manager.get_current_theme()
                        self.update_theme(current_theme)
                        logger.info(f"[LayoutSelectorButton._register_to_theme_manager] 已应用当前主题: {current_theme}")
                    else:
                        logger.warning("[LayoutSelectorButton._register_to_theme_manager] app.main_window没有theme_manager属性")
                else:
                    logger.warning("[LayoutSelectorButton._register_to_theme_manager] 无法通过QApplication获取主题管理器")
                    logger.warning("[LayoutSelectorButton._register_to_theme_manager] 未找到主题管理器，使用默认颜色")
        except Exception as e:
            logger.error(f"[LayoutSelectorButton._register_to_theme_manager] 注册到主题管理器失败: {e}", exc_info=True)
    
    def showEvent(self, event):
        """显示事件 - 确保主题管理器注册"""
        logger.info("[LayoutSelectorButton.showEvent] 显示事件触发")
        super().showEvent(event)
        if not self.theme_manager:
            logger.info("[LayoutSelectorButton.showEvent] 主题管理器未设置，重新尝试注册")
            self._register_to_theme_manager()
        else:
            logger.info("[LayoutSelectorButton.showEvent] 主题管理器已设置")
    
    def closeEvent(self, event):
        """关闭事件 - 取消注册"""
        if self.theme_manager:
            self.theme_manager.unregister_component(self)
        super().closeEvent(event)
        
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[LayoutSelectorButton.update_theme] 收到主题更新请求: {theme_name}")
        try:
            logger.info("[LayoutSelectorButton.update_theme] 开始创建布局图标")
            self._create_layout_icon()
            logger.info("[LayoutSelectorButton.update_theme] 布局图标创建完成")
            logger.info("[LayoutSelectorButton.update_theme] 开始应用主题样式")
            self._apply_theme_style()
            logger.info("[LayoutSelectorButton.update_theme] 主题样式应用完成")
        except Exception as e:
            logger.error(f"[LayoutSelectorButton.update_theme] 主题更新失败: {e}", exc_info=True)
    
    def _connect_theme_signals(self) -> None:
        """连接主题变化信号"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                main_window.theme_manager.theme_changed.connect(self._on_theme_changed)
        except Exception as e:
            logger.debug(f"[LayoutSelectorButton._connect_theme_signals] 连接主题信号失败: {e}")
    
    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变化时更新图标"""
        logger.debug(f"[LayoutSelectorButton._on_theme_changed] 主题变化: {theme_name}")
        self._create_layout_icon()
    
    def _create_layout_icon(self) -> None:
        """创建布局图标"""
        # 使用layout.svg图标
        from medimager.utils.resource_path import get_icon_path
        layout_icon_path = get_icon_path("layout.svg")
        
        # 根据主题创建合适颜色的图标
        icon = self._create_themed_icon(layout_icon_path)
        self.setIcon(icon)
        
        # 清除文本，只使用图标
        self.setText("")
        self.setMinimumSize(32, 32)
        self.setMaximumSize(32, 32)  # 设置最大尺寸，与工具栏按钮保持一致
    
    def _create_themed_icon(self, svg_path: str) -> QIcon:
        """根据主题创建合适颜色的图标"""
        try:
            # 获取主题颜色
            if self.theme_manager:
                theme_data = self.theme_manager.get_theme_settings('ui')
            else:
                from medimager.utils.theme_manager import get_theme_settings
                theme_data = get_theme_settings('ui')
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
            logger.warning(f"[LayoutSelectorButton._create_themed_icon] 创建主题图标失败: {e}")
            # 回退到原始图标
            return QIcon(svg_path)
    
    def _get_color_brightness(self, color_hex: str) -> int:
        """计算颜色亮度"""
        # 移除 # 符号
        color_hex = color_hex.lstrip('#')
        
        # 转换为RGB
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
        
        # 使用感知亮度公式 (ITU-R BT.709)
        brightness = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return int(brightness)
    
    def _apply_theme_style(self) -> None:
        """应用主题样式"""
        try:
            if self.theme_manager:
                theme_data = self.theme_manager.get_theme_settings('ui')
            else:
                from medimager.utils.theme_manager import get_theme_settings
                theme_data = get_theme_settings('ui')
            
            bg_color = theme_data.get('background_color', '#F0F0F0')
            text_color = theme_data.get('text_color', '#000000')
            border_color = theme_data.get('border_color', '#CCCCCC')
            
            self.setStyleSheet(f"""
                LayoutSelectorButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: 1px solid {border_color};
                    border-radius: 4px;
                    padding: 6px 12px;
                    text-align: center;
                    font-size: 14px;
                }}
                LayoutSelectorButton:hover {{
                    background-color: {self._adjust_color_brightness(bg_color, -10)};
                }}
                LayoutSelectorButton:pressed {{
                    background-color: {self._adjust_color_brightness(bg_color, -20)};
                }}
            """)
            
            logger.debug("[LayoutSelectorButton._apply_theme_style] 主题样式应用完成")
            
        except Exception as e:
            logger.warning(f"[LayoutSelectorButton._apply_theme_style] 应用主题样式失败: {e}")
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            color_hex = color_hex.lstrip('#')
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            
            r = max(0, min(255, r + amount))
            g = max(0, min(255, g + amount))
            b = max(0, min(255, b + amount))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color_hex
    
    def _show_dropdown(self) -> None:
        """显示下拉菜单"""
        logger.debug("[LayoutSelectorButton._show_dropdown] 显示布局下拉菜单")
        
        # 计算下拉菜单位置
        button_rect = self.geometry()
        global_pos = self.mapToGlobal(QPoint(0, self.height()))
        
        self.dropdown.show_at_position(global_pos)
    
    def _on_layout_selected(self, layout_config: tuple) -> None:
        """处理布局选择"""
        logger.info(f"[LayoutSelectorButton._on_layout_selected] 布局选择: {layout_config}")
        # 更新按钮显示
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            self.setToolTip(self.tr(f"当前布局: {rows}×{cols}"))
        else:
            self.setToolTip(self.tr("当前布局: 特殊布局"))
        
        self.layout_selected.emit(layout_config)
    
    def _on_auto_assign_requested(self) -> None:
        """处理自动分配请求"""
        logger.info("[LayoutSelectorButton._on_auto_assign_requested] 自动分配请求")
        self.auto_assign_requested.emit()
    
    def _on_clear_bindings_requested(self) -> None:
        """处理清除绑定请求"""
        logger.info("[LayoutSelectorButton._on_clear_bindings_requested] 清除绑定请求")
        self.clear_bindings_requested.emit()
    
    def set_current_layout(self, layout_config: tuple) -> None:
        """设置当前布局显示"""
        logger.debug(f"[LayoutSelectorButton.set_current_layout] 设置当前布局: {layout_config}")
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            self.setToolTip(self.tr(f"当前布局: {rows}×{cols}"))
        else:
            self.setToolTip(self.tr("当前布局: 特殊布局"))