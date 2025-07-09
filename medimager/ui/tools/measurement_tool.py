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
    
    功能：
    - 第一次点击设置起始点
    - 第二次点击设置终点，完成测量
    - 测量完成后可以拖拽锚点或整条线段
    - 第三次点击重新开始测量
    - 根据DICOM文件中的像素间距信息计算实际距离（mm）
    - 边界检查：起始点和终止点不能超出图像边界
    - 实时显示：鼠标移动时显示预览距离
    - 支持右键点击取消测量
    - 支持Del键删除线段
    """

    def __init__(self, viewer: QGraphicsView):
        super().__init__(viewer)
        self.measuring = False
        self.start_point = None
        self.end_point = None
        self.completed_measurements = []  # 存储完成的测量线
        self.dragging = False
        self.dragging_anchor = None  # 'start' 或 'end'
        self.dragging_line = False
        self.drag_offset = QPointF()
        self.viewer = viewer
        
        # 增加一个变量，明确标记测量是否已完成
        self.measurement_completed = False
        
        # 获取设置管理器
        self._init_settings()
        
    def _init_settings(self):
        """初始化设置管理器"""
        try:
            from medimager.utils.settings import SettingsManager
            self.settings_manager = SettingsManager()
        except Exception as e:
            self.logger.warning(f"初始化设置管理器失败: {e}")
            self.settings_manager = None

    def _get_style_from_settings(self):
        """从设置中获取测量工具的样式"""
        prefix = 'measurement.custom'
        
        return (
            self.settings_manager.get_setting(f'{prefix}.line_color', "#00FF00"),
            self.settings_manager.get_setting(f'{prefix}.anchor_color', "#00FF00"),
            self.settings_manager.get_setting(f'{prefix}.text_color', "#FFFFFF"),
            self.settings_manager.get_setting(f'{prefix}.background_color', "#00000080"),
            self.settings_manager.get_setting(f'{prefix}.line_width', 2),
            self.settings_manager.get_setting(f'{prefix}.anchor_size', 8),
            self.settings_manager.get_setting(f'{prefix}.font_size', 14),
        )

    def activate(self):
        """激活测量工具"""
        self.viewer.setCursor(Qt.CrossCursor)
        # 更新状态栏显示工具提示
        self._update_status_message(self.tr("测量工具已激活 - 点击设置起始点"))

    def deactivate(self):
        """停用测量工具"""
        self.viewer.setCursor(Qt.ArrowCursor)
        # 停止拖拽
        if self.dragging:
            self._stop_dragging()
        # 保留测量结果，不清除状态栏信息
        # self._clear_status_message()

    def _reset_measurement(self):
        """重置测量状态"""
        self.start_point = None
        self.end_point = None
        self.measuring = False
        self.dragging = False
        self.dragging_anchor = None
        
        # 增加这行来清除完成状态
        self.measurement_completed = False
        
        # 清除预览点，防止显示临时连线
        if hasattr(self, '_preview_point'):
            self._preview_point = None
        
        # 清除图像查看器中的测量线
        if hasattr(self.viewer, 'clear_measurement_line'):
            self.viewer.clear_measurement_line()
        else:
            self.viewer.viewport().update()

    def mouse_press_event(self, event: QMouseEvent):
        """处理鼠标按下事件，设置测量点或开始拖拽"""
        super().mouse_press_event(event)
        
        if self._press_is_outside:  # 检查是否在图像边界外
            return
            
        if event.button() == Qt.LeftButton:
            # 如果测量已完成，检查是否点击在锚点或线段上进行拖拽
            if self.measurement_completed and self.end_point:
                anchor_hit = self._check_anchor_hit(self.viewer.last_mouse_scene_pos)
                if anchor_hit:
                    self._start_anchor_dragging(anchor_hit, event)
                    event.accept()
                    return
                    
                # 检查是否点击在测量线上
                if self._is_click_on_measurement_line(self.viewer.last_mouse_scene_pos):
                    self._start_line_dragging(event)
                    event.accept()
                    return
            
            if not self.measuring:
                # 第一次点击：设置起始点
                self._reset_measurement() # 确保开始全新测量
                self.start_point = self.viewer.last_mouse_scene_pos
                self.measuring = True
                self._update_status_message(self.tr("已设置起始点 - 点击设置终点（右键取消）"))
                self.viewer.viewport().update()
                event.accept()
            elif not self.end_point:
                # 第二次点击：设置终点并完成测量
                self.end_point = self.viewer.last_mouse_scene_pos
                self._complete_measurement()
                event.accept()
            else:
                # 第三次点击：重新开始测量
                self._reset_measurement()
                # 立即设置新的起始点，避免显示临时连线
                self.start_point = self.viewer.last_mouse_scene_pos
                self.measuring = True
                self._update_status_message(self.tr("已设置起始点 - 点击设置终点（右键取消）"))
                self.viewer.viewport().update()
                event.accept()
                
        elif event.button() == Qt.RightButton:
            # 右键点击取消测量
            if self.measuring and not self.end_point:
                self._reset_measurement()
                self._update_status_message(self.tr("测量已取消"))
                self.viewer.viewport().update()
                event.accept()

    def mouse_move_event(self, event: QMouseEvent):
        """处理鼠标移动事件，更新预览线、实时距离显示或拖拽"""
        super().mouse_move_event(event)
        
        if self.dragging:
            # 处理拖拽
            self._update_dragging(event)
            event.accept()
        elif self.measuring and self.start_point and not self.end_point:
            # 使用安全坐标作为预览终点
            self._preview_point = self.viewer.last_mouse_scene_pos
            self._update_preview_distance()
            self.viewer.viewport().update()
            event.accept()
        elif self.end_point:
            # 更新鼠标指针样式
            self._update_cursor_for_hover()
            # 显示最终结果
            self._show_final_measurement()

    def mouse_release_event(self, event: QMouseEvent):
        """处理鼠标释放事件"""
        super().mouse_release_event(event)
        
        if self.dragging and event.button() == Qt.LeftButton:
            self._stop_dragging()
            event.accept()
        # 测量完成逻辑已在mouse_press_event中处理

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件"""
        super().key_press_event(event)
        
        if event.key() == Qt.Key_Delete:
            # Del键删除线段
            if self.end_point:
                self._reset_measurement()
                self._update_status_message(self.tr("测量线已删除"))
                self.viewer.viewport().update()
                event.accept()
        elif event.key() == Qt.Key_Escape:
            # Esc键取消当前测量
            if self.measuring and not self.end_point:
                self._reset_measurement()
                self._update_status_message(self.tr("测量已取消"))
                self.viewer.viewport().update()
                event.accept()

    def _check_anchor_hit(self, pos: QPointF) -> Optional[str]:
        """检查点击位置是否在锚点上"""
        if not self.end_point or not self.start_point:
            return None
        
        # 计算固定屏幕像素大小的检测半径
        transform = self.viewer.transform()
        scale_factor = transform.m11()
        screen_detection_radius = 15  # 增加检测半径从10到15像素
        scene_detection_radius = screen_detection_radius / scale_factor
            
        # 检查起始点
        start_distance = self._calculate_pixel_distance(pos, self.start_point)
        if start_distance <= scene_detection_radius:
            return 'start'
            
        # 检查终点
        end_distance = self._calculate_pixel_distance(pos, self.end_point)
        if end_distance <= scene_detection_radius:
            return 'end'
            
        return None

    def _start_anchor_dragging(self, anchor: str, event: QMouseEvent):
        """开始拖拽锚点"""
        self.dragging = True
        self.dragging_anchor = anchor
        # 记录当前鼠标位置，不需要偏移
        self.drag_offset = QPointF(0, 0)
        self.viewer.setCursor(Qt.ClosedHandCursor)
        
        if anchor == 'start':
            self._update_status_message(self.tr("拖拽起始点"))
        else:
            self._update_status_message(self.tr("拖拽终点"))

    def _start_line_dragging(self, event: QMouseEvent):
        """开始拖拽整条线"""
        self.dragging = True
        self.dragging_anchor = 'line'
        # 记录当前鼠标位置和线段起始点的偏移
        self.drag_offset = self.viewer.last_mouse_scene_pos - self.start_point
        self.viewer.setCursor(Qt.ClosedHandCursor)
        self._update_status_message(self.tr("拖拽测量线"))

    def _update_dragging(self, event: QMouseEvent):
        """更新拖拽状态"""
        if not self.dragging:
            return
            
        current_pos = self.viewer.last_mouse_scene_pos
        
        if self.dragging_anchor == 'start':
            # 直接设置起始点为当前鼠标位置
            self.start_point = current_pos
        elif self.dragging_anchor == 'end':
            # 直接设置终点为当前鼠标位置
            self.end_point = current_pos
        elif self.dragging_anchor == 'line':
            # 拖拽整条线：保持线段的相对位置
            line_vector = self.end_point - self.start_point
            self.start_point = current_pos - self.drag_offset
            self.end_point = self.start_point + line_vector
        
        # 更新测量线显示
        if hasattr(self.viewer, 'set_measurement_line'):
            real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
            self.viewer.set_measurement_line(self.start_point, self.end_point, real_distance, unit)
        
        # 更新状态栏显示
        self._show_final_measurement()
        self.viewer.viewport().update()

    def _stop_dragging(self):
        """停止拖拽"""
        self.dragging = False
        self.dragging_anchor = None
        self.viewer.setCursor(Qt.CrossCursor)
        self._update_status_message(self.tr("拖拽完成"))

    def _update_cursor_for_hover(self):
        """根据鼠标悬停位置更新光标样式"""
        if not self.end_point:
            return
            
        current_pos = self.viewer.last_mouse_scene_pos
        anchor_hit = self._check_anchor_hit(current_pos)
        
        if anchor_hit:
            # 悬停在锚点上
            self.viewer.setCursor(Qt.OpenHandCursor)
        elif self._is_click_on_measurement_line(current_pos):
            # 悬停在测量线上
            self.viewer.setCursor(Qt.OpenHandCursor)
        else:
            # 默认光标
            self.viewer.setCursor(Qt.CrossCursor)

    def _is_click_on_measurement_line(self, click_pos: QPointF) -> bool:
        """检查点击位置是否在测量线上"""
        if not self.start_point or not self.end_point:
            return False
            
        # 计算点击位置到测量线的距离
        line_start = self.start_point
        line_end = self.end_point
        
        # 计算线段长度
        line_length = self._calculate_pixel_distance(line_start, line_end)
        if line_length == 0:
            return False
            
        # 计算点击位置到线段的距离
        # 使用点到线段的距离公式
        t = max(0, min(1, ((click_pos.x() - line_start.x()) * (line_end.x() - line_start.x()) + 
                           (click_pos.y() - line_start.y()) * (line_end.y() - line_start.y())) / (line_length * line_length)))
        
        # 计算线段上最近的点
        closest_point = QPointF(
            line_start.x() + t * (line_end.x() - line_start.x()),
            line_start.y() + t * (line_end.y() - line_start.y())
        )
        
        # 计算点击位置到最近点的距离
        distance = self._calculate_pixel_distance(click_pos, closest_point)
        
        # 如果距离小于阈值（5像素），认为点击在线段上
        return distance <= 5

    def _update_preview_distance(self):
        """更新预览距离显示"""
        if not self.start_point or not self._preview_point:
            return
            
        # 计算预览距离
        real_distance, unit = self._calculate_real_distance(self.start_point, self._preview_point)
        
        # 更新状态栏显示预览距离
        if unit == "mm" and real_distance > 0:
            if real_distance >= 10:
                message = self.tr("预览距离: {:.1f} mm").format(real_distance)
            else:
                message = self.tr("预览距离: {:.2f} mm").format(real_distance)
        else:
            message = self.tr("预览距离: 无法计算（缺少像素间距信息）")
            
        self._update_status_message(message)

    def _show_final_measurement(self):
        """显示最终测量结果"""
        if not self.start_point or not self.end_point:
            return
            
        real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
        
        if unit == "mm" and real_distance > 0:
            if real_distance >= 10:
                message = self.tr("测量距离: {:.1f} mm").format(real_distance)
            else:
                message = self.tr("测量距离: {:.2f} mm").format(real_distance)
        else:
            message = self.tr("测量距离: 无法计算（缺少像素间距信息）")
            
        self._update_status_message(message)

    def _complete_measurement(self):
        """完成测量并显示结果"""
        if not self.start_point or not self.end_point:
            return
            
        # 计算实际距离（mm）
        real_distance, unit = self._calculate_real_distance(self.start_point, self.end_point)
        
        # 显示测量结果
        self._show_final_measurement()
        
        # 标记测量完成
        self.measurement_completed = True
        
        # 将测量线信息保存到图像查看器，以便在工具切换后保持显示
        if hasattr(self.viewer, 'set_measurement_line'):
            self.viewer.set_measurement_line(self.start_point, self.end_point, real_distance, unit)
        
        # 打印到日志
        import logging
        logger = logging.getLogger(__name__)
        if unit == "mm" and real_distance > 0:
            if real_distance >= 10:
                logger.info(f"测量完成: {real_distance:.1f} mm")
            else:
                logger.info(f"测量完成: {real_distance:.2f} mm")
        else:
            logger.info("测量完成: 无法计算（缺少像素间距信息）")

    def _calculate_real_distance(self, point1: QPointF, point2: QPointF) -> tuple[float, str]:
        """
        根据DICOM信息计算实际距离
        
        Args:
            point1: 第一个点
            point2: 第二个点
            
        Returns:
            tuple: (实际距离值, 单位)
        """
        model = self.viewer.model
        if not model or not model.has_image():
            return 0.0, "mm"
            
        # 计算像素距离
        pixel_distance = self._calculate_pixel_distance(point1, point2)
        
        # 从DICOM元数据获取像素间距
        dicom_header = model.dicom_header
        if not dicom_header:
            # 如果没有日志属性，就不输出警告
            if hasattr(self, 'logger'):
                self.logger.warning("DICOM header is empty")
            return 0.0, "mm"
            
        # 尝试获取像素间距 (Pixel Spacing)
        pixel_spacing = dicom_header.get('Pixel Spacing', None)
        if pixel_spacing and len(pixel_spacing) >= 2:
            # PixelSpacing 通常是 [row_spacing, col_spacing] (mm)
            row_spacing = float(pixel_spacing[0])  # mm/pixel
            col_spacing = float(pixel_spacing[1])  # mm/pixel
            
            # 使用平均像素间距
            avg_spacing = (row_spacing + col_spacing) / 2.0
            real_distance = pixel_distance * avg_spacing
            return real_distance, "mm"
            
        # 如果没有Pixel Spacing，尝试其他字段
        imager_pixel_spacing = dicom_header.get('Imager Pixel Spacing', None)
        if imager_pixel_spacing and len(imager_pixel_spacing) >= 2:
            row_spacing = float(imager_pixel_spacing[0])
            col_spacing = float(imager_pixel_spacing[1])
            avg_spacing = (row_spacing + col_spacing) / 2.0
            real_distance = pixel_distance * avg_spacing
            return real_distance, "mm"
            
        # 如果都没有，返回0
        return 0.0, "mm"

    def _calculate_pixel_distance(self, point1: QPointF, point2: QPointF) -> float:
        """计算两点间的像素距离"""
        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()
        return math.sqrt(dx * dx + dy * dy)

    def _update_status_message(self, message: str):
        """更新状态栏消息"""
        try:
            if hasattr(self.viewer, 'parent') and hasattr(self.viewer.parent(), 'status_label'):
                main_window = self.viewer.parent()
                main_window.status_label.setText(message)
                # 强制更新状态栏
                main_window.status_bar.update()
                # 记录到日志以便调试
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"状态栏更新: {message}")
        except Exception as e:
            # 如果状态栏更新失败，至少记录到日志
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"状态栏更新失败: {e}")

    def _clear_status_message(self):
        """清除状态栏消息"""
        if hasattr(self.viewer, 'parent') and hasattr(self.viewer.parent(), 'status_label'):
            main_window = self.viewer.parent()
            main_window.status_label.setText(self.tr("就绪"))

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
            pen.setCosmetic(True) # 确保线宽不受缩放影响
            painter.setPen(pen)
            painter.drawLine(self.start_point, draw_end_point)
            
            # 2. 绘制锚点 (大小固定)
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
        else: # 只绘制起始点
            painter.setBrush(QColor(anchor_color))
            painter.setPen(Qt.NoPen)
            pixel_size = 1.0 / self.viewer.transform().m11()
            scaled_anchor_size = anchor_size * pixel_size
            painter.drawEllipse(self.start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
        
        painter.restore() 