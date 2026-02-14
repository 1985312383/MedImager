"""
布局网格选择器组件

提供简约的布局选择功能，包含预设布局和动态调整。
"""

from typing import Optional
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QApplication, QGridLayout, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QByteArray
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QMouseEvent, QPaintEvent, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer

from medimager.utils.logger import get_logger
from medimager.utils.theme_manager import ThemeAwareMixin, get_theme_settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 共享的主题颜色加载
# ---------------------------------------------------------------------------
_DEFAULT_COLORS = {
    'bg_color': '#FFFFFF',
    'text_color': '#333333',
    'border_color': '#CCCCCC',
    'highlight_color': '#3498DB',
}


def _load_ui_colors(theme_manager) -> dict:
    """从 ThemeManager 加载 UI 主题颜色，失败时返回默认值。"""
    try:
        if theme_manager:
            td = theme_manager.get_theme_settings('ui')
            return {
                'bg_color': td.get('background_color', '#FFFFFF'),
                'text_color': td.get('text_color', '#333333'),
                'border_color': td.get('border_color', '#CCCCCC'),
                'highlight_color': td.get('highlight_color', '#3498DB'),
            }
    except Exception as e:
        logger.debug(f"加载主题颜色失败: {e}")
    return dict(_DEFAULT_COLORS)


# ---------------------------------------------------------------------------
# LayoutPresetButton
# ---------------------------------------------------------------------------
class LayoutPresetButton(ThemeAwareMixin, QPushButton):
    """布局预设按钮 - 使用图标显示布局"""

    layout_selected = Signal(object)

    def __init__(self, layout_config, layout_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.layout_config = layout_config
        self.layout_name = layout_name
        self.setFixedSize(60, 45)
        self.clicked.connect(self._on_clicked)
        self.setToolTip(self.tr(layout_name))

        self._colors = _load_ui_colors(self._theme_manager)
        self._setup_style()
        self._register_to_theme_manager()

    def update_theme(self, theme_name: str) -> None:
        self._colors = _load_ui_colors(self._theme_manager)
        self._setup_style()
        self.update()

    def _setup_style(self) -> None:
        c = self._colors
        self.setStyleSheet(f"""
            LayoutPresetButton {{
                border: 1px solid {c['border_color']};
                border-radius: 4px;
                background-color: {c['bg_color']};
                margin: 2px;
            }}
            LayoutPresetButton:hover {{
                background-color: {c['highlight_color']};
                border-color: {c['highlight_color']};
            }}
            LayoutPresetButton:pressed {{
                background-color: {self.adjust_color_brightness(c['highlight_color'], -20)};
            }}
        """)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        margin = 8
        draw_width = self.width() - 2 * margin
        draw_height = self.height() - 2 * margin
        c = self._colors

        if self.isDown():
            painter.setPen(QPen(QColor(c['highlight_color']), 1.5))
            painter.setBrush(QBrush(QColor(c['highlight_color'])))
        elif self.underMouse():
            hover_color = self.adjust_color_brightness(c['text_color'], 30)
            painter.setPen(QPen(QColor(hover_color), 1.5))
            painter.setBrush(QBrush(QColor(hover_color)))
        else:
            painter.setPen(QPen(QColor(c['text_color']), 1.5))
            painter.setBrush(QBrush(QColor(c['text_color'])))

        self._draw_layout_icon(painter, margin, draw_width, draw_height)
        painter.end()

    def _draw_layout_icon(self, painter: QPainter, margin: int, width: int, height: int) -> None:
        if isinstance(self.layout_config, tuple) and len(self.layout_config) == 2:
            rows, cols = self.layout_config
            self._draw_grid_layout(painter, margin, width, height, rows, cols)
        elif isinstance(self.layout_config, dict):
            self._draw_special_layout(painter, margin, width, height, self.layout_config)

    def _draw_grid_layout(self, painter: QPainter, margin: int, width: int, height: int, rows: int, cols: int) -> None:
        cell_width = width / cols
        cell_height = height / rows
        for row in range(rows):
            for col in range(cols):
                x = margin + col * cell_width
                y = margin + row * cell_height
                rect = QRect(int(x + 1), int(y + 1), int(cell_width - 2), int(cell_height - 2))
                painter.drawRect(rect)

    def _draw_special_layout(self, painter: QPainter, margin: int, width: int, height: int, config: dict) -> None:
        layout_type = config.get('type', '')

        if layout_type == 'vertical_split':
            top_height = height * config.get('top_ratio', 0.5)
            bottom_height = height - top_height
            painter.drawRect(QRect(margin + 1, margin + 1, int(width - 2), int(top_height - 2)))
            if config.get('bottom_split', False):
                half_w = width * 0.5
                painter.drawRect(QRect(margin + 1, int(margin + top_height + 1),
                                       int(half_w - 2), int(bottom_height - 2)))
                painter.drawRect(QRect(int(margin + half_w + 1), int(margin + top_height + 1),
                                       int(width - half_w - 2), int(bottom_height - 2)))
            else:
                painter.drawRect(QRect(margin + 1, int(margin + top_height + 1),
                                       int(width - 2), int(bottom_height - 2)))

        elif layout_type == 'horizontal_split':
            left_width = width * config.get('left_ratio', 0.5)
            right_width = width - left_width
            painter.drawRect(QRect(margin + 1, margin + 1, int(left_width - 2), int(height - 2)))
            if config.get('right_split', False):
                half_h = height * 0.5
                painter.drawRect(QRect(int(margin + left_width + 1), margin + 1,
                                       int(right_width - 2), int(half_h - 2)))
                painter.drawRect(QRect(int(margin + left_width + 1), int(margin + half_h + 1),
                                       int(right_width - 2), int(height - half_h - 2)))
            else:
                painter.drawRect(QRect(int(margin + left_width + 1), margin + 1,
                                       int(right_width - 2), int(height - 2)))

        elif layout_type == 'triple_column_right_split':
            lr = config.get('left_ratio', 0.33)
            mr = config.get('middle_ratio', 0.34)
            lw, mw, rw = width * lr, width * mr, width * (1.0 - lr - mr)
            painter.drawRect(QRect(margin + 1, margin + 1, int(lw - 2), int(height - 2)))
            painter.drawRect(QRect(int(margin + lw + 1), margin + 1, int(mw - 2), int(height - 2)))
            half_h = height * 0.5
            painter.drawRect(QRect(int(margin + lw + mw + 1), margin + 1,
                                   int(rw - 2), int(half_h - 2)))
            painter.drawRect(QRect(int(margin + lw + mw + 1), int(margin + half_h + 1),
                                   int(rw - 2), int(height - half_h - 2)))

        elif layout_type == 'triple_column_middle_right_split':
            lr = config.get('left_ratio', 0.33)
            mr = config.get('middle_ratio', 0.34)
            lw, mw, rw = width * lr, width * mr, width * (1.0 - lr - mr)
            painter.drawRect(QRect(margin + 1, margin + 1, int(lw - 2), int(height - 2)))
            half_h = height * 0.5
            painter.drawRect(QRect(int(margin + lw + 1), margin + 1, int(mw - 2), int(half_h - 2)))
            painter.drawRect(QRect(int(margin + lw + 1), int(margin + half_h + 1),
                                   int(mw - 2), int(height - half_h - 2)))
            painter.drawRect(QRect(int(margin + lw + mw + 1), margin + 1,
                                   int(rw - 2), int(half_h - 2)))
            painter.drawRect(QRect(int(margin + lw + mw + 1), int(margin + half_h + 1),
                                   int(rw - 2), int(height - half_h - 2)))

    def _on_clicked(self) -> None:
        logger.debug(f"选择布局: {self.layout_name}")
        self.layout_selected.emit(self.layout_config)


# ---------------------------------------------------------------------------
# DynamicLayoutSelector
# ---------------------------------------------------------------------------
class DynamicLayoutSelector(ThemeAwareMixin, QFrame):
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

        self._colors = _load_ui_colors(self._theme_manager)
        self._setup_ui()
        self._register_to_theme_manager()

    def update_theme(self, theme_name: str) -> None:
        self._colors = _load_ui_colors(self._theme_manager)
        self._update_styles()
        if hasattr(self, 'grid_widget'):
            self.grid_widget.update()

    def _update_styles(self) -> None:
        c = self._colors
        if hasattr(self, 'title_label'):
            self.title_label.setStyleSheet(f"color: {c['text_color']};")
        if hasattr(self, 'selection_label'):
            self.selection_label.setStyleSheet(f"color: {c['text_color']};")
        self.setStyleSheet(f"""
            DynamicLayoutSelector {{
                background-color: {c['bg_color']};
                border: 1px solid {c['border_color']};
                border-radius: 4px;
            }}
        """)

    def _setup_ui(self) -> None:
        c = self._colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.title_label = QLabel(self.tr("自定义网格"))
        self.title_label.setAlignment(Qt.AlignLeft)
        self.title_label.setFont(QFont("", 9, QFont.Bold))
        self.title_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.title_label)

        self.grid_widget = QWidget()
        grid_width = self.max_cols * (self.cell_size + self.cell_spacing) - self.cell_spacing
        grid_height = self.max_rows * (self.cell_size + self.cell_spacing) - self.cell_spacing
        self.grid_widget.setFixedSize(grid_width, grid_height)
        self.grid_widget.setMouseTracking(True)
        layout.addWidget(self.grid_widget, 0, Qt.AlignCenter)

        self.selection_label = QLabel(self.tr("1 × 1 网格"))
        self.selection_label.setAlignment(Qt.AlignCenter)
        self.selection_label.setFont(QFont("", 8))
        self.selection_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.selection_label)

        self.grid_widget.mouseMoveEvent = self._on_mouse_move
        self.grid_widget.mousePressEvent = self._on_mouse_press
        self.grid_widget.leaveEvent = self._on_mouse_leave
        self.grid_widget.paintEvent = self._paint_grid

        self.setStyleSheet(f"""
            DynamicLayoutSelector {{
                background-color: {c['bg_color']};
                border: 1px solid {c['border_color']};
                border-radius: 4px;
            }}
        """)

    def _paint_grid(self, event: QPaintEvent) -> None:
        c = self._colors
        cell_bg = self.adjust_color_brightness(c['bg_color'], -5)
        painter = QPainter(self.grid_widget)
        painter.setRenderHint(QPainter.Antialiasing)
        for row in range(self.max_rows):
            for col in range(self.max_cols):
                x = col * (self.cell_size + self.cell_spacing)
                y = row * (self.cell_size + self.cell_spacing)
                rect = QRect(x, y, self.cell_size, self.cell_size)
                if row < self.hovered_rows and col < self.hovered_cols:
                    painter.setBrush(QBrush(QColor(c['highlight_color'])))
                    painter.setPen(QPen(QColor(c['highlight_color']).darker(120), 1))
                else:
                    painter.setBrush(QBrush(QColor(cell_bg)))
                    painter.setPen(QPen(QColor(c['border_color']), 1))
                painter.drawRect(rect)
        painter.end()

    def _on_mouse_move(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        col = max(1, min(int(pos.x() // (self.cell_size + self.cell_spacing)) + 1, self.max_cols))
        row = max(1, min(int(pos.y() // (self.cell_size + self.cell_spacing)) + 1, self.max_rows))
        if self.hovered_rows != row or self.hovered_cols != col:
            self.hovered_rows = row
            self.hovered_cols = col
            self.selection_label.setText(self.tr("%1 × %2 网格").replace("%1", str(row)).replace("%2", str(col)))
            self.grid_widget.update()

    def _on_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.hovered_rows > 0 and self.hovered_cols > 0:
            logger.debug(f"选择动态布局: {self.hovered_rows}x{self.hovered_cols}")
            self.layout_selected.emit(self.hovered_rows, self.hovered_cols)

    def _on_mouse_leave(self, event) -> None:
        self.hovered_rows = 0
        self.hovered_cols = 0
        self.selection_label.setText(self.tr("1 × 1 网格"))
        self.grid_widget.update()


# ---------------------------------------------------------------------------
# LayoutDropdown
# ---------------------------------------------------------------------------
class LayoutDropdown(ThemeAwareMixin, QFrame):
    """布局下拉菜单"""

    layout_selected = Signal(object)
    auto_assign_requested = Signal()
    clear_bindings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._colors = _load_ui_colors(self._theme_manager)
        self._setup_ui()
        self._setup_style()
        self._register_to_theme_manager()

    def update_theme(self, theme_name: str) -> None:
        self._colors = _load_ui_colors(self._theme_manager)
        self._update_styles()
        if hasattr(self, 'dynamic_selector'):
            self.dynamic_selector.update_theme(theme_name)

    def _update_styles(self) -> None:
        c = self._colors
        if hasattr(self, 'preset_label'):
            self.preset_label.setStyleSheet(f"color: {c['text_color']};")
        if hasattr(self, 'action_label'):
            self.action_label.setStyleSheet(f"color: {c['text_color']};")
        if hasattr(self, 'separator1'):
            self.separator1.setStyleSheet(f"color: {c['border_color']};")
        if hasattr(self, 'separator2'):
            self.separator2.setStyleSheet(f"color: {c['border_color']};")
        self._setup_style()

    def _setup_ui(self) -> None:
        c = self._colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 预设布局
        self.preset_label = QLabel(self.tr("预设布局"))
        self.preset_label.setAlignment(Qt.AlignLeft)
        self.preset_label.setFont(QFont("", 9, QFont.Bold))
        self.preset_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.preset_label)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        presets = [
            ({'type': 'vertical_split', 'top_ratio': 0.6, 'bottom_split': True}, "上下分割+下分左右"),
            ({'type': 'horizontal_split', 'left_ratio': 0.6, 'right_split': True}, "左右分割+右分上下"),
            ({'type': 'triple_column_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'right_split': True}, "左右三等分+右边上下等分"),
            ({'type': 'triple_column_middle_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'middle_split': True, 'right_split': True}, "左右三等分+中间和右边上下等分"),
        ]
        for i, (config, name) in enumerate(presets):
            preset_btn = LayoutPresetButton(config, name)
            preset_btn.layout_selected.connect(self._on_preset_selected)
            preset_grid.addWidget(preset_btn, i // 4, i % 4)
        layout.addLayout(preset_grid)

        self.separator1 = QFrame()
        self.separator1.setFrameShape(QFrame.HLine)
        self.separator1.setFrameShadow(QFrame.Sunken)
        self.separator1.setStyleSheet(f"color: {c['border_color']};")
        layout.addWidget(self.separator1)

        self.dynamic_selector = DynamicLayoutSelector()
        self.dynamic_selector.layout_selected.connect(self._on_dynamic_selected)
        layout.addWidget(self.dynamic_selector)

        self.separator2 = QFrame()
        self.separator2.setFrameShape(QFrame.HLine)
        self.separator2.setFrameShadow(QFrame.Sunken)
        self.separator2.setStyleSheet(f"color: {c['border_color']};")
        layout.addWidget(self.separator2)

        self.action_label = QLabel(self.tr("序列操作"))
        self.action_label.setAlignment(Qt.AlignLeft)
        self.action_label.setFont(QFont("", 9, QFont.Bold))
        self.action_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.action_label)

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
        c = self._colors
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(f"""
            LayoutDropdown {{
                background-color: {c['bg_color']};
                border: 1px solid {c['border_color']};
                border-radius: 6px;
            }}
            QPushButton {{
                padding: 6px 12px;
                border: 1px solid {c['border_color']};
                border-radius: 4px;
                background-color: {self.adjust_color_brightness(c['bg_color'], -5)};
                color: {c['text_color']};
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color_brightness(c['highlight_color'], 40)};
                border-color: {c['highlight_color']};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color_brightness(c['highlight_color'], 20)};
            }}
        """)

    def _on_preset_selected(self, layout_config) -> None:
        logger.debug(f"选择预设布局: {layout_config}")
        self.layout_selected.emit(layout_config)
        self.hide()

    def _on_dynamic_selected(self, rows: int, cols: int) -> None:
        logger.debug(f"选择动态布局: {rows}x{cols}")
        self.layout_selected.emit((rows, cols))
        self.hide()

    def _on_auto_assign(self) -> None:
        logger.debug("请求自动分配")
        self.auto_assign_requested.emit()
        self.hide()

    def _on_clear_bindings(self) -> None:
        logger.debug("请求清除绑定")
        self.clear_bindings_requested.emit()
        self.hide()

    def show_at_position(self, global_pos: QPoint) -> None:
        if self._theme_manager is None:
            self._register_to_theme_manager()

        self.adjustSize()
        screen = QApplication.primaryScreen().geometry()
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


# ---------------------------------------------------------------------------
# LayoutSelectorButton
# ---------------------------------------------------------------------------
class LayoutSelectorButton(ThemeAwareMixin, QPushButton):
    """布局选择器按钮 - 点击时显示布局选择下拉菜单。"""

    layout_selected = Signal(object)
    auto_assign_requested = Signal()
    clear_bindings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LayoutSelectorButton")

        self._create_layout_icon()
        self.setToolTip(self.tr("选择视图布局"))

        self.dropdown = LayoutDropdown()
        self.dropdown.layout_selected.connect(self._on_layout_selected)
        self.dropdown.auto_assign_requested.connect(self.auto_assign_requested)
        self.dropdown.clear_bindings_requested.connect(self.clear_bindings_requested)
        self.clicked.connect(self._show_dropdown)

        self._register_to_theme_manager()

    def update_theme(self, theme_name: str) -> None:
        self._create_layout_icon()

    def _create_layout_icon(self) -> None:
        from medimager.utils.resource_path import get_icon_path
        svg_path = get_icon_path("layout.svg")
        try:
            if self._theme_manager:
                theme_data = self._theme_manager.get_theme_settings('ui')
            else:
                theme_data = get_theme_settings('ui')
            bg_color = theme_data.get('background_color', '#F0F0F0')
            icon_color = "#FFFFFF" if self.get_color_brightness(bg_color) < 128 else "#000000"

            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            svg_content = svg_content.replace('currentColor', icon_color)

            renderer = QSvgRenderer(QByteArray(svg_content.encode('utf-8')))
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            self.setIcon(QIcon(pixmap))
        except Exception as e:
            logger.warning(f"创建主题图标失败: {e}")
            self.setIcon(QIcon(svg_path))

        self.setText("")
        self.setFixedSize(32, 32)

    def _show_dropdown(self) -> None:
        global_pos = self.mapToGlobal(QPoint(0, self.height()))
        self.dropdown.show_at_position(global_pos)

    def _on_layout_selected(self, layout_config) -> None:
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            self.setToolTip(self.tr("当前布局: %1×%2").replace("%1", str(rows)).replace("%2", str(cols)))
        else:
            self.setToolTip(self.tr("当前布局: 特殊布局"))
        self.layout_selected.emit(layout_config)

    def set_current_layout(self, layout_config) -> None:
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            self.setToolTip(self.tr("当前布局: %1×%2").replace("%1", str(rows)).replace("%2", str(cols)))
        else:
            self.setToolTip(self.tr("当前布局: 特殊布局"))
