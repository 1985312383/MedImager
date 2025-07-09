import math
from medimager.ui.tools.base_tool import BaseTool
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QCursor, QPen, QColor, QFontMetrics

from PySide6.QtCore import Qt, QPointF, QRectF, QSizeF, QRect

from medimager.core.roi import EllipseROI, CircleROI, RectangleROI
from medimager.core.analysis import calculate_roi_statistics
from medimager.ui.widgets.roi_stats_box import get_stats_text, calculate_stats_box_size_rect, _get_stats_box_settings

class EllipseROITool(BaseTool):
    """
    用于通过拖拽绘制椭圆ROI的工具。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.is_drawing = False
        self.start_point: QPointF = QPointF()
        self.end_point: QPointF = QPointF()

    def activate(self):
        """激活工具，设置十字准星光标。"""
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        """停用工具，恢复默认光标。"""
        self.is_drawing = False
        # 请求重绘以清除任何临时形状
        self.viewer.scene.update()
        self.viewer.setCursor(Qt.ArrowCursor)

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，开始绘制ROI。"""
        super().mouse_press_event(event)
        if self._press_is_outside:
            return

        if event.button() == Qt.LeftButton:
            self.is_drawing = True
            self.start_point = self.viewer.last_mouse_scene_pos # 使用安全坐标
            self.end_point = self.start_point
            event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件，更新ROI预览。"""
        # 调用基类方法处理通用功能，它会更新 last_mouse_scene_pos
        super().mouse_move_event(event)
        
        if self.is_drawing:
            # 直接使用由基类计算并限制在图像边界内的安全坐标
            self.end_point = self.viewer.last_mouse_scene_pos
            # 触发ImageViewer的重绘以显示临时形状
            self.viewer.scene.update()
            event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件，完成ROI绘制。"""
        # 调用基类方法来更新通用状态
        super().mouse_release_event(event)

        if self.is_drawing and event.button() == Qt.LeftButton:
            self.is_drawing = False
            # 最终点也使用限制在边界内的安全坐标
            self.end_point = self.viewer.last_mouse_scene_pos
            
            model = self.viewer.model
            if model and model.has_image():
                rect = QRectF(self.start_point, self.end_point).normalized()
                
                if rect.width() > 1 and rect.height() > 1:
                    current_slice_index = model.current_slice_index
                    roi = EllipseROI(
                        center=(int(rect.center().y()), int(rect.center().x())), 
                        radius_y=int(rect.height() / 2),
                        radius_x=int(rect.width() / 2),
                        slice_index=current_slice_index
                    )
                    model.add_roi(roi)
                    self._calculate_and_store_stats_box_rect(roi)
            
            self.viewer.scene.update()
            event.accept()

    def _calculate_and_store_stats_box_rect(self, roi: EllipseROI):
        """计算统计信息框的智能位置和大小，并存储。"""
        viewer = self.viewer
        if not viewer.model:
            return

        stats = calculate_roi_statistics(viewer.model, roi)
        if not stats:
            return

        # 使用新的 roi_stats_box 模块来计算大小
        font = viewer.font()
        font.setPointSize(_get_stats_box_settings()['font_size'])
        stats_text = get_stats_text(stats)
        size_rect = calculate_stats_box_size_rect(stats_text, font)
        box_width = size_rect.width()
        box_height = size_rect.height()

        # 计算初始位置（在ROI的右侧）
        # 注意: roi.center是(y,x), roi.radius_x和roi.radius_y是像素单位
        # 我们需要在场景坐标系中进行计算
        roi_center_scene = QPointF(roi.center[1], roi.center[0])
        
        # 尝试放在右边
        initial_x = roi_center_scene.x() + roi.radius_x + 10
        initial_y = roi_center_scene.y() - box_height / 2
        
        # 创建矩形并存储
        stats_box_rect = QRect(int(initial_x), int(initial_y), int(box_width), int(box_height))

        # 检查是否超出右边界
        view_rect_scene = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        if stats_box_rect.right() > view_rect_scene.right():
            # 如果超出，放到左边
            initial_x = roi_center_scene.x() - roi.radius_x - 10 - box_width
            stats_box_rect.moveLeft(int(initial_x))

        viewer.stats_box_positions[roi.id] = stats_box_rect

    def draw_temporary_shape(self, painter):
        """由ImageViewer调用，用于在绘制过程中显示临时形状。"""
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            
            rect = QRectF(self.start_point, self.end_point)
            painter.drawEllipse(rect)

    def wheelEvent(self, event: QWheelEvent) -> bool:
        """不处理滚轮事件，让上一级处理（例如切片）"""
        return False


class RectangleROITool(BaseTool):
    """
    用于通过拖拽绘制矩形ROI的工具。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.is_drawing = False
        self.start_point: QPointF = QPointF()
        self.end_point: QPointF = QPointF()

    def activate(self):
        """激活工具，设置十字准星光标。"""
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        """停用工具，恢复默认光标。"""
        self.is_drawing = False
        self.viewer.scene.update()
        self.viewer.setCursor(Qt.ArrowCursor)

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，开始绘制ROI。"""
        super().mouse_press_event(event)
        if self._press_is_outside:
            return

        if event.button() == Qt.LeftButton:
            self.is_drawing = True
            self.start_point = self.viewer.last_mouse_scene_pos
            self.end_point = self.start_point
            event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件，更新ROI预览。"""
        super().mouse_move_event(event)
        
        if self.is_drawing:
            self.end_point = self.viewer.last_mouse_scene_pos
            self.viewer.scene.update()
            event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件，完成ROI绘制。"""
        super().mouse_release_event(event)

        if self.is_drawing and event.button() == Qt.LeftButton:
            self.is_drawing = False
            self.end_point = self.viewer.last_mouse_scene_pos
            
            model = self.viewer.model
            if model and model.has_image():
                rect = QRectF(self.start_point, self.end_point).normalized()
                
                if rect.width() > 1 and rect.height() > 1:
                    current_slice_index = model.current_slice_index
                    roi = RectangleROI(
                        top_left=(int(rect.top()), int(rect.left())),
                        bottom_right=(int(rect.bottom()), int(rect.right())),
                        slice_index=current_slice_index
                    )
                    model.add_roi(roi)
                    self._calculate_and_store_stats_box_rect(roi)
            
            self.viewer.scene.update()
            event.accept()

    def _calculate_and_store_stats_box_rect(self, roi: RectangleROI):
        """计算统计信息框的智能位置和大小，并存储。"""
        viewer = self.viewer
        if not viewer.model:
            return

        stats = calculate_roi_statistics(viewer.model, roi)
        if not stats:
            return

        font = viewer.font()
        font.setPointSize(FONT_SIZE)
        stats_text = get_stats_text(stats)
        size_rect = calculate_stats_box_size_rect(stats_text, font)
        box_width = size_rect.width()
        box_height = size_rect.height()

        # 计算初始位置（在ROI的右侧）
        roi_center_scene = QPointF(roi.center[1], roi.center[0])
        
        initial_x = roi_center_scene.x() + roi.width // 2 + 10
        initial_y = roi_center_scene.y() - box_height / 2
        
        stats_box_rect = QRect(int(initial_x), int(initial_y), int(box_width), int(box_height))

        # 检查是否超出右边界
        view_rect_scene = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        if stats_box_rect.right() > view_rect_scene.right():
            initial_x = roi_center_scene.x() - roi.width // 2 - 10 - box_width
            stats_box_rect.moveLeft(int(initial_x))

        viewer.stats_box_positions[roi.id] = stats_box_rect

    def draw_temporary_shape(self, painter):
        """由ImageViewer调用，用于在绘制过程中显示临时形状。"""
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            
            rect = QRectF(self.start_point, self.end_point)
            painter.drawRect(rect)

    def wheelEvent(self, event: QWheelEvent) -> bool:
        """不处理滚轮事件，让上一级处理（例如切片）"""
        return False


class CircleROITool(BaseTool):
    """
    用于通过拖拽绘制圆形ROI的工具。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.is_drawing = False
        self.start_point: QPointF = QPointF()
        self.end_point: QPointF = QPointF()

    def activate(self):
        """激活工具，设置十字准星光标。"""
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        """停用工具，恢复默认光标。"""
        self.is_drawing = False
        self.viewer.scene.update()
        self.viewer.setCursor(Qt.ArrowCursor)

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，开始绘制ROI。"""
        super().mouse_press_event(event)
        if self._press_is_outside:
            return

        if event.button() == Qt.LeftButton:
            self.is_drawing = True
            self.start_point = self.viewer.last_mouse_scene_pos
            self.end_point = self.start_point
            event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件，更新ROI预览。"""
        super().mouse_move_event(event)
        
        if self.is_drawing:
            self.end_point = self.viewer.last_mouse_scene_pos
            self.viewer.scene.update()
            event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件，完成ROI绘制。"""
        super().mouse_release_event(event)

        if self.is_drawing and event.button() == Qt.LeftButton:
            self.is_drawing = False
            self.end_point = self.viewer.last_mouse_scene_pos
            
            model = self.viewer.model
            if model and model.has_image():
                rect = QRectF(self.start_point, self.end_point).normalized()
                
                if rect.width() > 1 and rect.height() > 1:
                    current_slice_index = model.current_slice_index
                    # 圆形ROI使用外接正方形的较小边作为直径
                    radius = int(min(rect.width(), rect.height()) / 2)
                    roi = CircleROI(
                        center=(int(rect.center().y()), int(rect.center().x())),
                        radius=radius,
                        slice_index=current_slice_index
                    )
                    model.add_roi(roi)
                    self._calculate_and_store_stats_box_rect(roi)
            
            self.viewer.scene.update()
            event.accept()

    def _calculate_and_store_stats_box_rect(self, roi: CircleROI):
        """计算统计信息框的智能位置和大小，并存储。"""
        viewer = self.viewer
        if not viewer.model:
            return

        stats = calculate_roi_statistics(viewer.model, roi)
        if not stats:
            return

        font = viewer.font()
        font.setPointSize(FONT_SIZE)
        stats_text = get_stats_text(stats)
        size_rect = calculate_stats_box_size_rect(stats_text, font)
        box_width = size_rect.width()
        box_height = size_rect.height()

        # 计算初始位置（在ROI的右侧）
        roi_center_scene = QPointF(roi.center[1], roi.center[0])
        
        initial_x = roi_center_scene.x() + roi.radius + 10
        initial_y = roi_center_scene.y() - box_height / 2
        
        stats_box_rect = QRect(int(initial_x), int(initial_y), int(box_width), int(box_height))

        # 检查是否超出右边界
        view_rect_scene = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        if stats_box_rect.right() > view_rect_scene.right():
            initial_x = roi_center_scene.x() - roi.radius - 10 - box_width
            stats_box_rect.moveLeft(int(initial_x))

        viewer.stats_box_positions[roi.id] = stats_box_rect

    def draw_temporary_shape(self, painter):
        """由ImageViewer调用，用于在绘制过程中显示临时形状。"""
        if self.is_drawing:
            painter.setPen(QPen(QColor("yellow"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            
            rect = QRectF(self.start_point, self.end_point)
            # 绘制圆形，使用较小的边作为直径
            size = min(rect.width(), rect.height())
            circle_rect = QRectF(rect.center().x() - size/2, rect.center().y() - size/2, size, size)
            painter.drawEllipse(circle_rect)

    def wheelEvent(self, event: QWheelEvent) -> bool:
        """不处理滚轮事件，让上一级处理（例如切片）"""
        return False 