from medimager.ui.tools.base_tool import BaseTool
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QCursor
from PySide6.QtCore import Qt, QPointF, QPoint
from medimager.core.roi import BaseROI
from enum import Enum, auto
import math


class DragMode(Enum):
    """定义默认工具的拖动模式"""
    NONE = auto()
    BROWSE_IMAGES = auto()      # 浏览系列图像
    ADJUST_WINDOW = auto()      # 调整窗口（亮度/对比度）
    ZOOM = auto()               # 放大/缩小图像
    PAN = auto()                # 平移图像
    ROI_MOVE = auto()           # 移动ROI
    ROI_RESIZE = auto()         # 调整ROI大小
    INFO_BOX_MOVE = auto()      # 移动信息板


class DefaultTool(BaseTool):
    """
    默认工具，提供符合用户习惯的多种交互功能。
    - 鼠标左键+鼠标移动: 浏览系列图像[默认设置]
    - 鼠标中键+鼠标移动: 调整图像窗口（亮度/对比度）[默认设置]
    - 鼠标右键+鼠标移动: 放大/缩小图像[默认设置]
    - Shift +鼠标左键+鼠标移动: 平移图片
    - 垂直滚轮: 浏览切片
    - Ctrl + 滚轮: 缩放
    - ROI交互: 支持拖拽ROI锚点、移动ROI、移动信息板
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self._drag_mode = DragMode.NONE
        self._last_mouse_pos = QPoint()
        self._target_roi_id: str | None = None
        self._target_anchor_idx: int | None = None

    def activate(self):
        """激活工具，设置光标样式。"""
        self.viewer.setCursor(Qt.ArrowCursor)

    def deactivate(self):
        """停用工具，恢复默认光标。"""
        self.viewer.setCursor(Qt.ArrowCursor)

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，根据点击位置和按键确定拖动模式。"""
        super().mouse_press_event(event) # 调用基类方法
        if self._press_is_outside: # 检查标志
            return
        self._last_mouse_pos = event.pos()
        model = self.viewer.model
        
        # 左键：ROI交互或浏览图像
        if event.button() == Qt.LeftButton:
            if event.modifiers() == Qt.ShiftModifier:
                # Shift+左键：平移
                self._drag_mode = DragMode.PAN
                self.viewer.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            elif model and model.has_image():
                # 检查ROI交互：锚点、信息板、ROI主体
                if self._check_roi_interactions(self.viewer.last_mouse_scene_pos, event.modifiers()):
                    event.accept()
                    return
            
            # 默认：浏览系列图像
            self._drag_mode = DragMode.BROWSE_IMAGES
            event.accept()
            return

        # 中键：调整窗口（亮度/对比度）
        if event.button() == Qt.MiddleButton:
            self._drag_mode = DragMode.ADJUST_WINDOW
            event.accept()
            return

        # 右键：放大/缩小图像
        if event.button() == Qt.RightButton:
            self._drag_mode = DragMode.ZOOM
            event.accept()
            return
            
    def _check_roi_interactions(self, scene_pos: QPointF, modifiers) -> bool:
        """检查ROI交互：ROI锚点 > 信息板 > ROI主体"""
        model = self.viewer.model
        view = self.viewer
        
        # 1. 检查是否击中某个已选中ROI的锚点
        rois_on_slice = [roi for roi in reversed(model.rois) if roi.slice_index == model.current_slice_index]
        for roi in rois_on_slice:
            if roi.selected:
                for i, (ay, ax) in enumerate(roi.get_anchor_points()):
                    # 将锚点坐标转换为场景坐标 QPointF
                    anchor_pos_scene = QPointF(ax, ay)
                    # 计算与鼠标点击位置的距离(手动计算以避免NotImplementedError)
                    dx = scene_pos.x() - anchor_pos_scene.x()
                    dy = scene_pos.y() - anchor_pos_scene.y()
                    if abs(dx) + abs(dy) < 10: # 10px的容差
                        self._drag_mode = DragMode.ROI_RESIZE
                        self._target_roi_id = roi.id
                        self._target_anchor_idx = i
                        roi.start_resize(i) # 通知ROI开始缩放
                        return True

        # 2. 检查是否击中某个信息板
        for roi in rois_on_slice:
            if roi.id in view.stats_box_positions:
                info_box_rect = view.stats_box_positions[roi.id]
                if info_box_rect.contains(scene_pos.toPoint()):
                    self._drag_mode = DragMode.INFO_BOX_MOVE
                    self._target_roi_id = roi.id
                    # 选中这个ROI以提供视觉反馈
                    model.select_roi(roi.id, multi=modifiers & Qt.ControlModifier)
                    return True

        # 3. 检查是否击中某个ROI的内部
        for roi in rois_on_slice:
            hit_type = roi.hit_test((scene_pos.y(), scene_pos.x()))
            if hit_type == 'inside':
                self._drag_mode = DragMode.ROI_MOVE
                self._target_roi_id = roi.id
                model.select_roi(roi.id, multi=modifiers & Qt.ControlModifier)
                return True

        # 4. 如果什么都没点中，则清除选择（除非按住Ctrl）
        if not (modifiers & Qt.ControlModifier):
            model.clear_selection()
        
        return False

    def mouse_move_event(self, event: QMouseEvent):
        """根据当前的拖动模式执行相应的操作。"""
        super().mouse_move_event(event)
        
        delta = event.pos() - self._last_mouse_pos
        scene_delta = self.viewer.last_mouse_scene_pos - self.viewer.mapToScene(self._last_mouse_pos)
        self._last_mouse_pos = event.pos()
        
        model = self.viewer.model
        view = self.viewer

        if self._drag_mode == DragMode.BROWSE_IMAGES:
            # 浏览系列图像
            if model and model.get_slice_count() > 1:
                # 根据垂直移动切换切片
                if abs(delta.y()) > 5:  # 阈值避免过于敏感
                    direction = 1 if delta.y() > 0 else -1
                    model.set_current_slice(model.current_slice_index + direction)
        
        elif self._drag_mode == DragMode.ADJUST_WINDOW:
            # 调整窗口（亮度/对比度）
            if model:
                ww, wl = model.window_width, model.window_level
                model.set_window(max(1, ww + delta.x()), wl + delta.y())

        elif self._drag_mode == DragMode.ZOOM:
            # 放大/缩小图像
            zoom_factor = 1.0 + delta.y() * 0.01  # 缩放敏感度
            if zoom_factor > 0.1:  # 防止缩放过小
                self.viewer.scale(zoom_factor, zoom_factor)

        elif self._drag_mode == DragMode.PAN:
            # 平移图像
            self.viewer.horizontalScrollBar().setValue(self.viewer.horizontalScrollBar().value() - delta.x())
            self.viewer.verticalScrollBar().setValue(self.viewer.verticalScrollBar().value() - delta.y())

        elif self._drag_mode == DragMode.ROI_RESIZE and self._target_roi_id and model:
            roi = model.get_roi_by_id(self._target_roi_id)
            if roi:
                scene_pos = self.viewer.last_mouse_scene_pos # 使用安全坐标
                roi.resize(self._target_anchor_idx, (scene_pos.y(), scene_pos.x()))
                # 不要在缩放时移动信息框，保持其原有位置
                view.scene.update()

        elif self._drag_mode == DragMode.ROI_MOVE and self._target_roi_id and model:
            roi = model.get_roi_by_id(self._target_roi_id)
            if roi:
                roi.move(scene_delta.y(), scene_delta.x())
                 # 如果信息板也关联，一起移动
                if roi.id in view.stats_box_positions:
                    view.stats_box_positions[roi.id].translate(scene_delta.toPoint())
                view.scene.update()
        
        elif self._drag_mode == DragMode.INFO_BOX_MOVE and self._target_roi_id:
            if self._target_roi_id in view.stats_box_positions:
                view.stats_box_positions[self._target_roi_id].translate(scene_delta.toPoint())
                view.scene.update()

        event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件，重置拖动状态。"""
        model = self.viewer.model
        if self._drag_mode == DragMode.ROI_RESIZE and self._target_roi_id and model:
            roi = model.get_roi_by_id(self._target_roi_id)
            if roi:
                roi.end_resize()

        self._drag_mode = DragMode.NONE
        self._target_roi_id = None
        self._target_anchor_idx = None
        self.viewer.setCursor(Qt.ArrowCursor)
        self.viewer.scene.update()
        event.accept()

    def wheel_event(self, event: QWheelEvent):
        """处理滚轮事件，实现缩放或切片切换。"""
        modifiers = event.modifiers()
        angle = event.angleDelta().y()

        if modifiers == Qt.ControlModifier:
            if angle > 0: self.viewer.zoom_in()
            else: self.viewer.zoom_out()
            event.accept()
        elif modifiers == Qt.NoModifier:
            if self.viewer.model and self.viewer.model.get_slice_count() > 1:
                direction = -1 if angle > 0 else 1
                self.viewer.model.set_current_slice(self.viewer.model.current_slice_index + direction)
                event.accept() 