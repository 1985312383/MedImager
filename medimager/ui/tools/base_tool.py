from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from medimager.ui.image_viewer import ImageViewer

from PySide6.QtWidgets import QGraphicsView
from PySide6.QtCore import Qt, QPointF, QCoreApplication
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


def viewer_slice_index(viewer: 'QGraphicsView') -> int:
    """Return the pane-local slice, falling back to the legacy model state."""
    accessor = getattr(viewer, 'current_slice_index', None)
    if callable(accessor):
        try:
            return int(accessor())
        except (TypeError, ValueError):
            pass
    if accessor is not None and not callable(accessor):
        try:
            return int(accessor)
        except (TypeError, ValueError):
            pass
    state = getattr(viewer, 'presentation_state', None)
    if state is not None and hasattr(state, 'slice_index'):
        try:
            return int(state.slice_index)
        except (TypeError, ValueError):
            pass
    model = getattr(viewer, 'model', None)
    return int(getattr(model, 'current_slice_index', 0) or 0)


def check_measurement_hit(viewer: 'QGraphicsView', pos: QPointF) -> Optional[int]:
    """检查点击位置是否命中某个测量线，返回全局索引或 None。"""
    model = getattr(viewer, 'model', None)
    if not model:
        return None

    current_slice_measurements = model.get_measurements_for_slice(
        viewer_slice_index(viewer)
    )
    if not current_slice_measurements:
        return None

    if hasattr(viewer, 'effective_scale'):
        scale_factor = viewer.effective_scale()
    else:
        transform = viewer.transform()
        scale_factor = max(1e-6, math.hypot(transform.m11(), transform.m12()))
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
    def __init__(self, viewer: ImageViewer):
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

    def finalize_interaction(self) -> None:
        """在关闭等生命周期边界提交已发生的编辑；默认无在途状态。"""
        return

    def cancel_interaction(self) -> None:
        """Cancel transient creation state; subclasses may provide rollback."""
        return

    def current_slice_index(self) -> int:
        return viewer_slice_index(self.viewer)

    def measurement_pixel_spacing(self) -> tuple[float, float] | None:
        """Return patient-geometry spacing, never display-only pixel aspect."""
        model = getattr(self.viewer, 'model', None)
        if model is None:
            return None
        getter = getattr(model, 'get_measurement_pixel_spacing', None)
        if callable(getter):
            return getter(self.current_slice_index())
        # Compatibility with models predating the explicit measurement API.
        fallback = getattr(model, 'get_pixel_spacing', None)
        return fallback(self.current_slice_index()) if callable(fallback) else None

    def set_view_slice(self, slice_index: int) -> bool:
        setter = getattr(self.viewer, 'set_view_slice', None)
        if callable(setter):
            result = setter(int(slice_index))
            return result is not False
        model = getattr(self.viewer, 'model', None)
        if model is None:
            return False
        result = model.set_current_slice(int(slice_index))
        return result is not False

    def current_window(self) -> tuple[float, float]:
        state = getattr(self.viewer, 'presentation_state', None)
        if state is not None:
            try:
                return float(state.window_width), float(state.window_level)
            except (AttributeError, TypeError, ValueError):
                pass
        model = getattr(self.viewer, 'model', None)
        return (
            float(getattr(model, 'window_width', 1.0)),
            float(getattr(model, 'window_level', 0.0)),
        )

    def set_view_window(self, width: float, level: float) -> bool:
        setter = getattr(self.viewer, 'set_view_window', None)
        if callable(setter):
            result = setter(float(width), float(level))
            return result is not False
        model = getattr(self.viewer, 'model', None)
        if model is None:
            return False
        result = model.set_window(width, level)
        return result is not False

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件。"""
        scene_pos = self.viewer.mapToScene(event.position().toPoint())
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
        magnifier_pos = event.position().toPoint()
        
        magnifier_x = magnifier_pos.x() + offset
        if magnifier_x + magnifier.width() > self.viewer.viewport().width():
            magnifier_x = magnifier_pos.x() - magnifier.width() - offset

        magnifier_y = magnifier_pos.y() + offset
        if magnifier_y + magnifier.height() > self.viewer.viewport().height():
            magnifier_y = magnifier_pos.y() - magnifier.height() - offset
        
        magnifier.move(magnifier_x, magnifier_y)

        # 更新像素信息和安全坐标
        scene_pos = self.viewer.mapToScene(event.position().toPoint())
        clamped_pos = scene_pos
        inside_image = False
        if self.viewer.image_item and not self.viewer.image_item.pixmap().isNull():
            image_rect = self.viewer.image_item.pixmap().rect()
            inside_image = image_rect.contains(scene_pos.toPoint())
            clamped_x = max(image_rect.left(), min(scene_pos.x(), image_rect.right()))
            clamped_y = max(image_rect.top(), min(scene_pos.y(), image_rect.bottom()))
            clamped_pos = QPointF(clamped_x, clamped_y)

        # 像素信息必须使用未钳制位置，否则鼠标移出图像后仍会错误显示边缘像素。
        if hasattr(self.viewer, '_update_pixel_info'):
            self.viewer._update_pixel_info(scene_pos)
        self.viewer.last_mouse_scene_pos = clamped_pos 

        # --- ROI Hover Detection ---
        model = getattr(self.viewer, 'model', None)
        # 仅在不进行拖拽操作时（无鼠标按键按下）检测悬停
        if event.buttons() == Qt.NoButton and model and inside_image:
            x, y = int(clamped_pos.x()), int(clamped_pos.y())
            currently_hovered = None
            scale = self.viewer.effective_scale() if hasattr(self.viewer, 'effective_scale') else 1.0
            hover_tolerance = 10.0 / max(scale, 1e-6)
            # 反向遍历，优先检测顶层的ROI
            for idx in range(len(model.rois) - 1, -1, -1):
                roi = model.rois[idx]
                if roi.slice_index != self.current_slice_index():
                    continue
                
                # 如果鼠标在ROI内部，则标记为悬停
                if roi.hit_test((y, x), tol=hover_tolerance) != 'none':
                    currently_hovered = idx
                    break 
            
            # 仅在悬停状态改变时才重绘，避免不必要的刷新
            if self.viewer.hovered_roi_index != currently_hovered:
                self.viewer.hovered_roi_index = currently_hovered
                self.viewer.viewport().update()
        elif event.buttons() == Qt.NoButton and model and self.viewer.hovered_roi_index is not None:
            self.viewer.hovered_roi_index = None
            self.viewer.viewport().update()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件。"""
        scene_pos = self.viewer.mapToScene(event.position().toPoint())
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
        event.ignore()

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件。子类可以重写此方法以处理特定的按键。"""
        event.ignore()

    def key_release_event(self, event: QKeyEvent):
        """处理键盘释放事件。子类可以重写此方法以处理特定的按键。"""
        event.ignore()
