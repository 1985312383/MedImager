"""
面板切换条组件

在软件边缘显示一个细长的垂直条，中间有一个箭头按钮，
用于快速展开/收起侧边面板。
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF

from medimager.utils.logger import get_logger

logger = get_logger(__name__)


class PanelToggleStrip(QWidget):
    """面板切换条

    一个从上到下的细条，中间有一个箭头按钮，
    用于切换侧边面板的显示/隐藏。

    Args:
        side: 面板所在侧 'left' 或 'right'
        tooltip: 提示文本

    Signals:
        toggled (bool): 切换时发出，True 表示展开面板
    """

    toggled = Signal(bool)

    def __init__(self, side: str = 'right', tooltip: str = "", parent=None):
        super().__init__(parent)
        self._side = side  # 'left' 或 'right'
        self._panel_visible = True if side == 'left' else False
        self._theme_name = 'light'
        self._setup_ui(tooltip)
        self._apply_theme()
        self._register_to_theme_manager()

    def _setup_ui(self, tooltip: str):
        """设置UI"""
        self.setFixedWidth(16)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def set_panel_visible(self, visible: bool):
        """外部同步面板状态"""
        if self._panel_visible != visible:
            self._panel_visible = visible
            self.update()

    def mousePressEvent(self, event):
        """点击整个条都可以切换"""
        if event.button() == Qt.LeftButton:
            self._panel_visible = not self._panel_visible
            self.toggled.emit(self._panel_visible)
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        """绘制背景和箭头"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        # 主题颜色
        if self._theme_name == 'dark':
            bg = QColor("#3c3c3c")
            arrow_color = QColor("#cccccc")
            hover_bg = QColor("#4a4a4a")
        else:
            bg = QColor("#e8e8e8")
            arrow_color = QColor("#555555")
            hover_bg = QColor("#d0d0d0")

        under_mouse = self.underMouse()
        painter.fillRect(0, 0, w, h, hover_bg if under_mouse else bg)

        # 绘制分隔线
        pen = QPen(arrow_color, 1)
        painter.setPen(pen)
        if self._side == 'right':
            painter.drawLine(0, 0, 0, h)  # 左边缘
        else:
            painter.drawLine(w - 1, 0, w - 1, h)  # 右边缘

        # 绘制箭头（居中）
        arrow_size = 6
        cx = w // 2
        cy = h // 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(arrow_color)

        # 箭头方向逻辑：
        # 右侧面板: 展开时 > (收起), 收起时 < (展开)
        # 左侧面板: 展开时 < (收起), 收起时 > (展开)
        if self._side == 'right':
            point_right = self._panel_visible
        else:
            point_right = not self._panel_visible

        if point_right:
            # > 箭头
            points = [
                QPointF(cx - arrow_size // 2, cy - arrow_size),
                QPointF(cx + arrow_size // 2, cy),
                QPointF(cx - arrow_size // 2, cy + arrow_size),
            ]
        else:
            # < 箭头
            points = [
                QPointF(cx + arrow_size // 2, cy - arrow_size),
                QPointF(cx - arrow_size // 2, cy),
                QPointF(cx + arrow_size // 2, cy + arrow_size),
            ]

        painter.drawPolygon(QPolygonF(points))
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def update_theme(self, theme_name: str):
        """主题更新接口"""
        self._theme_name = theme_name
        self._apply_theme()
        self.update()

    def _apply_theme(self):
        pass

    def _register_to_theme_manager(self):
        """注册到主题管理器"""
        try:
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                theme_manager = main_window.theme_manager
                theme_manager.register_component(self)
                current_theme = theme_manager.get_current_theme()
                self.update_theme(current_theme)
        except Exception as e:
            logger.debug(f"[PanelToggleStrip._register_to_theme_manager] 注册失败: {e}")
