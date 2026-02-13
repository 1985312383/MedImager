# 测量工具 
from medimager.ui.tools.base_tool import BaseTool
from medimager.core.image_data_model import MeasurementData
from medimager.utils.logger import get_logger
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QCursor, QKeyEvent
from PySide6.QtCore import Qt, QPointF, QRectF
from typing import Optional
import math
import uuid


class MeasurementTool(BaseTool):
    """
    测量工具，用于测量两个像素点之间的实际距离。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.logger = get_logger(__name__)
        self.measuring = False
        self.start_point = None
        self.end_point = None
        self.dragging = False
        self.dragging_anchor = None
        self.drag_offset = QPointF()
        self.measurement_completed = False
        
        # 当前编辑的测量ID（用于拖拽编辑已有测量）
        self.editing_measurement_id: Optional[str] = None

    def _get_style_from_settings(self):
        """从设置中获取测量工具的样式"""
        try:
            from medimager.utils.theme_manager import get_theme_settings
            
            # 使用统一的主题设置读取函数
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
            # 默认设置
            return (
                "#00FF00",  # line_color
                "#00FF00",  # anchor_color
                "#FFFFFF",  # text_color
                "#00000080", # background_color
                2,          # line_width
                8,          # anchor_size
                14,         # font_size
            )

    def activate(self):
        """激活测量工具"""
        self.viewer.setCursor(Qt.CrossCursor)

    def deactivate(self):
        """停用测量工具"""
        self.viewer.setCursor(Qt.ArrowCursor)
        if self.dragging:
            self._stop_dragging()

    def _reset_measurement(self):
        """重置测量状态"""
        self.start_point = None
        self.end_point = None
        self.measuring = False
        self.dragging = False
        self.dragging_anchor = None
        self.drag_offset = QPointF(0, 0)
        self.measurement_completed = False
        self.editing_measurement_id = None  # 清除编辑状态
        
        if hasattr(self, '_preview_point'):
            self._preview_point = None
        
        self.viewer.setCursor(Qt.CrossCursor)
        
        if hasattr(self.viewer, 'clear_measurement_line'):
            self.viewer.clear_measurement_line()
        else:
            self.viewer.viewport().update()

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，设置测量点"""
        super().mouse_press_event(event)
        
        if self._press_is_outside:
            return
            
        if event.button() == Qt.LeftButton:
            model = self.viewer.model
            if not model:
                return
                
            click_pos = self.viewer.last_mouse_scene_pos
            
            # 检查是否点击了现有测量的锚点
            clicked_measurement_index, anchor_type = self._check_measurement_anchor_hit(click_pos)
            
            if clicked_measurement_index is not None:
                # 选中该测量并开始拖拽
                model.clear_measurement_selection()
                model.select_measurement(clicked_measurement_index)
                
                measurement = model.measurements[clicked_measurement_index]
                self.editing_measurement_id = measurement.id
                self.start_point = measurement.start_point
                self.end_point = measurement.end_point
                self.measurement_completed = True
                
                self._start_anchor_dragging(anchor_type, event)
                event.accept()
                return
            
            # 检查是否点击了现有测量（非锚点区域）
            clicked_measurement_index = self._check_measurement_hit(click_pos)
            
            if clicked_measurement_index is not None:
                # 选中该测量
                if not (event.modifiers() & Qt.ControlModifier):
                    model.clear_measurement_selection()
                
                if clicked_measurement_index in model.selected_measurement_indices:
                    model.deselect_measurement(clicked_measurement_index)
                else:
                    model.select_measurement(clicked_measurement_index)
                
                event.accept()
                return
            
            # 开始新的测量
            if self.measurement_completed and self.end_point:
                # 如果之前有完成的测量，重置开始新测量
                self._reset_measurement()
                
            if not self.measuring:
                self._reset_measurement()
                self.start_point = click_pos
                self.measuring = True
                self.viewer.viewport().update()
                event.accept()
            elif not self.end_point:
                self.end_point = click_pos
                self._complete_measurement()
                self.dragging = False
                self.dragging_anchor = None
                event.accept()
                
        elif event.button() == Qt.RightButton:
            if self.measuring and not self.end_point:
                self._reset_measurement()
                self.viewer.viewport().update()
                event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件"""
        super().mouse_move_event(event)
        
        if self.measuring and self.start_point and not self.end_point:
            self._preview_point = self.viewer.last_mouse_scene_pos
            self.viewer.viewport().update()
            event.accept()
        elif self.dragging and self.dragging_anchor and self.measurement_completed:
            self._update_dragging(event)
            event.accept()
        elif self.end_point and not self.dragging and self.measurement_completed:
            self._update_cursor_for_hover()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件"""
        super().mouse_release_event(event)
        
        if event.button() == Qt.LeftButton:
            if self.dragging:
                self._stop_dragging()
                event.accept()
            
            if self.measurement_completed:
                self.measuring = False

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件"""
        super().key_press_event(event)
        
        if event.key() == Qt.Key_Delete:
            model = self.viewer.model
            if not model:
                return
            
            deleted_something = False
            
            # 优先删除选中的测量
            if model.selected_measurement_indices:
                deleted_ids = model.delete_selected_measurements()
                self.logger.info(f"{self.tr('删除了')} {len(deleted_ids)} {self.tr('个测量')}")
                deleted_something = True
            
            # 如果没有选中的测量，检查是否有正在创建的测量线
            elif self.end_point and not self.editing_measurement_id:
                self._reset_measurement()
                deleted_something = True
            
            if deleted_something:
                self.viewer.viewport().update()
                event.accept()
                
        elif event.key() == Qt.Key_Escape:
            if self.measuring and not self.end_point:
                self._reset_measurement()
                self.viewer.viewport().update()
                event.accept()

    def _check_anchor_hit(self, pos: QPointF) -> Optional[str]:
        """检查点击位置是否在锚点上"""
        if not self.end_point or not self.start_point:
            return None
        
        transform = self.viewer.transform()
        scale_factor = transform.m11()
        screen_detection_radius = 20
        scene_detection_radius = screen_detection_radius / scale_factor
            
        start_distance = self._calculate_pixel_distance(pos, self.start_point)
        end_distance = self._calculate_pixel_distance(pos, self.end_point)
        
        if start_distance <= scene_detection_radius and end_distance <= scene_detection_radius:
            return 'start' if start_distance < end_distance else 'end'
        elif start_distance <= scene_detection_radius:
            return 'start'
        elif end_distance <= scene_detection_radius:
            return 'end'
            
        return None

    def _start_anchor_dragging(self, anchor: str, event: QMouseEvent):
        """开始拖拽锚点"""
        if not self.measurement_completed or not self.end_point or not self.start_point:
            return
            
        if anchor not in ['start', 'end']:
            return
            
        if self.dragging:
            return
            
        self.dragging = True
        self.dragging_anchor = anchor
        self.drag_offset = QPointF(0, 0)
        self.viewer.setCursor(Qt.ClosedHandCursor)

    def _update_dragging(self, event: QMouseEvent):
        """更新拖拽状态"""
        if not self.dragging or not self.dragging_anchor or not self.measurement_completed:
            return
            
        if self.dragging_anchor not in ['start', 'end']:
            self._stop_dragging()
            return
            
        current_pos = self.viewer.last_mouse_scene_pos
        
        if self.dragging_anchor == 'start':
            self.start_point = current_pos
        elif self.dragging_anchor == 'end':
            self.end_point = current_pos
        
        # 如果正在编辑现有测量，实时更新距离
        if self.editing_measurement_id:
            model = self.viewer.model
            if model:
                measurement = model.get_measurement_by_id(self.editing_measurement_id)
                if measurement:
                    real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
                    measurement.start_point = self.start_point
                    measurement.end_point = self.end_point
                    measurement.distance = real_distance
                    measurement.unit = unit
                    model.data_changed.emit()
        
        if hasattr(self.viewer, 'set_measurement_line'):
            real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
            self.viewer.set_measurement_line(self.start_point, self.end_point, real_distance, unit)
        
        self.viewer.viewport().update()

    def _stop_dragging(self):
        """停止拖拽"""
        if not self.dragging:
            return
            
        self.dragging = False
        self.dragging_anchor = None
        self.drag_offset = QPointF(0, 0)
        self.editing_measurement_id = None  # 完成编辑
        self.viewer.setCursor(Qt.CrossCursor)

    def _update_cursor_for_hover(self):
        """根据鼠标悬停位置更新光标样式"""
        if not self.end_point:
            return
            
        current_pos = self.viewer.last_mouse_scene_pos
        anchor_hit = self._check_anchor_hit(current_pos)
        
        if anchor_hit:
            self.viewer.setCursor(Qt.OpenHandCursor)
        else:
            self.viewer.setCursor(Qt.CrossCursor)

    def _complete_measurement(self):
        """完成测量并显示结果"""
        if not self.start_point or not self.end_point:
            return
            
        model = self.viewer.model
        if not model:
            return
            
        real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
        
        if self.editing_measurement_id:
            # 更新现有测量
            measurement = model.get_measurement_by_id(self.editing_measurement_id)
            if measurement:
                measurement.start_point = self.start_point
                measurement.end_point = self.end_point
                measurement.distance = real_distance
                measurement.unit = unit
                model.data_changed.emit()
        else:
            # 创建新测量
            measurement_id = str(uuid.uuid4())
            measurement_data = MeasurementData(
                id=measurement_id,
                slice_index=model.current_slice_index,
                start_point=self.start_point,
                end_point=self.end_point,
                distance=real_distance,
                unit=unit
            )
            
            model.add_measurement(measurement_data)
        
        # 重要修复：完成测量后清理工具状态，避免与后续交互冲突
        self.measurement_completed = False  # 重置完成状态
        self.start_point = None            # 清除临时起点
        self.end_point = None              # 清除临时终点
        self.measuring = False             # 重置测量状态
        self.editing_measurement_id = None # 清除编辑状态
        
        # 清除预览点
        if hasattr(self, '_preview_point'):
            self._preview_point = None
        
        # 清除ImageViewer中的临时测量线（如果存在）
        if hasattr(self.viewer, 'clear_measurement_line'):
            self.viewer.clear_measurement_line()

    def _calculate_real_distance(self, point1: QPointF, point2: QPointF) -> tuple[float, str]:
        """根据DICOM信息计算实际距离"""
        model = self.viewer.model
        if not model or not model.has_image():
            return 0.0, "px"

        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()

        dicom_header = model.dicom_header
        if not dicom_header:
            # 无DICOM头信息，返回像素距离
            pixel_distance = math.sqrt(dx * dx + dy * dy)
            return pixel_distance, "px"

        pixel_spacing = dicom_header.get('Pixel Spacing', None)
        if not pixel_spacing or len(pixel_spacing) < 2:
            pixel_spacing = dicom_header.get('Imager Pixel Spacing', None)

        if pixel_spacing and len(pixel_spacing) >= 2:
            row_spacing = float(pixel_spacing[0])  # dy方向
            col_spacing = float(pixel_spacing[1])  # dx方向
            real_distance = math.sqrt((dx * col_spacing) ** 2 + (dy * row_spacing) ** 2)
            return real_distance, "mm"

        # 无像素间距信息，返回像素距离
        pixel_distance = math.sqrt(dx * dx + dy * dy)
        return pixel_distance, "px"

    def _calculate_pixel_distance(self, point1: QPointF, point2: QPointF) -> float:
        """计算两点间的像素距离"""
        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()
        return math.sqrt(dx * dx + dy * dy)

    def _check_measurement_hit(self, pos: QPointF) -> Optional[int]:
        """检查点击位置是否命中某个测量线"""
        model = self.viewer.model
        if not model:
            return None
            
        current_slice_measurements = model.get_measurements_for_slice(model.current_slice_index)
        
        for i, measurement in enumerate(current_slice_measurements):
            # 计算点到线段的距离
            line_distance = self._point_to_line_distance(pos, measurement.start_point, measurement.end_point)
            
            # 使用屏幕像素距离进行检测
            transform = self.viewer.transform()
            scale_factor = transform.m11()
            screen_detection_radius = 10  # 屏幕像素
            scene_detection_radius = screen_detection_radius / scale_factor
            
            if line_distance <= scene_detection_radius:
                # 找到对应的全局索引
                for global_idx, global_measurement in enumerate(model.measurements):
                    if global_measurement.id == measurement.id:
                        return global_idx
        
        return None

    def _check_measurement_anchor_hit(self, pos: QPointF) -> tuple[Optional[int], Optional[str]]:
        """检查点击位置是否命中某个测量的锚点"""
        model = self.viewer.model
        if not model:
            return None, None
            
        current_slice_measurements = model.get_measurements_for_slice(model.current_slice_index)
        
        transform = self.viewer.transform()
        scale_factor = transform.m11()
        screen_detection_radius = 15  # 屏幕像素
        scene_detection_radius = screen_detection_radius / scale_factor
        
        for i, measurement in enumerate(current_slice_measurements):
            start_distance = self._calculate_pixel_distance(pos, measurement.start_point)
            end_distance = self._calculate_pixel_distance(pos, measurement.end_point)
            
            if start_distance <= scene_detection_radius or end_distance <= scene_detection_radius:
                # 找到对应的全局索引
                for global_idx, global_measurement in enumerate(model.measurements):
                    if global_measurement.id == measurement.id:
                        anchor_type = 'start' if start_distance < end_distance else 'end'
                        return global_idx, anchor_type
        
        return None, None

    def _point_to_line_distance(self, point: QPointF, line_start: QPointF, line_end: QPointF) -> float:
        """计算点到线段的最短距离"""
        # 向量计算
        line_vec = line_end - line_start
        point_vec = point - line_start
        
        line_len_sq = line_vec.x() ** 2 + line_vec.y() ** 2
        if line_len_sq == 0:
            # 线段长度为0，返回点到起点的距离
            return self._calculate_pixel_distance(point, line_start)
        
        # 计算投影参数
        t = max(0, min(1, (point_vec.x() * line_vec.x() + point_vec.y() * line_vec.y()) / line_len_sq))
        
        # 计算线段上最近的点
        projection = line_start + t * line_vec
        
        # 返回距离
        return self._calculate_pixel_distance(point, projection)

    def draw_temporary_shape(self, painter):
        """在图像上绘制临时的测量线和预览信息"""
        model = self.viewer.model
        if not model:
            return
            
        from PySide6.QtGui import QPen, QColor, QFont, QBrush
        from PySide6.QtCore import QPointF, QRectF, Qt
            
        line_color, anchor_color, text_color, bg_color, line_width, anchor_size, font_size = self._get_style_from_settings()
        
        painter.save()

        # 注意：保存的测量线现在由ImageViewer统一绘制，这里只绘制临时的正在创建的测量线
        
        # 绘制当前正在创建的测量线
        if self.start_point and not self.editing_measurement_id:
            # 确定要绘制的终点
            draw_end_point = self.end_point if self.end_point else getattr(self, '_preview_point', None)
            
            if draw_end_point:
                # 绘制线
                pen = QPen(QColor(line_color), line_width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLine(self.start_point, draw_end_point)
                
                # 绘制锚点
                painter.setBrush(QColor(anchor_color))
                painter.setPen(Qt.NoPen)
                pixel_size = 1.0 / self.viewer.transform().m11()
                scaled_anchor_size = anchor_size * pixel_size
                
                painter.drawEllipse(self.start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
                painter.drawEllipse(draw_end_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
                
                # 绘制距离文本
                if self.end_point:
                    real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
                else:
                    real_distance, unit = self._calculate_real_distance(self.start_point, draw_end_point)
                
                font = QFont()
                font.setPixelSize(font_size)
                painter.setFont(font)

                text = f"{real_distance:.2f} {unit}"
                metrics = painter.fontMetrics()
                text_rect = metrics.boundingRect(text).adjusted(-4, -2, 4, 2)
                
                mid_point = (self.start_point + draw_end_point) / 2
                text_rect.moveCenter(mid_point.toPoint())
                
                painter.setBrush(QColor(bg_color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(text_rect, 5, 5)

                painter.setPen(QColor(text_color))
                painter.drawText(text_rect, Qt.AlignCenter, text)

        painter.restore()