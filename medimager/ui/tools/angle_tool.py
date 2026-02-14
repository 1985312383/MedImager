# 角度测量工具
from medimager.ui.tools.base_tool import BaseTool, point_distance
from medimager.core.image_data_model import AngleMeasurementData
from medimager.utils.logger import get_logger
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QKeyEvent, QPen, QColor, QFont, QBrush
from PySide6.QtCore import Qt, QPointF, QRectF
import math
import uuid


class AngleTool(BaseTool):
    """角度测量工具，通过三次点击测量两条线段的夹角。"""

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.logger = get_logger(__name__)
        self._points: list[QPointF] = []
        self._preview_point: QPointF | None = None

    def _get_style_from_settings(self):
        """从设置中获取测量工具的样式"""
        try:
            from medimager.utils.theme_manager import get_theme_settings
            theme_data = get_theme_settings('measurement')
            return (
                theme_data.get('line_color', "#00FF00"),
                theme_data.get('anchor_color', "#00FF00"),
                theme_data.get('text_color', "#FFFFFF"),
                theme_data.get('background_color', "#00000080"),
                theme_data.get('line_width', 2),
                theme_data.get('anchor_size', 8),
                theme_data.get('font_size', 14),
            )
        except Exception:
            return ("#00FF00", "#00FF00", "#FFFFFF", "#00000080", 2, 8, 14)

    def activate(self):
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        self._points.clear()
        self._preview_point = None
        self.viewer.setCursor(Qt.ArrowCursor)
        self.viewer.viewport().update()

    def mouse_press_event(self, event: QMouseEvent):
        super().mouse_press_event(event)
        if self._press_is_outside:
            return

        if event.button() == Qt.LeftButton:
            model = self.viewer.model
            if not model:
                return
            pos = self.viewer.last_mouse_scene_pos
            self._points.append(pos)
            if len(self._points) == 3:
                self._complete_angle()
            self.viewer.viewport().update()
            event.accept()

        elif event.button() == Qt.RightButton:
            self._points.clear()
            self._preview_point = None
            self.viewer.viewport().update()
            event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        super().mouse_move_event(event)
        if 0 < len(self._points) < 3:
            self._preview_point = self.viewer.last_mouse_scene_pos
            self.viewer.viewport().update()
            event.accept()

    def key_press_event(self, event: QKeyEvent):
        super().key_press_event(event)
        if event.key() == Qt.Key_Escape:
            self._points.clear()
            self._preview_point = None
            self.viewer.viewport().update()
            event.accept()
        elif event.key() == Qt.Key_Delete:
            model = self.viewer.model
            if model and model.angle_measurements:
                model.angle_measurements.pop()
                model.data_changed.emit()
                self.viewer.viewport().update()
                event.accept()

    def _complete_angle(self):
        model = self.viewer.model
        if not model:
            return
        p1, vertex, p3 = self._points
        angle = self._calculate_angle(p1, vertex, p3)
        data = AngleMeasurementData(
            id=str(uuid.uuid4()),
            slice_index=model.current_slice_index,
            point1=p1,
            vertex=vertex,
            point3=p3,
            angle_degrees=angle,
        )
        model.add_angle_measurement(data)
        self._points.clear()
        self._preview_point = None

    @staticmethod
    def _calculate_angle(p1: QPointF, vertex: QPointF, p3: QPointF) -> float:
        v1x, v1y = p1.x() - vertex.x(), p1.y() - vertex.y()
        v2x, v2y = p3.x() - vertex.x(), p3.y() - vertex.y()
        dot = v1x * v2x + v1y * v2y
        mag1 = math.sqrt(v1x ** 2 + v1y ** 2)
        mag2 = math.sqrt(v2x ** 2 + v2y ** 2)
        if mag1 == 0 or mag2 == 0:
            return 0.0
        cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
        return math.degrees(math.acos(cos_angle))

    def draw_temporary_shape(self, painter):
        """绘制正在创建中的角度测量预览"""
        if not self._points:
            return

        line_color, anchor_color, text_color, bg_color, line_width, anchor_size, font_size = self._get_style_from_settings()

        painter.save()

        pen = QPen(QColor(line_color), line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        pixel_size = 1.0 / self.viewer.transform().m11()
        scaled_anchor = anchor_size * pixel_size

        # 绘制已确定的点
        painter.setBrush(QColor(anchor_color))
        painter.setPen(Qt.NoPen)
        for pt in self._points:
            painter.drawEllipse(pt, scaled_anchor / 2, scaled_anchor / 2)

        preview = self._preview_point
        if preview:
            painter.drawEllipse(preview, scaled_anchor / 2, scaled_anchor / 2)

        # 绘制线段
        pen = QPen(QColor(line_color), line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        pts = list(self._points) + ([preview] if preview else [])

        if len(pts) >= 2:
            # 第一条线：pts[0] -> pts[1] (vertex)
            painter.drawLine(pts[0], pts[1])
        if len(pts) >= 3:
            # 第二条线：pts[1] (vertex) -> pts[2]
            painter.drawLine(pts[1], pts[2])

            # 计算并显示角度
            angle = self._calculate_angle(pts[0], pts[1], pts[2])
            self._draw_angle_arc_and_text(painter, pts[0], pts[1], pts[2], angle,
                                          line_color, text_color, bg_color,
                                          line_width, font_size, pixel_size)

        painter.restore()

    @staticmethod
    def _draw_angle_arc_and_text(painter, p1, vertex, p3, angle,
                                  line_color, text_color, bg_color,
                                  line_width, font_size, pixel_size):
        """绘制角度弧线和文字"""
        # 弧线半径（场景坐标）
        arc_radius = 25 * pixel_size

        # 计算两条射线的角度
        angle1 = math.degrees(math.atan2(-(p1.y() - vertex.y()), p1.x() - vertex.x()))
        angle2 = math.degrees(math.atan2(-(p3.y() - vertex.y()), p3.x() - vertex.x()))

        start_angle = angle2
        span = angle1 - angle2
        # 确保弧线走短弧
        if span > 180:
            span -= 360
        elif span < -180:
            span += 360

        pen = QPen(QColor(line_color), line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        arc_rect = QRectF(
            vertex.x() - arc_radius, vertex.y() - arc_radius,
            arc_radius * 2, arc_radius * 2
        )
        # Qt drawArc 使用 1/16 度
        painter.drawArc(arc_rect, int(start_angle * 16), int(span * 16))

        # 角度文字
        mid_angle_rad = math.radians(start_angle + span / 2)
        text_radius = arc_radius * 1.8
        text_x = vertex.x() + text_radius * math.cos(mid_angle_rad)
        text_y = vertex.y() - text_radius * math.sin(mid_angle_rad)

        text = f"{angle:.1f}°"
        font = QFont()
        font.setPixelSize(font_size)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(text).adjusted(-4, -2, 4, 2)
        text_rect.moveCenter(QPointF(text_x, text_y).toPoint())

        painter.setBrush(QColor(bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(text_rect, 5, 5)

        painter.setPen(QColor(text_color))
        painter.drawText(text_rect, Qt.AlignCenter, text)
