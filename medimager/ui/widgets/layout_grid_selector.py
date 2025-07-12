"""
布局网格选择器组件

提供类似Excel表格插入工具的交互式布局选择功能。
"""

from typing import Tuple, Optional
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QApplication
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QSize, QTimer
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QMouseEvent, QPaintEvent

from medimager.utils.logger import get_logger
from medimager.utils.theme_manager import get_theme_settings

logger = get_logger(__name__)


class LayoutGridSelector(QFrame):
    """布局网格选择器
    
    提供交互式的网格布局选择功能，类似Excel的表格插入工具。
    
    Signals:
        layout_selected (int, int): 当选择布局时发出，参数为(rows, cols)
    """
    
    layout_selected = Signal(int, int)
    
    def __init__(self, max_rows: int = 3, max_cols: int = 4, parent: Optional[QWidget] = None):
        """初始化网格选择器
        
        Args:
            max_rows: 最大行数
            max_cols: 最大列数
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug(f"[LayoutGridSelector.__init__] 初始化网格选择器: {max_rows}x{max_cols}")
        
        self.max_rows = max_rows
        self.max_cols = max_cols
        self.cell_size = 40  # 从20增加到40，让格子更大
        self.cell_spacing = 6  # 从2增加到6，让间距也稍大一些
        self.hovered_rows = 0
        self.hovered_cols = 0
        
        # 获取主题颜色
        self._load_theme_colors()
        
        self._setup_ui()
        self._setup_style()
        
        logger.debug("[LayoutGridSelector.__init__] 网格选择器初始化完成")
    
    def _load_theme_colors(self) -> None:
        """加载主题颜色"""
        try:
            theme_data = get_theme_settings('ui')
            
            # 获取主题颜色，提供默认值
            self.bg_color = theme_data.get('background_color', '#F0F0F0')
            self.text_color = theme_data.get('text_color', '#000000')
            self.border_color = theme_data.get('border_color', '#CCCCCC')
            self.highlight_color = theme_data.get('highlight_color', '#3498DB')
            
            # 计算衍生颜色
            self.cell_bg_color = self._adjust_color_brightness(self.bg_color, 10)
            self.cell_border_color = self._adjust_color_brightness(self.border_color, -10)
            
            logger.debug("[LayoutGridSelector._load_theme_colors] 主题颜色加载完成")
            
        except Exception as e:
            logger.warning(f"[LayoutGridSelector._load_theme_colors] 加载主题颜色失败: {e}")
            # 使用默认颜色
            self.bg_color = '#F0F0F0'
            self.text_color = '#000000'
            self.border_color = '#CCCCCC'
            self.highlight_color = '#3498DB'
            self.cell_bg_color = '#FFFFFF'
            self.cell_border_color = '#B0B0B0'
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            # 移除#号
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
            
        except Exception:
            return color_hex  # 如果转换失败，返回原色
    
    def _setup_ui(self) -> None:
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 标题标签
        self.title_label = QLabel(self.tr("选择布局"))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("", 9, QFont.Bold))
        layout.addWidget(self.title_label)
        
        # 网格区域
        self.grid_widget = QWidget()
        grid_width = self.max_cols * (self.cell_size + self.cell_spacing) - self.cell_spacing
        grid_height = self.max_rows * (self.cell_size + self.cell_spacing) - self.cell_spacing
        self.grid_widget.setFixedSize(grid_width, grid_height)
        self.grid_widget.setMouseTracking(True)
        layout.addWidget(self.grid_widget, 0, Qt.AlignCenter)
        
        # 当前选择标签
        self.selection_label = QLabel(self.tr("1 × 1 表格"))
        self.selection_label.setAlignment(Qt.AlignCenter)
        self.selection_label.setFont(QFont("", 8))
        layout.addWidget(self.selection_label)
        
        # 设置鼠标跟踪
        self.setMouseTracking(True)
        self.grid_widget.mouseMoveEvent = self._on_mouse_move
        self.grid_widget.mousePressEvent = self._on_mouse_press
        self.grid_widget.leaveEvent = self._on_mouse_leave
        self.grid_widget.paintEvent = self._paint_grid
    
    def _setup_style(self) -> None:
        """设置样式"""
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        
        # 使用主题颜色设置样式
        self.setStyleSheet(f"""
            LayoutGridSelector {{
                background-color: {self.bg_color};
                border: 1px solid {self.border_color};
                border-radius: 4px;
            }}
            QLabel {{
                color: {self.text_color};
            }}
        """)
        
        # 设置窗口标志，使其显示为弹出窗口
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
    
    def _paint_grid(self, event: QPaintEvent) -> None:
        """绘制网格"""
        painter = QPainter(self.grid_widget)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制所有单元格
        for row in range(self.max_rows):
            for col in range(self.max_cols):
                x = col * (self.cell_size + self.cell_spacing)
                y = row * (self.cell_size + self.cell_spacing)
                rect = QRect(x, y, self.cell_size, self.cell_size)
                
                # 确定单元格状态
                is_hovered = (row < self.hovered_rows and col < self.hovered_cols)
                
                # 绘制单元格
                if is_hovered:
                    # 选中状态：使用主题高亮色
                    painter.setBrush(QBrush(QColor(self.highlight_color)))
                    painter.setPen(QPen(QColor(self._adjust_color_brightness(self.highlight_color, -20)), 1))
                else:
                    # 默认状态：使用主题背景色
                    painter.setBrush(QBrush(QColor(self.cell_bg_color)))
                    painter.setPen(QPen(QColor(self.cell_border_color), 1))
                
                painter.drawRect(rect)
        
        painter.end()
    
    def _on_mouse_move(self, event: QMouseEvent) -> None:
        """处理鼠标移动事件"""
        pos = event.position().toPoint()
        
        # 计算鼠标悬停的行列
        col = min(int(pos.x() // (self.cell_size + self.cell_spacing)) + 1, self.max_cols)
        row = min(int(pos.y() // (self.cell_size + self.cell_spacing)) + 1, self.max_rows)
        
        # 确保至少选择1x1
        col = max(1, col)
        row = max(1, row)
        
        if self.hovered_rows != row or self.hovered_cols != col:
            self.hovered_rows = row
            self.hovered_cols = col
            
            # 更新标签
            self.selection_label.setText(self.tr(f"{row} × {col} 表格"))
            
            # 重绘网格
            self.grid_widget.update()
            
            logger.debug(f"[LayoutGridSelector._on_mouse_move] 悬停: {row}x{col}")
    
    def _on_mouse_press(self, event: QMouseEvent) -> None:
        """处理鼠标点击事件"""
        if event.button() == Qt.LeftButton and self.hovered_rows > 0 and self.hovered_cols > 0:
            logger.info(f"[LayoutGridSelector._on_mouse_press] 选择布局: {self.hovered_rows}x{self.hovered_cols}")
            self.layout_selected.emit(self.hovered_rows, self.hovered_cols)
            self.hide()
    
    def _on_mouse_leave(self, event) -> None:
        """处理鼠标离开事件"""
        self.hovered_rows = 0
        self.hovered_cols = 0
        self.selection_label.setText(self.tr("1 × 1 表格"))
        self.grid_widget.update()
    
    def show_at_position(self, global_pos: QPoint) -> None:
        """在指定位置显示选择器
        
        Args:
            global_pos: 全局坐标位置
        """
        logger.debug(f"[LayoutGridSelector.show_at_position] 显示网格选择器: {global_pos}")
        
        # 调整尺寸
        self.adjustSize()
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        
        # 计算显示位置，确保不超出屏幕边界
        x = global_pos.x()
        y = global_pos.y()
        
        if x + self.width() > screen.right():
            x = screen.right() - self.width()
        if y + self.height() > screen.bottom():
            y = global_pos.y() - self.height()
        
        self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()
        self.activateWindow()


class LayoutSelectorButton(QPushButton):
    """布局选择器按钮
    
    点击时显示网格选择器的按钮组件。
    
    Signals:
        layout_selected (int, int): 当选择布局时发出，参数为(rows, cols)
    """
    
    layout_selected = Signal(int, int)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化布局选择器按钮"""
        super().__init__(parent)
        logger.debug("[LayoutSelectorButton.__init__] 初始化布局选择器按钮")
        
        self.setText(self.tr("布局 ▼"))
        self.setToolTip(self.tr("点击选择视图布局"))
        
        # 应用主题样式
        self._apply_theme_style()
        
        # 创建网格选择器
        self.grid_selector = LayoutGridSelector()
        self.grid_selector.layout_selected.connect(self._on_layout_selected)
        
        # 连接点击事件
        self.clicked.connect(self._show_grid_selector)
        
        logger.debug("[LayoutSelectorButton.__init__] 布局选择器按钮初始化完成")
    
    def _apply_theme_style(self) -> None:
        """应用主题样式"""
        try:
            theme_data = get_theme_settings('ui')
            
            bg_color = theme_data.get('background_color', '#F0F0F0')
            text_color = theme_data.get('text_color', '#000000')
            border_color = theme_data.get('border_color', '#CCCCCC')
            highlight_color = theme_data.get('highlight_color', '#3498DB')
            
            # 计算悬停和按下状态的颜色
            hover_color = self._adjust_color_brightness(highlight_color, 20)
            pressed_color = self._adjust_color_brightness(highlight_color, -20)
            
            self.setStyleSheet(f"""
                LayoutSelectorButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: 1px solid {border_color};
                    padding: 4px 8px;
                    border-radius: 3px;
                }}
                LayoutSelectorButton:hover {{
                    background-color: {hover_color};
                    border-color: {highlight_color};
                }}
                LayoutSelectorButton:pressed {{
                    background-color: {pressed_color};
                }}
            """)
            
            logger.debug("[LayoutSelectorButton._apply_theme_style] 主题样式应用完成")
            
        except Exception as e:
            logger.warning(f"[LayoutSelectorButton._apply_theme_style] 应用主题样式失败: {e}")
    
    def _adjust_color_brightness(self, color_hex: str, amount: int) -> str:
        """调整颜色亮度"""
        try:
            # 移除#号
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
            
        except Exception:
            return color_hex  # 如果转换失败，返回原色
    
    def _show_grid_selector(self) -> None:
        """显示网格选择器"""
        logger.debug("[LayoutSelectorButton._show_grid_selector] 显示网格选择器")
        
        # 计算显示位置（按钮下方）
        global_pos = self.mapToGlobal(QPoint(0, self.height()))
        self.grid_selector.show_at_position(global_pos)
    
    def _on_layout_selected(self, rows: int, cols: int) -> None:
        """处理布局选择事件"""
        logger.info(f"[LayoutSelectorButton._on_layout_selected] 布局选择: {rows}x{cols}")
        self.layout_selected.emit(rows, cols)
    
    def set_current_layout(self, rows: int, cols: int) -> None:
        """设置当前布局显示
        
        Args:
            rows: 当前行数
            cols: 当前列数
        """
        self.setText(self.tr(f"布局 {rows}×{cols} ▼")) 