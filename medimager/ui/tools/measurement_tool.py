# 测量工具 
from medimager.ui.tools.base_tool import BaseTool
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QCursor, QKeyEvent
from PySide6.QtCore import Qt, QPointF, QRectF
from typing import Optional
import math


class MeasurementTool(BaseTool):
    """
    测量工具，用于测量两个像素点之间的实际距离。
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.measuring = False
        self.start_point = None
        self.end_point = None
        self.dragging = False
        self.dragging_anchor = None
        self.drag_offset = QPointF()
        self.measurement_completed = False

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
            if self.measurement_completed and self.end_point:
                click_pos = self.viewer.last_mouse_scene_pos
                anchor_hit = self._check_anchor_hit(click_pos)
                
                if anchor_hit:
                    self._start_anchor_dragging(anchor_hit, event)
                    event.accept()
                    return
                else:
                    self._reset_measurement()
                    self.start_point = click_pos
                    self.measuring = True
                    self.viewer.viewport().update()
                    event.accept()
            elif not self.measuring:
                self._reset_measurement()
                self.start_point = self.viewer.last_mouse_scene_pos
                self.measuring = True
                self.viewer.viewport().update()
                event.accept()
            elif not self.end_point:
                self.end_point = self.viewer.last_mouse_scene_pos
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
            if self.end_point:
                self._reset_measurement()
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
            
        real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
        
        self.measurement_completed = True
        
        if hasattr(self.viewer, 'set_measurement_line'):
            self.viewer.set_measurement_line(self.start_point, self.end_point, real_distance, unit)

    def _calculate_real_distance(self, point1: QPointF, point2: QPointF) -> tuple[float, str]:
        """根据DICOM信息计算实际距离"""
        model = self.viewer.model
        if not model or not model.has_image():
            return 0.0, "mm"
            
        pixel_distance = self._calculate_pixel_distance(point1, point2)
        
        dicom_header = model.dicom_header
        if not dicom_header:
            return 0.0, "mm"
            
        pixel_spacing = dicom_header.get('Pixel Spacing', None)
        if pixel_spacing and len(pixel_spacing) >= 2:
            row_spacing = float(pixel_spacing[0])
            col_spacing = float(pixel_spacing[1])
            avg_spacing = (row_spacing + col_spacing) / 2.0
            real_distance = pixel_distance * avg_spacing
            return real_distance, "mm"
            
        imager_pixel_spacing = dicom_header.get('Imager Pixel Spacing', None)
        if imager_pixel_spacing and len(imager_pixel_spacing) >= 2:
            row_spacing = float(imager_pixel_spacing[0])
            col_spacing = float(imager_pixel_spacing[1])
            avg_spacing = (row_spacing + col_spacing) / 2.0
            real_distance = pixel_distance * avg_spacing
            return real_distance, "mm"
            
        return 0.0, "mm"

    def _calculate_pixel_distance(self, point1: QPointF, point2: QPointF) -> float:
        """计算两点间的像素距离"""
        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()
        return math.sqrt(dx * dx + dy * dy)

    def draw_temporary_shape(self, painter):
        """在图像上绘制临时的测量线和预览信息"""
        if not self.start_point:
            return

        from PySide6.QtGui import QPen, QColor, QFont, QBrush
        from PySide6.QtCore import QPointF, QRectF, Qt
            
        line_color, anchor_color, text_color, bg_color, line_width, anchor_size, font_size = self._get_style_from_settings()
        
        painter.save()

        # 确定要绘制的终点
        draw_end_point = self.end_point if self.end_point else getattr(self, '_preview_point', None)
        
        if draw_end_point:
            # 1. 绘制线
            pen = QPen(QColor(line_color), line_width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(self.start_point, draw_end_point)
            
            # 2. 绘制锚点
            painter.setBrush(QColor(anchor_color))
            painter.setPen(Qt.NoPen)
            pixel_size = 1.0 / self.viewer.transform().m11()
            scaled_anchor_size = anchor_size * pixel_size
            
            painter.drawEllipse(self.start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
            painter.drawEllipse(draw_end_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
            
            # 3. 绘制距离文本
            if self.end_point:
                real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
            else:
                real_distance, unit = self._calculate_real_distance(self.start_point, draw_end_point)
                
            if unit == "mm" and real_distance > 0:
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
        else:
            # 只绘制起始点
            painter.setBrush(QColor(anchor_color))
            painter.setPen(Qt.NoPen)
            pixel_size = 1.0 / self.viewer.transform().m11()
            scaled_anchor_size = anchor_size * pixel_size
            painter.drawEllipse(self.start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
        
        painter.restore() 