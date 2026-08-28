"""Keyboard-accessible side-panel toggle strip."""

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from medimager.utils.logger import get_logger
from medimager.utils.theme_manager import get_theme_settings, normalize_ui_theme


logger = get_logger(__name__)


class PanelToggleStrip(QWidget):
    """A 28 px edge target that expands or collapses a side panel."""

    toggled = Signal(bool)

    def __init__(self, side: str = "right", tooltip: str = "", parent=None):
        super().__init__(parent)
        if side not in {"left", "right"}:
            raise ValueError("side must be 'left' or 'right'")
        self._side = side
        self._panel_visible = side == "left"
        self._theme_name = "light"
        self._theme_tokens = normalize_ui_theme(
            get_theme_settings("ui", self._theme_name)
        )
        self._setup_ui(tooltip)
        self._register_to_theme_manager()

    def _setup_ui(self, tooltip: str) -> None:
        self.setFixedWidth(28)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        accessible_name = tooltip or "Toggle side panel"
        self.setAccessibleName(accessible_name)
        self.setAccessibleDescription(accessible_name)
        if tooltip:
            self.setToolTip(tooltip)
        self.setProperty("panelVisible", self._panel_visible)

    def sizeHint(self) -> QSize:
        return QSize(28, 96)

    def set_panel_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._panel_visible == visible:
            return
        self._panel_visible = visible
        self.setProperty("panelVisible", visible)
        self.update()

    def _toggle(self) -> None:
        self._panel_visible = not self._panel_visible
        self.setProperty("panelVisible", self._panel_visible)
        self.toggled.emit(self._panel_visible)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width(), self.height()
        tokens = self._theme_tokens
        background = QColor(tokens["surface_color"])
        hover_background = QColor(tokens["surface_raised_color"])
        arrow_color = QColor(tokens["text_secondary_color"])
        painter.fillRect(
            0,
            0,
            width,
            height,
            hover_background if self.underMouse() or self.hasFocus() else background,
        )

        painter.setPen(QPen(QColor(tokens["border_color"]), 1))
        edge_x = 0 if self._side == "right" else width - 1
        painter.drawLine(edge_x, 0, edge_x, height)

        arrow_size = 6
        center_x = width // 2
        center_y = height // 2
        point_right = (
            self._panel_visible if self._side == "right" else not self._panel_visible
        )
        if point_right:
            points = [
                QPointF(center_x - arrow_size // 2, center_y - arrow_size),
                QPointF(center_x + arrow_size // 2, center_y),
                QPointF(center_x - arrow_size // 2, center_y + arrow_size),
            ]
        else:
            points = [
                QPointF(center_x + arrow_size // 2, center_y - arrow_size),
                QPointF(center_x - arrow_size // 2, center_y),
                QPointF(center_x + arrow_size // 2, center_y + arrow_size),
            ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(arrow_color)
        painter.drawPolygon(QPolygonF(points))

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens["focus_color"]), 2))
            painter.drawRect(1, 1, width - 3, height - 3)
        painter.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def update_theme(self, theme_name: str) -> None:
        self._theme_name = theme_name
        if hasattr(self.window(), "theme_manager"):
            self._theme_tokens = self.window().theme_manager.get_theme_tokens(theme_name)
        else:
            self._theme_tokens = normalize_ui_theme(get_theme_settings("ui", theme_name))
        self.update()

    def _register_to_theme_manager(self) -> None:
        try:
            main_window = self.window()
            if hasattr(main_window, "theme_manager"):
                theme_manager = main_window.theme_manager
                theme_manager.register_component(self)
                self._theme_tokens = theme_manager.get_theme_tokens()
                self.update()
        except Exception as error:
            logger.debug("PanelToggleStrip theme registration failed: %s", error)
