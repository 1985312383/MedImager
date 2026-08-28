"""
布局网格选择器组件

提供简约的布局选择功能，包含预设布局和动态调整。
"""

from typing import Optional
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QApplication, QGridLayout)
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QByteArray
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QKeyEvent, QMouseEvent, QPaintEvent, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer

from medimager.utils.logger import get_logger
from medimager.utils.theme_manager import ThemeAwareMixin, get_theme_settings
from medimager.utils.i18n import t

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
        label = t(layout_name)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setAccessibleDescription(label)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

        self.title_label = QLabel(t("dynamiclayoutselector.custom_grid"))
        self.title_label.setAlignment(Qt.AlignLeft)
        self.title_label.setFont(QFont("", 9, QFont.Bold))
        self.title_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.title_label)

        self.grid_widget = QWidget()
        self.grid_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grid_widget.setAccessibleName(t("dynamiclayoutselector.custom_grid"))
        self.grid_widget.setAccessibleDescription(t("dynamiclayoutselector.one_by_one_grid"))
        grid_width = self.max_cols * (self.cell_size + self.cell_spacing) - self.cell_spacing
        grid_height = self.max_rows * (self.cell_size + self.cell_spacing) - self.cell_spacing
        self.grid_widget.setFixedSize(grid_width, grid_height)
        self.grid_widget.setMouseTracking(True)
        layout.addWidget(self.grid_widget, 0, Qt.AlignCenter)

        self.selection_label = QLabel(t("dynamiclayoutselector.one_by_one_grid"))
        self.selection_label.setAlignment(Qt.AlignCenter)
        self.selection_label.setFont(QFont("", 8))
        self.selection_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.selection_label)

        self.grid_widget.mouseMoveEvent = self._on_mouse_move
        self.grid_widget.mousePressEvent = self._on_mouse_press
        self.grid_widget.leaveEvent = self._on_mouse_leave
        self.grid_widget.keyPressEvent = self._on_key_press
        self.grid_widget.focusInEvent = self._on_grid_focus_in
        self.grid_widget.focusOutEvent = self._on_grid_focus_out
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
        if self.grid_widget.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c.get('focus_color', c['highlight_color'])), 2))
            painter.drawRect(self.grid_widget.rect().adjusted(1, 1, -2, -2))
        painter.end()

    def _set_grid_selection(self, rows: int, cols: int) -> None:
        rows = max(1, min(int(rows), self.max_rows))
        cols = max(1, min(int(cols), self.max_cols))
        self.hovered_rows = rows
        self.hovered_cols = cols
        label = t("dynamiclayoutselector.grid_size").replace("%1", str(rows)).replace("%2", str(cols))
        self.selection_label.setText(label)
        self.grid_widget.setAccessibleDescription(label)
        self.grid_widget.update()

    def _on_mouse_move(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        col = max(1, min(int(pos.x() // (self.cell_size + self.cell_spacing)) + 1, self.max_cols))
        row = max(1, min(int(pos.y() // (self.cell_size + self.cell_spacing)) + 1, self.max_rows))
        if self.hovered_rows != row or self.hovered_cols != col:
            self._set_grid_selection(row, col)

    def _on_mouse_press(self, event: QMouseEvent) -> None:
        self.grid_widget.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.LeftButton and self.hovered_rows > 0 and self.hovered_cols > 0:
            logger.debug(f"选择动态布局: {self.hovered_rows}x{self.hovered_cols}")
            self.layout_selected.emit(self.hovered_rows, self.hovered_cols)

    def _on_key_press(self, event: QKeyEvent) -> None:
        rows = self.hovered_rows or 1
        cols = self.hovered_cols or 1
        key = event.key()
        if key == Qt.Key.Key_Left:
            cols -= 1
        elif key == Qt.Key.Key_Right:
            cols += 1
        elif key == Qt.Key.Key_Up:
            rows -= 1
        elif key == Qt.Key.Key_Down:
            rows += 1
        elif key == Qt.Key.Key_Home:
            rows, cols = 1, 1
        elif key == Qt.Key.Key_End:
            rows, cols = self.max_rows, self.max_cols
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.layout_selected.emit(rows, cols)
            event.accept()
            return
        else:
            event.ignore()
            return
        self._set_grid_selection(rows, cols)
        event.accept()

    def _on_grid_focus_in(self, event) -> None:
        if self.hovered_rows == 0 or self.hovered_cols == 0:
            self._set_grid_selection(1, 1)
        self.grid_widget.update()
        QWidget.focusInEvent(self.grid_widget, event)

    def _on_grid_focus_out(self, event) -> None:
        self.grid_widget.update()
        QWidget.focusOutEvent(self.grid_widget, event)

    def _on_mouse_leave(self, event) -> None:
        if not self.grid_widget.hasFocus():
            self.hovered_rows = 0
            self.hovered_cols = 0
            self.selection_label.setText(t("dynamiclayoutselector.one_by_one_grid"))
            self.grid_widget.setAccessibleDescription(self.selection_label.text())
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
        self._preset_buttons = []
        self._action_buttons = []
        parent_theme_manager = None
        if parent is not None and hasattr(parent, 'theme_manager'):
            parent_theme_manager = parent.theme_manager
            self._theme_manager = parent_theme_manager
        self._colors = _load_ui_colors(self._theme_manager)
        self._setup_ui()
        self._setup_style()
        if parent_theme_manager is not None:
            parent_theme_manager.register_component(self)
        else:
            self._register_to_theme_manager()

    def update_theme(self, theme_name: str) -> None:
        self._colors = _load_ui_colors(self._theme_manager)
        self._update_styles()
        for button in getattr(self, '_preset_buttons', []):
            button._theme_manager = self._theme_manager
            button.update_theme(theme_name)
        if hasattr(self, 'dynamic_selector'):
            self.dynamic_selector._theme_manager = self._theme_manager
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
        for button in getattr(self, '_action_buttons', []):
            button.setStyleSheet("")
        self._setup_style()

    def _setup_ui(self) -> None:
        c = self._colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 预设布局
        self.preset_label = QLabel(t("layoutdropdown.preset_layout"))
        self.preset_label.setAlignment(Qt.AlignLeft)
        self.preset_label.setFont(QFont("", 9, QFont.Bold))
        self.preset_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.preset_label)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        presets = [
            ({'type': 'vertical_split', 'top_ratio': 0.6, 'bottom_split': True}, "layoutpreset.vertical_split_bottom_split"),
            ({'type': 'horizontal_split', 'left_ratio': 0.6, 'right_split': True}, "layoutpreset.horizontal_split_right_split"),
            ({'type': 'triple_column_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'right_split': True}, "layoutpreset.triple_column_right_split"),
            ({'type': 'triple_column_middle_right_split', 'left_ratio': 0.33, 'middle_ratio': 0.34, 'middle_split': True, 'right_split': True}, "layoutpreset.triple_column_middle_right_split"),
        ]
        for i, (config, label_key) in enumerate(presets):
            preset_btn = LayoutPresetButton(config, label_key)
            self._preset_buttons.append(preset_btn)
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

        self.action_label = QLabel(t("layoutdropdown.sequence_operations"))
        self.action_label.setAlignment(Qt.AlignLeft)
        self.action_label.setFont(QFont("", 9, QFont.Bold))
        self.action_label.setStyleSheet(f"color: {c['text_color']};")
        layout.addWidget(self.action_label)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        auto_assign_btn = QPushButton(t("layoutdropdown.automatic_assignment"))
        auto_assign_btn.setToolTip(t("layoutdropdown.automatically_assign_sequences_to_available_views"))
        auto_assign_btn.clicked.connect(self._on_auto_assign)
        self._action_buttons.append(auto_assign_btn)
        action_layout.addWidget(auto_assign_btn)
        clear_bindings_btn = QPushButton(t("layoutdropdown.clear_bindings"))
        clear_bindings_btn.setToolTip(t("layoutdropdown.clear_all_sequence_bindings"))
        clear_bindings_btn.clicked.connect(self._on_clear_bindings)
        self._action_buttons.append(clear_bindings_btn)
        action_layout.addWidget(clear_bindings_btn)
        layout.addLayout(action_layout)

    def _setup_style(self) -> None:
        c = self._colors
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        self.setAccessibleName(t("mainwindow.select_view_layout"))
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
        if self._theme_manager is not None:
            self.update_theme(self._theme_manager.get_current_theme())

        self.adjustSize()
        target_screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        screen = target_screen.availableGeometry()
        x = global_pos.x()
        y = global_pos.y()
        if x + self.width() > screen.right() + 1:
            x = screen.right() + 1 - self.width()
        if y + self.height() > screen.bottom() + 1:
            y = global_pos.y() - self.height()
        x = max(screen.left(), x)
        y = max(screen.top(), y)
        self.move(x, y)
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
        self.setAccessibleName(t("mainwindow.select_view_layout"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._create_layout_icon()
        self.setToolTip(t("layoutselectorbutton.select_view_layout"))

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
            self.setToolTip(t("layoutselectorbutton.current_layout_size").replace("%1", str(rows)).replace("%2", str(cols)))
        else:
            self.setToolTip(t("layoutselectorbutton.current_layout_special_layout"))
        self.layout_selected.emit(layout_config)

    def set_current_layout(self, layout_config) -> None:
        if isinstance(layout_config, tuple) and len(layout_config) == 2:
            rows, cols = layout_config
            self.setToolTip(t("layoutselectorbutton.current_layout_size").replace("%1", str(rows)).replace("%2", str(cols)))
        else:
            self.setToolTip(t("layoutselectorbutton.current_layout_special_layout"))
