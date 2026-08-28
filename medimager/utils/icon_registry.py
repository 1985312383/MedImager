"""Semantic, high-DPI SVG icon registry.

The application keeps SVG sources in the package and resolves ``currentColor``
for every Qt icon mode.  This avoids raster assets, preserves sharp rendering
on mixed-DPI displays, and gives checked/selected/disabled controls distinct
visual states without requiring an icon-font runtime dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from medimager.utils.logger import get_logger
from medimager.utils.resource_path import get_icon_path

if TYPE_CHECKING:
    from medimager.utils.theme_manager import ThemeManager


logger = get_logger(__name__)


# Stable semantic names keep UI code independent from individual filenames.
ICON_FILES: Mapping[str, str] = {
    "pointer": "click.svg",
    "roi_ellipse": "ellipse.svg",
    "roi_rectangle": "rectangle.svg",
    "roi_circle": "circle.svg",
    "measure_length": "ruler.svg",
    "measure_angle": "angle.svg",
    "window_level": "contrast.svg",
    "transform": "transform.svg",
    "layout": "layout.svg",
    "sync": "chain.svg",
    "play": "play.svg",
    "pause": "pause.svg",
    "open_file": "file-open.svg",
    "open_folder": "folder-open.svg",
    "save": "save.svg",
    "export": "export.svg",
    "copy": "copy.svg",
    "undo": "undo.svg",
    "redo": "redo.svg",
    "fit": "fit.svg",
    "actual_size": "actual-size.svg",
    "zoom_in": "zoom-in.svg",
    "zoom_out": "zoom-out.svg",
    "pan": "pan.svg",
    "rotate_left": "rotate-left.svg",
    "rotate_right": "rotate-right.svg",
    "flip_horizontal": "flip-horizontal.svg",
    "flip_vertical": "flip-vertical.svg",
    "invert": "invert.svg",
    "reset": "reset.svg",
    "panel_left": "panel-left.svg",
    "panel_right": "panel-right.svg",
    "warning": "warning.svg",
    "retry": "retry.svg",
    "step_back": "step-back.svg",
    "step_forward": "step-forward.svg",
}


class SemanticSvgIconEngine(QIconEngine):
    """Render one SVG template with semantic colors for each Qt icon state."""

    def __init__(self, svg_template: str, colors: Mapping[str, str]):
        super().__init__()
        self._svg_template = str(svg_template)
        self._colors = dict(colors)

    def clone(self):
        return SemanticSvgIconEngine(self._svg_template, self._colors)

    def _color_for(self, mode: QIcon.Mode, state: QIcon.State) -> str:
        if mode == QIcon.Mode.Disabled:
            return self._colors["disabled"]
        if state == QIcon.State.On or mode == QIcon.Mode.Selected:
            return self._colors["selected"]
        if mode == QIcon.Mode.Active:
            return self._colors["active"]
        return self._colors["normal"]

    def _renderer(self, mode: QIcon.Mode, state: QIcon.State) -> QSvgRenderer:
        color = self._color_for(mode, state)
        data = self._svg_template.replace("currentColor", color).encode("utf-8")
        return QSvgRenderer(QByteArray(data))

    def paint(self, painter, rect, mode, state):
        self._renderer(mode, state).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        return self._render_pixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        return self._render_pixmap(size, mode, state, scale)

    def _render_pixmap(
        self,
        size: QSize,
        mode: QIcon.Mode,
        state: QIcon.State,
        scale: float,
    ) -> QPixmap:
        scale = max(1.0, float(scale))
        physical_size = QSize(
            max(1, round(size.width() * scale)),
            max(1, round(size.height() * scale)),
        )
        pixmap = QPixmap(physical_size)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self._renderer(mode, state).render(
            painter, QRectF(0, 0, size.width(), size.height())
        )
        painter.end()
        return pixmap


class IconRegistry:
    """Resolve semantic icon names and create theme-aware vector ``QIcon``s."""

    def __init__(self, theme_manager: "ThemeManager") -> None:
        self._theme_manager = theme_manager

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(ICON_FILES))

    def path(self, name: str) -> str:
        try:
            filename = ICON_FILES[name]
        except KeyError as error:
            raise KeyError(f"Unknown icon name: {name}") from error
        return get_icon_path(filename)

    def icon(self, name: str) -> QIcon:
        return self.icon_from_path(self.path(name))

    def icon_from_path(self, svg_path: str | Path) -> QIcon:
        path = Path(svg_path)
        try:
            svg_template = path.read_text(encoding="utf-8")
            if "currentColor" not in svg_template:
                raise ValueError("SVG must use currentColor")
            probe = QSvgRenderer(QByteArray(svg_template.encode("utf-8")))
            if not probe.isValid():
                raise ValueError("invalid SVG")
            return QIcon(SemanticSvgIconEngine(svg_template, self._mode_colors()))
        except Exception as error:
            logger.warning("Unable to create semantic icon %s: %s", path, error)
            return QIcon(str(path))

    def _mode_colors(self) -> dict[str, str]:
        tokens = self._theme_manager.get_theme_tokens()
        return {
            "normal": tokens["icon_color"],
            "active": tokens["icon_active_color"],
            "selected": tokens["icon_selected_color"],
            "disabled": tokens["text_disabled_color"],
        }

    def validate_resources(self) -> list[str]:
        """Return human-readable resource errors; an empty list means valid."""
        errors: list[str] = []
        for name, filename in ICON_FILES.items():
            path = Path(get_icon_path(filename))
            if not path.is_file():
                errors.append(f"{name}: missing {filename}")
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as error:
                errors.append(f"{name}: {error}")
                continue
            if "currentColor" not in content:
                errors.append(f"{name}: does not use currentColor")
            if not QSvgRenderer(QByteArray(content.encode("utf-8"))).isValid():
                errors.append(f"{name}: invalid SVG")
        return errors
