from medimager.ui.tools.base_tool import BaseTool, point_distance, check_measurement_hit
from medimager.utils.logger import get_logger
from medimager.utils.settings import get_settings_manager
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QKeyEvent
from PySide6.QtCore import Qt, QPointF, QPoint
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
    MEASUREMENT_MOVE = auto()
    MEASUREMENT_RESIZE = auto()
    ANGLE_MOVE = auto()
    ANGLE_RESIZE = auto()
    ANNOTATION_LABEL_MOVE = auto()


DRAG_ACTION_TO_MODE = {
    "browse": DragMode.BROWSE_IMAGES,
    "window": DragMode.ADJUST_WINDOW,
    "zoom": DragMode.ZOOM,
    "pan": DragMode.PAN,
    "none": DragMode.NONE,
}


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

    def __init__(self, viewer: QGraphicsView, interaction_mode: str = 'default'):
        super().__init__(viewer)
        self.logger = get_logger(__name__)
        self.interaction_mode = (
            interaction_mode
            if interaction_mode in {'default', 'pan', 'zoom', 'window_level'}
            else 'default'
        )
        self._drag_mode = DragMode.NONE
        self._last_mouse_pos = QPoint()
        self._target_roi_id: str | None = None
        self._target_anchor_idx: int | None = None
        self._roi_interaction_changed = False
        self._target_measurement_id: str | None = None
        self._target_measurement_anchor: str | None = None
        self._target_angle_id: str | None = None
        self._target_angle_anchor: str | None = None
        self._target_label_id: str | None = None
        self._annotation_interaction_changed = False
        self._browse_drag_remainder = 0
        self._wheel_angle_remainder = 0
        self._wheel_pixel_remainder = 0
        self._wheel_remainder_modifiers = None

    def activate(self):
        """激活工具，设置光标样式。"""
        if self.interaction_mode == 'pan':
            self.viewer.setCursor(Qt.OpenHandCursor)
        elif self.interaction_mode in {'zoom', 'window_level'}:
            self.viewer.setCursor(Qt.SizeVerCursor)
        else:
            self.viewer.setCursor(Qt.ArrowCursor)

    def deactivate(self):
        """停用工具，恢复默认光标。"""
        self.finalize_interaction()
        self.viewer.setCursor(Qt.ArrowCursor)

    def finalize_interaction(self) -> None:
        """提交尚未收到 mouseRelease 的 ROI 移动或缩放。"""
        self._finish_drag_interaction()

    def cancel_interaction(self) -> None:
        # Geometry is updated continuously, so cancellation at an arbitrary
        # lifecycle boundary safely commits the already-visible state.
        self._finish_drag_interaction()

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，根据按键和修饰键设置拖动模式。"""
        super().mouse_press_event(event)
        self._last_mouse_pos = event.position().toPoint()
        self._browse_drag_remainder = 0
        model = self.viewer.model
        
        # 左键处理
        if event.button() == Qt.LeftButton:
            forced_mode = {
                'pan': DragMode.PAN,
                'zoom': DragMode.ZOOM,
                'window_level': DragMode.ADJUST_WINDOW,
            }.get(self.interaction_mode)
            if forced_mode is not None:
                self._drag_mode = forced_mode
                if forced_mode == DragMode.PAN:
                    self.viewer.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            if event.modifiers() == Qt.ShiftModifier:
                # Shift+左键：平移
                self._drag_mode = DragMode.PAN
                self.viewer.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            elif model and model.has_image():
                if self._check_annotation_label_interaction(
                    self.viewer.last_mouse_scene_pos
                ):
                    event.accept()
                    return
                # Pointer owns selection and editing for all persisted
                # annotation types; creation tools only create new objects.
                if self._check_measurement_interactions(self.viewer.last_mouse_scene_pos, event.modifiers()):
                    event.accept()
                    return
                if self._check_angle_interactions(
                    self.viewer.last_mouse_scene_pos, event.modifiers()
                ):
                    event.accept()
                    return
                
                # 再检查ROI交互：锚点、信息板、ROI主体
                if self._check_roi_interactions(self.viewer.last_mouse_scene_pos, event.modifiers()):
                    event.accept()
                    return
            
            self._drag_mode = self._drag_mode_from_setting("interaction.left_drag_action", DragMode.BROWSE_IMAGES)
            if self._drag_mode == DragMode.PAN:
                self.viewer.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        # 中键：调整窗口（亮度/对比度）
        if event.button() == Qt.MiddleButton:
            self._drag_mode = self._drag_mode_from_setting("interaction.middle_drag_action", DragMode.ADJUST_WINDOW)
            if self._drag_mode == DragMode.PAN:
                self.viewer.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        # 右键：放大/缩小图像
        if event.button() == Qt.RightButton:
            self._drag_mode = self._drag_mode_from_setting("interaction.right_drag_action", DragMode.ZOOM)
            if self._drag_mode == DragMode.PAN:
                self.viewer.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

    def _drag_mode_from_setting(self, key: str, default: DragMode) -> DragMode:
        try:
            action = get_settings_manager().get_setting(key, None)
            return DRAG_ACTION_TO_MODE.get(str(action), default)
        except Exception:
            return default
            
    def _check_measurement_interactions(self, scene_pos: QPointF, modifiers) -> bool:
        """Select and start whole-line or anchor editing for a distance."""
        model = self.viewer.model
        if not model:
            return False

        scale = self.viewer.effective_scale() if hasattr(self.viewer, 'effective_scale') else 1.0
        tolerance = 12.0 / max(scale, 1e-6)
        # Anchors are active only on an already selected item, preventing an
        # endpoint from making ordinary line selection surprising.
        for index in sorted(model.selected_measurement_indices, reverse=True):
            if not (0 <= index < len(model.measurements)):
                continue
            measurement = model.measurements[index]
            if measurement.slice_index != self.current_slice_index():
                continue
            start_distance = point_distance(scene_pos, measurement.start_point)
            end_distance = point_distance(scene_pos, measurement.end_point)
            if min(start_distance, end_distance) <= tolerance:
                self._target_measurement_id = measurement.id
                self._target_measurement_anchor = (
                    'start' if start_distance <= end_distance else 'end'
                )
                self._drag_mode = DragMode.MEASUREMENT_RESIZE
                self._annotation_interaction_changed = False
                return True

        clicked_measurement_index = check_measurement_hit(self.viewer, scene_pos)
        if clicked_measurement_index is not None:
            if not (modifiers & Qt.ControlModifier):
                model.clear_measurement_selection()
                model.clear_selection()
                model.clear_angle_measurement_selection()

            if (
                modifiers & Qt.ControlModifier
                and clicked_measurement_index in model.selected_measurement_indices
            ):
                model.deselect_measurement(clicked_measurement_index)
                self._drag_mode = DragMode.NONE
            else:
                model.select_measurement(clicked_measurement_index)
                self._target_measurement_id = model.measurements[
                    clicked_measurement_index
                ].id
                self._drag_mode = DragMode.MEASUREMENT_MOVE
                self._annotation_interaction_changed = False
            self.viewer.viewport().update()
            return True
        return False

    def _check_angle_interactions(self, scene_pos: QPointF, modifiers) -> bool:
        model = self.viewer.model
        if not model:
            return False
        scale = self.viewer.effective_scale() if hasattr(self.viewer, 'effective_scale') else 1.0
        tolerance = 12.0 / max(scale, 1e-6)
        angles = list(reversed(model.get_angle_measurements_for_slice(
            self.current_slice_index()
        )))
        for angle in angles:
            if angle.id not in model.selected_angle_measurement_ids:
                continue
            points = (
                ('point1', angle.point1),
                ('vertex', angle.vertex),
                ('point3', angle.point3),
            )
            nearest = min(points, key=lambda item: point_distance(scene_pos, item[1]))
            if point_distance(scene_pos, nearest[1]) <= tolerance:
                self._target_angle_id = angle.id
                self._target_angle_anchor = nearest[0]
                self._drag_mode = DragMode.ANGLE_RESIZE
                self._annotation_interaction_changed = False
                return True

        for angle in angles:
            hit = (
                point_distance(scene_pos, angle.point1) <= tolerance
                or point_distance(scene_pos, angle.vertex) <= tolerance
                or point_distance(scene_pos, angle.point3) <= tolerance
                or self._point_to_line_distance(scene_pos, angle.point1, angle.vertex) <= tolerance
                or self._point_to_line_distance(scene_pos, angle.vertex, angle.point3) <= tolerance
            )
            if not hit:
                continue
            if not (modifiers & Qt.ControlModifier):
                model.clear_selection()
                model.clear_measurement_selection()
                model.clear_angle_measurement_selection()
            if modifiers & Qt.ControlModifier and angle.id in model.selected_angle_measurement_ids:
                model.deselect_angle_measurement(angle.id)
                self._drag_mode = DragMode.NONE
            else:
                model.select_angle_measurement(
                    angle.id, multi=bool(modifiers & Qt.ControlModifier)
                )
                self._target_angle_id = angle.id
                self._drag_mode = DragMode.ANGLE_MOVE
                self._annotation_interaction_changed = False
            self.viewer.viewport().update()
            return True
        return False

    @staticmethod
    def _point_to_line_distance(point, start, end) -> float:
        from medimager.ui.tools.base_tool import point_to_line_distance
        return point_to_line_distance(point, start, end)

    def _check_annotation_label_interaction(self, scene_pos: QPointF) -> bool:
        hit_test = getattr(self.viewer, 'hit_test_annotation_label', None)
        if not callable(hit_test):
            return False
        hit = hit_test(self.viewer.mapFromScene(scene_pos))
        if not hit:
            return False
        self._target_label_id = hit[1] if isinstance(hit, tuple) else str(hit)
        self._drag_mode = DragMode.ANNOTATION_LABEL_MOVE
        return True

    @staticmethod
    def _calculate_angle_degrees(p1, vertex, p3, spacing=None) -> float:
        row_spacing, col_spacing = spacing or (1.0, 1.0)
        first = (
            (p1.x() - vertex.x()) * col_spacing,
            (p1.y() - vertex.y()) * row_spacing,
        )
        second = (
            (p3.x() - vertex.x()) * col_spacing,
            (p3.y() - vertex.y()) * row_spacing,
        )
        first_length = math.hypot(*first)
        second_length = math.hypot(*second)
        if not first_length or not second_length:
            return 0.0
        cosine = max(
            -1.0,
            min(
                1.0,
                (first[0] * second[0] + first[1] * second[1])
                / (first_length * second_length),
            ),
        )
        return math.degrees(math.acos(cosine))
            
    def _check_roi_interactions(self, scene_pos: QPointF, modifiers) -> bool:
        """检查ROI交互：ROI锚点 > 信息板 > ROI主体"""
        model = self.viewer.model
        view = self.viewer
        
        # 1. 检查是否击中某个已选中ROI的锚点
        rois_on_slice = [
            roi for roi in reversed(model.rois)
            if roi.slice_index == self.current_slice_index()
        ]
        for roi in rois_on_slice:
            if roi.selected:
                for i, (ay, ax) in enumerate(roi.get_anchor_points()):
                    # 将锚点坐标转换为场景坐标 QPointF
                    anchor_pos_scene = QPointF(ax, ay)
                    # 计算与鼠标点击位置的距离(手动计算以避免NotImplementedError)
                    dx = scene_pos.x() - anchor_pos_scene.x()
                    dy = scene_pos.y() - anchor_pos_scene.y()
                    scale = (
                        self.viewer.effective_scale()
                        if hasattr(self.viewer, 'effective_scale')
                        else max(math.hypot(self.viewer.transform().m11(), self.viewer.transform().m12()), 1e-6)
                    )
                    if math.hypot(dx, dy) <= 10.0 / max(scale, 1e-6):
                        self._drag_mode = DragMode.ROI_RESIZE
                        self._target_roi_id = roi.id
                        self._target_anchor_idx = i
                        self._roi_interaction_changed = False
                        roi.start_resize(i) # 通知ROI开始缩放
                        return True

        # 2. 检查是否击中某个信息板
        for roi in rois_on_slice:
            if roi.id in view.stats_box_positions:
                info_box_rect = view.get_stats_box_viewport_rect(roi.id)
                if info_box_rect.contains(view.mapFromScene(scene_pos)):
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
                self._roi_interaction_changed = False
                model.select_roi(roi.id, multi=modifiers & Qt.ControlModifier)
                return True

        # 4. 如果什么都没点中，则清除选择（除非按住Ctrl）
        if not (modifiers & Qt.ControlModifier):
            model.clear_selection()
            model.clear_measurement_selection()
            model.clear_angle_measurement_selection()
        
        return False

    def mouse_move_event(self, event: QMouseEvent):
        """根据当前的拖动模式执行相应的操作。"""
        super().mouse_move_event(event)
        
        # 如果拖拽模式为NONE，不执行任何拖拽操作
        if self._drag_mode == DragMode.NONE:
            event.accept()
            return
        
        event_pos = event.position().toPoint()
        delta = event_pos - self._last_mouse_pos
        scene_delta = self.viewer.last_mouse_scene_pos - self.viewer.mapToScene(self._last_mouse_pos)
        self._last_mouse_pos = event_pos
        
        model = self.viewer.model
        view = self.viewer

        if self._drag_mode == DragMode.BROWSE_IMAGES:
            # 浏览系列图像
            if model and model.get_slice_count() > 1:
                # 累积高采样率鼠标/触控板的小位移；每消费 6px 切一片，
                # 并保留不足一步的余量，避免慢拖永远达不到单事件阈值。
                self._browse_drag_remainder += delta.y()
                steps = int(self._browse_drag_remainder / 6)
                if steps:
                    target_index = max(
                        0,
                        min(
                            model.get_slice_count() - 1,
                            self.current_slice_index() + steps,
                        ),
                    )
                    if target_index != self.current_slice_index():
                        self.set_view_slice(target_index)
                    self._browse_drag_remainder -= steps * 6

        elif self._drag_mode == DragMode.ADJUST_WINDOW:
            # 调整窗口（亮度/对比度）
            if model:
                ww, wl = self.current_window()
                new_ww = max(1, ww + delta.x())
                new_wl = wl + delta.y()
                self.set_view_window(new_ww, new_wl)
                self._sync_window_level(new_ww, new_wl)

        elif self._drag_mode == DragMode.ZOOM:
            # 放大/缩小图像
            zoom_factor = 1.0 + delta.y() * 0.01  # 缩放敏感度
            if zoom_factor > 0.1:  # 防止缩放过小
                self.viewer.set_view_zoom(self.viewer.get_view_zoom() * zoom_factor)
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
                self._roi_interaction_changed = True
                # 不要在缩放时移动信息框，保持其原有位置
                view.scene.update()

        elif self._drag_mode == DragMode.ROI_MOVE and self._target_roi_id and model:
            roi = model.get_roi_by_id(self._target_roi_id)
            if roi:
                roi.move(scene_delta.y(), scene_delta.x())
                if scene_delta.x() or scene_delta.y():
                    self._roi_interaction_changed = True
                # 标签是固定设备尺寸；直接用本次 viewport 像素增量移动，
                # 避免高倍率下亚 scene 像素被 QPoint 取整吞掉。
                if roi.id in view.stats_box_positions:
                    stats_rect = view.get_stats_box_viewport_rect(roi.id)
                    stats_rect.translate(delta)
                    view.set_stats_box_viewport_rect(roi.id, stats_rect)
                view.scene.update()
        
        elif self._drag_mode == DragMode.INFO_BOX_MOVE and self._target_roi_id:
            if self._target_roi_id in view.stats_box_positions:
                stats_rect = view.get_stats_box_viewport_rect(self._target_roi_id)
                stats_rect.translate(delta)
                view.set_stats_box_viewport_rect(self._target_roi_id, stats_rect)
                view.scene.update()

        elif self._drag_mode in (DragMode.MEASUREMENT_MOVE, DragMode.MEASUREMENT_RESIZE) and self._target_measurement_id and model:
            measurement = model.get_measurement_by_id(self._target_measurement_id)
            if measurement:
                if self._drag_mode == DragMode.MEASUREMENT_MOVE:
                    measurement.start_point += scene_delta
                    measurement.end_point += scene_delta
                elif self._target_measurement_anchor == 'start':
                    measurement.start_point = QPointF(self.viewer.last_mouse_scene_pos)
                else:
                    measurement.end_point = QPointF(self.viewer.last_mouse_scene_pos)
                spacing = self.measurement_pixel_spacing()
                row_spacing, col_spacing = spacing or (1.0, 1.0)
                dx = (measurement.end_point.x() - measurement.start_point.x()) * col_spacing
                dy = (measurement.end_point.y() - measurement.start_point.y()) * row_spacing
                measurement.distance = math.hypot(dx, dy)
                measurement.unit = 'mm' if spacing is not None else 'px'
                if scene_delta.x() or scene_delta.y():
                    self._annotation_interaction_changed = True
                model.data_changed.emit()

        elif self._drag_mode in (DragMode.ANGLE_MOVE, DragMode.ANGLE_RESIZE) and self._target_angle_id and model:
            angle = model.get_angle_measurement_by_id(self._target_angle_id)
            if angle:
                if self._drag_mode == DragMode.ANGLE_MOVE:
                    angle.point1 += scene_delta
                    angle.vertex += scene_delta
                    angle.point3 += scene_delta
                else:
                    setattr(
                        angle,
                        self._target_angle_anchor or 'vertex',
                        QPointF(self.viewer.last_mouse_scene_pos),
                    )
                angle.angle_degrees = self._calculate_angle_degrees(
                    angle.point1,
                    angle.vertex,
                    angle.point3,
                    self.measurement_pixel_spacing(),
                )
                if scene_delta.x() or scene_delta.y():
                    self._annotation_interaction_changed = True
                model.data_changed.emit()

        elif self._drag_mode == DragMode.ANNOTATION_LABEL_MOVE and self._target_label_id:
            mover = getattr(self.viewer, 'move_annotation_label', None)
            if callable(mover):
                mover(self._target_label_id, delta)
            else:
                offsets = getattr(self.viewer, 'annotation_label_offsets', None)
                if isinstance(offsets, dict):
                    offsets[self._target_label_id] = offsets.get(
                        self._target_label_id, QPointF()
                    ) + QPointF(delta)
                    self.viewer.viewport().update()

        event.accept()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件，重置拖动状态。"""
        self._finish_drag_interaction()
        event.accept()

    def _finish_drag_interaction(self) -> None:
        """提交或取消当前拖拽，工具切换时也保证 ROI 状态进入撤销栈。"""
        model = self.viewer.model
        completed_mode = self._drag_mode
        if self._drag_mode == DragMode.ROI_RESIZE and self._target_roi_id and model:
            roi = model.get_roi_by_id(self._target_roi_id)
            if roi:
                roi.end_resize()

        if (
            model
            and self._roi_interaction_changed
            and completed_mode in (DragMode.ROI_MOVE, DragMode.ROI_RESIZE)
        ):
            marker = getattr(model, 'mark_annotations_dirty', None)
            if callable(marker):
                marker()
            # 同一 model 可能同时绑定到多个 ViewFrame；结束编辑时通知
            # 所有观察者重绘共享 ROI，而不只刷新发起交互的 scene。
            model.data_changed.emit()

        if model and self._annotation_interaction_changed and completed_mode in (
            DragMode.MEASUREMENT_MOVE,
            DragMode.MEASUREMENT_RESIZE,
            DragMode.ANGLE_MOVE,
            DragMode.ANGLE_RESIZE,
        ):
            model.mark_annotations_dirty()
            model.data_changed.emit()

        self._drag_mode = DragMode.NONE
        self._target_roi_id = None
        self._target_anchor_idx = None
        self._target_measurement_id = None
        self._target_measurement_anchor = None
        self._target_angle_id = None
        self._target_angle_anchor = None
        self._target_label_id = None
        self._roi_interaction_changed = False
        self._annotation_interaction_changed = False
        self._browse_drag_remainder = 0
        self.viewer.setCursor(Qt.ArrowCursor)
        self.viewer.scene.update()

    def wheel_event(self, event: QWheelEvent):
        """处理滚轮事件，实现缩放或切片切换。"""
        modifiers = event.modifiers()
        if modifiers not in (Qt.ControlModifier, Qt.NoModifier):
            event.ignore()
            return

        if modifiers != self._wheel_remainder_modifiers:
            # 修饰键变化意味着交互语义已经改变，不能把浏览切片时残留的
            # 部分刻度带入 Ctrl+缩放（反之亦然）。
            self._wheel_angle_remainder = 0
            self._wheel_pixel_remainder = 0
            self._wheel_remainder_modifiers = modifiers

        angle_delta = event.angleDelta().y()
        if angle_delta:
            # 标准滚轮以 120 为一格；部分设备会一次上报多格或连续上报
            # 小于一格的 angleDelta，因此必须累计并按完整刻度消费。
            self._wheel_pixel_remainder = 0
            self._wheel_angle_remainder += angle_delta
            steps = int(abs(self._wheel_angle_remainder) / 120)
            if steps == 0:
                event.accept()
                return
            vertical_delta = self._wheel_angle_remainder
            consumed = steps * 120 * (1 if vertical_delta > 0 else -1)
            self._wheel_angle_remainder -= consumed
        else:
            pixel_delta = event.pixelDelta().y()
            if pixel_delta == 0:
                event.ignore()
                return
            # 高精度触控板只提供 pixelDelta。累积到 15px 再消费一步，
            # 既保留响应性，也避免每个 1px 事件都切一片。
            self._wheel_angle_remainder = 0
            self._wheel_pixel_remainder += pixel_delta
            steps = int(abs(self._wheel_pixel_remainder) / 15)
            if steps == 0:
                event.accept()
                return
            vertical_delta = self._wheel_pixel_remainder
            consumed = steps * 15 * (1 if vertical_delta > 0 else -1)
            self._wheel_pixel_remainder -= consumed

        if modifiers == Qt.ControlModifier:
            for _ in range(steps):
                if vertical_delta > 0:
                    self.viewer.zoom_in()
                else:
                    self.viewer.zoom_out()
            self._sync_zoom_pan()
            event.accept()
        elif modifiers == Qt.NoModifier:
            if self.viewer.model and self.viewer.model.get_slice_count() > 1:
                reverse = self._bool_setting("interaction.wheel_reverse", False)
                direction = (-steps if vertical_delta > 0 else steps)
                if reverse:
                    direction *= -1
                target_index = max(
                    0,
                    min(
                        self.viewer.model.get_slice_count() - 1,
                        self.current_slice_index() + direction,
                    ),
                )
                self.set_view_slice(target_index)

                # 切片切换后，如果鼠标在图像区域内，主动更新像素信息
                if hasattr(self.viewer, 'last_mouse_scene_pos') and self.viewer.last_mouse_scene_pos:
                    if hasattr(self.viewer, '_update_pixel_info'):
                        self.viewer._update_pixel_info(self.viewer.last_mouse_scene_pos)

                event.accept()

    def _bool_setting(self, key: str, default: bool) -> bool:
        try:
            value = get_settings_manager().get_setting(key, default)
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "on")
            return bool(value)
        except Exception:
            return default

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
                with model.annotation_transaction():
                    # 一次 Delete 同时删除三类选择，但只形成一个撤销步骤。
                    if model.selected_measurement_indices:
                        deleted_measurement_ids = model.delete_selected_measurements()
                        self.logger.info(f"删除了 {len(deleted_measurement_ids)} 个测量")
                        deleted_something = bool(deleted_measurement_ids) or deleted_something

                    if model.selected_indices:
                        deleted_roi_ids = model.delete_selected_rois()
                        for roi_id in deleted_roi_ids:
                            if hasattr(self.viewer, 'stats_box_positions') and roi_id in self.viewer.stats_box_positions:
                                del self.viewer.stats_box_positions[roi_id]
                        deleted_something = bool(deleted_roi_ids) or deleted_something

                    if model.selected_angle_measurement_ids:
                        deleted_angle_ids = model.delete_selected_angle_measurements()
                        deleted_something = bool(deleted_angle_ids) or deleted_something
                
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
                transform = self.viewer.transform()
                zoom_factor = (
                    self.viewer.get_view_zoom()
                    if hasattr(self.viewer, 'get_view_zoom')
                    else max(1e-6, math.hypot(transform.m11(), transform.m12()))
                )
                pan_offset = self.viewer.mapToScene(self.viewer.viewport().rect().center())
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
        self.logger.info(f"当前切片: {self.current_slice_index()}")
        self.logger.info(f"选中索引: {list(model.selected_measurement_indices)}")
        
        current_slice_measurements = model.get_measurements_for_slice(
            self.current_slice_index()
        )
        self.logger.info(f"当前切片数量: {len(current_slice_measurements)}")
        
        for i, measurement in enumerate(model.measurements):
            # 计算线段长度
            dx = measurement.end_point.x() - measurement.start_point.x()
            dy = measurement.end_point.y() - measurement.start_point.y()
            length = math.sqrt(dx * dx + dy * dy)
            
            selected = "是" if i in model.selected_measurement_indices else "否"
            on_current_slice = "是" if measurement.slice_index == self.current_slice_index() else "否"
            
            self.logger.info(f"测量{i}: 距离={measurement.distance:.1f}{measurement.unit}, "
                           f"长度={length:.1f}, 选中={selected}, 当前切片={on_current_slice}")
            
            if length < 0.1:
                self.logger.warning(f"  警告：测量{i}长度过短")
        
        self.logger.info("=" * 40)
