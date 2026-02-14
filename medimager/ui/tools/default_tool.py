from medimager.ui.tools.base_tool import BaseTool, point_distance, check_measurement_hit
from medimager.utils.logger import get_logger
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QCursor, QKeyEvent
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
        self.logger = get_logger(__name__)
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
        """处理鼠标按下事件，根据按键和修饰键设置拖动模式。"""
        super().mouse_press_event(event)
        self._last_mouse_pos = event.pos()
        model = self.viewer.model
        
        # 左键处理
        if event.button() == Qt.LeftButton:
            if event.modifiers() == Qt.ShiftModifier:
                # Shift+左键：平移
                self._drag_mode = DragMode.PAN
                self.viewer.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            elif model and model.has_image():
                # 先检查测量选中 - 如果处理了测量交互，就不进入其他模式
                if self._check_measurement_interactions(self.viewer.last_mouse_scene_pos, event.modifiers()):
                    # 重要：确保不进入其他拖拽模式
                    self._drag_mode = DragMode.NONE
                    event.accept()
                    return
                
                # 再检查ROI交互：锚点、信息板、ROI主体
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
            
    def _check_measurement_interactions(self, scene_pos: QPointF, modifiers) -> bool:
        """检查测量交互 - DefaultTool只处理选中，不处理拖拽"""
        model = self.viewer.model
        if not model:
            return False
        
        # 检查是否击中测量线 - 只处理选中，不触发拖拽
        clicked_measurement_index = check_measurement_hit(self.viewer, scene_pos)
        
        if clicked_measurement_index is not None:
            # DefaultTool只处理选中/取消选中，不处理拖拽
            if not (modifiers & Qt.ControlModifier):
                model.clear_measurement_selection()
                model.clear_selection()  # 同时清除ROI选择
            
            if clicked_measurement_index in model.selected_measurement_indices:
                model.deselect_measurement(clicked_measurement_index)
            else:
                model.select_measurement(clicked_measurement_index)
            
            # 强制更新视图以立即显示选中状态
            self.viewer.viewport().update()
            
            # 重要：设置拖拽模式为NONE，防止意外拖拽
            self._drag_mode = DragMode.NONE
            return True
        
        return False
            
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
            model.clear_measurement_selection()
        
        return False

    def mouse_move_event(self, event: QMouseEvent):
        """根据当前的拖动模式执行相应的操作。"""
        super().mouse_move_event(event)
        
        # 如果拖拽模式为NONE，不执行任何拖拽操作
        if self._drag_mode == DragMode.NONE:
            event.accept()
            return
        
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
                    new_index = model.current_slice_index + direction
                    model.set_current_slice(new_index)
                    self._sync_slice(model.current_slice_index)

        elif self._drag_mode == DragMode.ADJUST_WINDOW:
            # 调整窗口（亮度/对比度）
            if model:
                ww, wl = model.window_width, model.window_level
                new_ww = max(1, ww + delta.x())
                new_wl = wl + delta.y()
                model.set_window(new_ww, new_wl)
                self._sync_window_level(model.window_width, model.window_level)

        elif self._drag_mode == DragMode.ZOOM:
            # 放大/缩小图像
            zoom_factor = 1.0 + delta.y() * 0.01  # 缩放敏感度
            if zoom_factor > 0.1:  # 防止缩放过小
                self.viewer.scale(zoom_factor, zoom_factor)
                self._sync_zoom_pan()

        elif self._drag_mode == DragMode.PAN:
            # 平移图像
            self.viewer.horizontalScrollBar().setValue(self.viewer.horizontalScrollBar().value() - delta.x())
            self.viewer.verticalScrollBar().setValue(self.viewer.verticalScrollBar().value() - delta.y())
            self._sync_zoom_pan()

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
            self._sync_zoom_pan()
            event.accept()
        elif modifiers == Qt.NoModifier:
            if self.viewer.model and self.viewer.model.get_slice_count() > 1:
                direction = -1 if angle > 0 else 1
                self.viewer.model.set_current_slice(self.viewer.model.current_slice_index + direction)
                self._sync_slice(self.viewer.model.current_slice_index)

                # 切片切换后，如果鼠标在图像区域内，主动更新像素信息
                if hasattr(self.viewer, 'last_mouse_scene_pos') and self.viewer.last_mouse_scene_pos:
                    if hasattr(self.viewer, '_update_pixel_info'):
                        self.viewer._update_pixel_info(self.viewer.last_mouse_scene_pos)

                event.accept()

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件"""
        super().key_press_event(event)
        
        if event.key() == Qt.Key_F12:
            # 调试测量线信息
            self._debug_all_measurements()
            event.accept()
            return
        
        if event.key() == Qt.Key_Delete:
            model = self.viewer.model
            if model:
                deleted_something = False
                
                # 删除选中的测量 - 优先处理测量删除
                if model.selected_measurement_indices:
                    deleted_measurement_ids = model.delete_selected_measurements()
                    self.logger.info(f"删除了 {len(deleted_measurement_ids)} 个测量")
                    deleted_something = True
                
                # 删除选中的ROI
                if model.selected_indices:
                    deleted_roi_ids = model.delete_selected_rois()
                    
                    # 清除相关的统计框
                    for roi_id in deleted_roi_ids:
                        if hasattr(self.viewer, 'stats_box_positions') and roi_id in self.viewer.stats_box_positions:
                            del self.viewer.stats_box_positions[roi_id]
                    
                    deleted_something = True
                
                if deleted_something:
                    self.viewer.viewport().update()
                    event.accept()
                else:
                    self.logger.debug("[DefaultTool.key_press_event] Del键按下，但没有选中的ROI或测量")
            else:
                self.logger.debug("[DefaultTool.key_press_event] Del键按下，但模型为空")

    # ---- 同步辅助方法 ----

    def _get_sync_context(self):
        """获取同步上下文（view_id 和 sync_manager）"""
        viewer = self.viewer
        if not viewer:
            return None, None
        view_id = getattr(viewer, '_view_id', None)
        sync_manager = getattr(viewer, '_sync_manager', None)
        return view_id, sync_manager

    def _sync_window_level(self, window_width: int, window_level: int) -> None:
        """同步窗宽窗位到其他视图"""
        view_id, sync_manager = self._get_sync_context()
        if view_id and sync_manager:
            try:
                sync_manager.sync_window_level(view_id, window_width, window_level)
            except Exception as e:
                self.logger.debug(f"[DefaultTool._sync_window_level] 同步失败: {e}")

    def _sync_slice(self, slice_index: int) -> None:
        """同步切片位置到其他视图"""
        view_id, sync_manager = self._get_sync_context()
        if view_id and sync_manager:
            try:
                sync_manager.sync_slice(view_id, slice_index)
            except Exception as e:
                self.logger.debug(f"[DefaultTool._sync_slice] 同步失败: {e}")

    def _sync_zoom_pan(self) -> None:
        """同步缩放平移到其他视图"""
        view_id, sync_manager = self._get_sync_context()
        if view_id and sync_manager:
            try:
                from PySide6.QtCore import QPointF
                transform = self.viewer.transform()
                zoom_factor = transform.m11()
                h_scroll = self.viewer.horizontalScrollBar().value()
                v_scroll = self.viewer.verticalScrollBar().value()
                pan_offset = QPointF(h_scroll, v_scroll)
                sync_manager.sync_zoom_pan(view_id, zoom_factor, pan_offset, transform)
            except Exception as e:
                self.logger.debug(f"[DefaultTool._sync_zoom_pan] 同步失败: {e}")

    def _debug_all_measurements(self):
        """调试输出所有测量线信息"""
        model = self.viewer.model
        if not model:
            self.logger.info("模型为空")
            return
        
        self.logger.info("=" * 40)
        self.logger.info("测量线调试信息")
        self.logger.info("=" * 40)
        
        self.logger.info(f"总数量: {len(model.measurements)}")
        self.logger.info(f"当前切片: {model.current_slice_index}")
        self.logger.info(f"选中索引: {list(model.selected_measurement_indices)}")
        
        current_slice_measurements = model.get_measurements_for_slice(model.current_slice_index)
        self.logger.info(f"当前切片数量: {len(current_slice_measurements)}")
        
        for i, measurement in enumerate(model.measurements):
            # 计算线段长度
            dx = measurement.end_point.x() - measurement.start_point.x()
            dy = measurement.end_point.y() - measurement.start_point.y()
            length = math.sqrt(dx * dx + dy * dy)
            
            selected = "是" if i in model.selected_measurement_indices else "否"
            on_current_slice = "是" if measurement.slice_index == model.current_slice_index else "否"
            
            self.logger.info(f"测量{i}: 距离={measurement.distance:.1f}{measurement.unit}, "
                           f"长度={length:.1f}, 选中={selected}, 当前切片={on_current_slice}")
            
            if length < 0.1:
                self.logger.warning(f"  警告：测量{i}长度过短")
        
        self.logger.info("=" * 40)