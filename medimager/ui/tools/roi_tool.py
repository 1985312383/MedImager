import math
from abc import abstractmethod
from medimager.ui.tools.base_tool import BaseTool
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QPen, QColor

from PySide6.QtCore import Qt, QPointF, QRectF, QRect

from medimager.core.roi import EllipseROI, CircleROI, RectangleROI, BaseROI
from medimager.core.analysis import calculate_roi_statistics
from medimager.ui.widgets.roi_stats_box import get_stats_text, calculate_stats_box_size_rect, _get_stats_box_settings


class BaseROITool(BaseTool):
    """ROI 绘制工具的公共基类。

    提供拖拽绘制、Delete 键删除选中 ROI、统计信息框定位等通用逻辑。
    子类只需实现 ``_create_roi`` 和 ``draw_temporary_shape``。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.is_drawing = False
        self.start_point: QPointF = QPointF()
        self.end_point: QPointF = QPointF()

    # ------------------------------------------------------------------
    # 通用生命周期
    # ------------------------------------------------------------------
    def activate(self):
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        self.is_drawing = False
        self.viewer.scene.update()
        self.viewer.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------
    # 通用鼠标事件
    # ------------------------------------------------------------------
    def mouse_press_event(self, event: QMouseEvent):
        super().mouse_press_event(event)
        if self._press_is_outside:
            return
        if event.button() == Qt.LeftButton:
            self.is_drawing = True
            self.start_point = self.viewer.last_mouse_scene_pos
            self.end_point = self.start_point
            event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        super().mouse_move_event(event)
        if self.is_drawing:
            self.end_point = self.viewer.last_mouse_scene_pos
            self.viewer.scene.update()
            event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        super().mouse_release_event(event)
        if self.is_drawing and event.button() == Qt.LeftButton:
            self.is_drawing = False
            self.end_point = self.viewer.last_mouse_scene_pos

            model = self.viewer.model
            if model and model.has_image():
                rect = QRectF(self.start_point, self.end_point).normalized()
                if rect.width() > 1 and rect.height() > 1:
                    roi = self._create_roi(rect, model.current_slice_index)
                    if roi is not None:
                        model.add_roi(roi)
                        self._place_stats_box(roi)

            self.viewer.scene.update()
            event.accept()

    # ------------------------------------------------------------------
    # 通用键盘事件 — Delete 删除选中 ROI
    # ------------------------------------------------------------------
    def key_press_event(self, event):
        if event.key() == Qt.Key_Delete:
            model = self.viewer.model
            if model and model.selected_indices:
                deleted_roi_ids = model.delete_selected_rois()
                for roi_id in deleted_roi_ids:
                    if roi_id in self.viewer.stats_box_positions:
                        del self.viewer.stats_box_positions[roi_id]
                self.viewer.scene.update()
                event.accept()
                return
        super().key_press_event(event)

    # ------------------------------------------------------------------
    # 统计信息框定位（通用）
    # ------------------------------------------------------------------
    def _get_roi_half_extent_x(self, roi: BaseROI) -> int:
        """返回 ROI 在 X 方向上从中心到边缘的半宽（像素）。"""
        if isinstance(roi, EllipseROI):
            return roi.radius_x
        elif isinstance(roi, CircleROI):
            return roi.radius
        elif isinstance(roi, RectangleROI):
            return roi.width // 2
        return 0

    def _place_stats_box(self, roi: BaseROI):
        """计算统计信息框位置并存储到 viewer.stats_box_positions。"""
        viewer = self.viewer
        if not viewer.model:
            return

        stats = calculate_roi_statistics(viewer.model, roi)
        if not stats:
            return

        font = viewer.font()
        font.setPointSize(_get_stats_box_settings()['font_size'])
        stats_text = get_stats_text(stats)
        size_rect = calculate_stats_box_size_rect(stats_text, font)
        box_width = size_rect.width()
        box_height = size_rect.height()

        roi_center_scene = QPointF(roi.center[1], roi.center[0])
        half_x = self._get_roi_half_extent_x(roi)

        initial_x = roi_center_scene.x() + half_x + 10
        initial_y = roi_center_scene.y() - box_height / 2
        stats_box_rect = QRect(int(initial_x), int(initial_y), int(box_width), int(box_height))

        view_rect_scene = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        if stats_box_rect.right() > view_rect_scene.right():
            initial_x = roi_center_scene.x() - half_x - 10 - box_width
            stats_box_rect.moveLeft(int(initial_x))

        viewer.stats_box_positions[roi.id] = stats_box_rect

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------
    @abstractmethod
    def _create_roi(self, rect: QRectF, slice_index: int) -> BaseROI | None:
        """根据拖拽矩形创建具体的 ROI 实例。"""
        ...

    @abstractmethod
    def draw_temporary_shape(self, painter):
        """由 ImageViewer 调用，绘制拖拽过程中的临时形状。"""
        ...


# ---------------------------------------------------------------------------
# 具体工具
# ---------------------------------------------------------------------------
class EllipseROITool(BaseROITool):
    """通过拖拽绘制椭圆 ROI。"""

    def _create_roi(self, rect: QRectF, slice_index: int) -> EllipseROI:
        return EllipseROI(
            center=(int(rect.center().y()), int(rect.center().x())),
            radius_y=int(rect.height() / 2),
            radius_x=int(rect.width() / 2),
            slice_index=slice_index,
        )

    def draw_temporary_shape(self, painter):
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(self.start_point, self.end_point))


class RectangleROITool(BaseROITool):
    """通过拖拽绘制矩形 ROI。"""

    def _create_roi(self, rect: QRectF, slice_index: int) -> RectangleROI:
        return RectangleROI(
            top_left=(int(rect.top()), int(rect.left())),
            bottom_right=(int(rect.bottom()), int(rect.right())),
            slice_index=slice_index,
        )

    def draw_temporary_shape(self, painter):
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(self.start_point, self.end_point))


class CircleROITool(BaseROITool):
    """通过拖拽绘制圆形 ROI。"""

    def _create_roi(self, rect: QRectF, slice_index: int) -> CircleROI:
        radius = int(min(rect.width(), rect.height()) / 2)
        return CircleROI(
            center=(int(rect.center().y()), int(rect.center().x())),
            radius=radius,
            slice_index=slice_index,
        )

    def draw_temporary_shape(self, painter):
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            rect = QRectF(self.start_point, self.end_point)
            size = min(rect.width(), rect.height())
            circle_rect = QRectF(
                rect.center().x() - size / 2,
                rect.center().y() - size / 2,
                size, size,
            )
            painter.drawEllipse(circle_rect)
