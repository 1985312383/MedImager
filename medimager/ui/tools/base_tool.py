import math
from abc import ABC, abstractmethod
from typing import Optional

from PySide6.QtWidgets import QGraphicsView
from PySide6.QtCore import QEvent, Qt, QPointF, QCoreApplication
from PySide6.QtGui import QMouseEvent, QWheelEvent, QKeyEvent


# ---------------------------------------------------------------------------
# 共享几何工具函数
# ---------------------------------------------------------------------------

def point_distance(p1: QPointF, p2: QPointF) -> float:
    """计算两点间的像素距离。"""
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    return math.sqrt(dx * dx + dy * dy)


def point_to_line_distance(point: QPointF, line_start: QPointF, line_end: QPointF) -> float:
    """计算点到线段的最短距离。"""
    line_vec = line_end - line_start
    point_vec = point - line_start

    line_len_sq = line_vec.x() ** 2 + line_vec.y() ** 2
    if line_len_sq == 0:
        return point_distance(point, line_start)

    t = max(0, min(1, (point_vec.x() * line_vec.x() + point_vec.y() * line_vec.y()) / line_len_sq))
    projection = line_start + t * line_vec
    return point_distance(point, projection)


def check_measurement_hit(viewer: 'QGraphicsView', pos: QPointF) -> Optional[int]:
    """检查点击位置是否命中某个测量线，返回全局索引或 None。"""
    model = getattr(viewer, 'model', None)
    if not model:
        return None

    current_slice_measurements = model.get_measurements_for_slice(model.current_slice_index)
    if not current_slice_measurements:
        return None

    transform = viewer.transform()
    scale_factor = transform.m11()
    scene_detection_radius = 10.0 / scale_factor  # 10 屏幕像素

    for measurement in current_slice_measurements:
        line_distance = point_to_line_distance(pos, measurement.start_point, measurement.end_point)
        if line_distance <= scene_detection_radius:
            for global_idx, gm in enumerate(model.measurements):
                if gm.id == measurement.id:
                    return global_idx

    return None


class BaseTool(ABC):
    """
    所有交互工具的抽象基类。

    定义了工具与ImageViewer交互所需的通用接口。
    每个工具都与一个特定的视图（ImageViewer）相关联。
    """
    def __init__(self, viewer: 'ImageViewer'):
        """
        初始化工具。

        Args:
            viewer: 与此工具关联的ImageViewer实例。
        """
        self.viewer = viewer
        self._press_is_outside = False

    def tr(self, text: str) -> str:
        """翻译文本"""
        return QCoreApplication.translate(self.__class__.__name__, text)

    @abstractmethod
    def activate(self):
        """激活工具时调用。"""
        pass

    @abstractmethod
    def deactivate(self):
        """停用工具时调用。"""
        pass

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件。"""
        scene_pos = self.viewer.mapToScene(event.pos())
        self._press_is_outside = True
        if self.viewer.image_item and not self.viewer.image_item.pixmap().isNull():
            image_rect = self.viewer.image_item.pixmap().rect()
            # 修复：将QPointF转换为QPoint以进行正确的包含检查
            if image_rect.contains(scene_pos.toPoint()):
                self._press_is_outside = False
        self.viewer.last_mouse_scene_pos = scene_pos


    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件。"""
        # 移动放大镜
        offset = 20
        magnifier = self.viewer.magnifier
        magnifier_pos = event.pos()
        
        magnifier_x = magnifier_pos.x() + offset
        if magnifier_x + magnifier.width() > self.viewer.viewport().width():
            magnifier_x = magnifier_pos.x() - magnifier.width() - offset

        magnifier_y = magnifier_pos.y() + offset
        if magnifier_y + magnifier.height() > self.viewer.viewport().height():
            magnifier_y = magnifier_pos.y() - magnifier.height() - offset
        
        magnifier.move(magnifier_x, magnifier_y)

        # 更新像素信息和安全坐标
        scene_pos = self.viewer.mapToScene(event.pos())
        clamped_pos = scene_pos
        if self.viewer.image_item and not self.viewer.image_item.pixmap().isNull():
            image_rect = self.viewer.image_item.pixmap().rect()
            clamped_x = max(image_rect.left(), min(scene_pos.x(), image_rect.right()))
            clamped_y = max(image_rect.top(), min(scene_pos.y(), image_rect.bottom()))
            clamped_pos = QPointF(clamped_x, clamped_y)

        # 更新像素值信息（通过信号发送坐标和像素值）
        if hasattr(self.viewer, '_update_pixel_info'):
            self.viewer._update_pixel_info(clamped_pos)
        self.viewer.last_mouse_scene_pos = clamped_pos 

        # --- ROI Hover Detection ---
        model = getattr(self.viewer, 'model', None)
        # 仅在不进行拖拽操作时（无鼠标按键按下）检测悬停
        if event.buttons() == Qt.NoButton and model:
            x, y = int(clamped_pos.x()), int(clamped_pos.y())
            currently_hovered = None
            # 反向遍历，优先检测顶层的ROI
            for idx in range(len(model.rois) - 1, -1, -1):
                roi = model.rois[idx]
                if roi.slice_index != model.current_slice_index:
                    continue
                
                # 如果鼠标在ROI内部，则标记为悬停
                if roi.hit_test((y, x), tol=10) != 'none':
                    currently_hovered = idx
                    break 
            
            # 仅在悬停状态改变时才重绘，避免不必要的刷新
            if self.viewer.hovered_roi_index != currently_hovered:
                self.viewer.hovered_roi_index = currently_hovered
                self.viewer.viewport().update()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件。"""
        scene_pos = self.viewer.mapToScene(event.pos())
        clamped_pos = scene_pos
        if self.viewer.image_item and not self.viewer.image_item.pixmap().isNull():
            image_rect = self.viewer.image_item.pixmap().rect()
            clamped_x = max(image_rect.left(), min(scene_pos.x(), image_rect.right()))
            clamped_y = max(image_rect.top(), min(scene_pos.y(), image_rect.bottom()))
            clamped_pos = QPointF(clamped_x, clamped_y)
        self.viewer.last_mouse_scene_pos = clamped_pos
        self._press_is_outside = False # 重置状态
        
    def wheel_event(self, event: QWheelEvent):
        """处理鼠标滚轮事件。"""
        pass

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件。子类可以重写此方法以处理特定的按键。"""
        pass

    def key_release_event(self, event: QKeyEvent):
        """处理键盘释放事件。子类可以重写此方法以处理特定的按键。"""
        pass