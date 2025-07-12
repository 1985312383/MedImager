#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像查看器控件
核心的 2D 图像显示控件，基于 QGraphicsView 实现
"""

from typing import Optional, TYPE_CHECKING
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QWidget, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, QPointF, QRect, QRectF, QPoint, QSizeF
from PySide6.QtGui import QPixmap, QImage, QPainter, QWheelEvent, QMouseEvent, QCursor, QColor, QPen, QFontMetrics
import math
from medimager.utils.logger import get_logger
from medimager.core.image_data_model import ImageDataModel
from medimager.ui.tools.base_tool import BaseTool
from medimager.ui.tools.roi_tool import EllipseROITool
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI
from medimager.core.analysis import calculate_roi_statistics
from medimager.ui.widgets.roi_stats_box import draw_stats_box
from ..utils.settings import SettingsManager

if TYPE_CHECKING:
    from medimager.core.image_data_model import ImageDataModel
    from medimager.ui.tools.base_tool import BaseTool

from medimager.ui.widgets.magnifier import MagnifierWidget
from medimager.ui.tools.default_tool import DefaultTool


class ImageViewer(QGraphicsView):
    """图像查看器控件
    
    基于 QGraphicsView 的图像显示控件，职责是显示由 ImageDataModel 处理好的图像。
    它不包含任何图像处理逻辑（如窗宽窗位），只负责显示和用户交互。
    """
    
    # 信号定义
    pixel_value_changed = Signal(int, int, float)  # 像素值变化信号 (x, y, value)
    cursor_left_image = Signal() # 当光标离开图像区域时发出
    zoom_changed = Signal(float)  # 缩放比例变化信号
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.model: Optional[ImageDataModel] = None
        self.current_tool: Optional[BaseTool] = None

        self._init_scene()
        self._init_viewer_settings()

        self._panning = False
        self._pan_start_pos = QPoint()
        
        # 图像Item
        self.image_item: Optional[QGraphicsPixmapItem] = None
        
        # 自定义光标
        self.cross_cursor = self._create_cross_cursor()
        
        # 放大镜
        self.magnifier = MagnifierWidget(self)
        
        # 设置视图属性
        self._setup_view()
        
        # 启用拖拽接收
        self.setAcceptDrops(True)
        
        # 设置默认工具
        self.set_tool(DefaultTool(self))
        
        # 状态：用于跟踪悬停的ROI和鼠标位置，以显示统计信息
        self.hovered_roi_index: Optional[int] = None
        self.last_mouse_scene_pos: QPointF = QPointF()
        self.stats_box_positions: dict[str, QRect] = {} # ROI_id -> QRect for stats box
        
        # 测量线状态：用于在工具切换后保持测量线显示
        self.measurement_start_point: Optional[QPointF] = None
        self.measurement_end_point: Optional[QPointF] = None
        self.measurement_distance: Optional[float] = None
        self.measurement_unit: str = "mm"
        
        # 测量线拖拽状态
        self._measurement_dragging = False
        self._measurement_drag_start_pos = QPointF()
        self._measurement_drag_offset = QPointF()
        
        # 初始化设置管理器
        self._init_settings()

    def _init_settings(self):
        """初始化设置管理器"""
        try:
            self.settings_manager = SettingsManager()
        except Exception as e:
            self.logger.warning(f"初始化设置管理器失败: {e}")
            self.settings_manager = None

    def _setup_view(self) -> None:
        """设置视图属性"""
        self.setDragMode(QGraphicsView.NoDrag) # 拖拽模式由工具类控制
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #2b2b2b;")
        self.setFrameShape(QFrame.NoFrame)
        
    def _create_cross_cursor(self) -> QCursor:
        """创建一个洋红色的十字光标"""
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        pen = QPen(QColor("magenta"))
        pen.setWidth(1)
        painter.setPen(pen)
        
        # 绘制十字
        center = size // 2
        painter.drawLine(center, 0, center, size)
        painter.drawLine(0, center, size, center)
        
        painter.end()
        
        return QCursor(pixmap, hotX=center, hotY=center)

    def _init_scene(self) -> None:
        """初始化场景"""
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.image_item = QGraphicsPixmapItem()
        self.scene.addItem(self.image_item)

    def _init_viewer_settings(self) -> None:
        """初始化视图设置"""
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)

    def set_tool(self, tool: Optional[BaseTool]):
        """设置并激活当前工具"""
        if self.current_tool:
            self.current_tool.deactivate()

        # 切换工具时，清除任何现有的ROI选择，以避免旧的锚点残留
        if self.model:
            self.model.clear_selection()
            
        self.current_tool = tool
        
        if self.current_tool:
            self.current_tool.activate()

    def set_model(self, model: ImageDataModel) -> None:
        """设置数据模型并更新视图"""
        self.model = model

    def display_qimage(self, q_image: Optional[QImage]) -> None:
        """显示 QImage
        
        此方法是该控件的核心入口，由外部（如MainWindow）调用，
        传入已经经过窗宽窗位等处理的 QImage。
        
        Args:
            q_image: 要显示的 QImage 对象，如果为 None，则清空视图。
        """
        if q_image is None or q_image.isNull():
            if self.image_item:
                self.scene.removeItem(self.image_item)
                self.image_item = None
            self.scene.clear()
            return

        pixmap = QPixmap.fromImage(q_image)
        if self.image_item is None:
            self.image_item = self.scene.addPixmap(pixmap)
        else:
            self.image_item.setPixmap(pixmap)
            
        self.scene.setSceneRect(pixmap.rect())

    def fit_to_window(self) -> None:
        """自适应窗口大小"""
        if not self.image_item or self.image_item.pixmap().isNull():
            return
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.zoom_factor = self.transform().m11()
        self.zoom_changed.emit(self.zoom_factor)
        
    def enterEvent(self, event) -> None:
        """鼠标进入事件"""
        # 光标由当前工具管理
        # self.setCursor(self.cross_cursor)
        self.magnifier.show()
        super().enterEvent(event)
        
    def leaveEvent(self, event) -> None:
        """鼠标离开事件"""
        self.unsetCursor()
        self.magnifier.hide()
        self.cursor_left_image.emit()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """重写鼠标滚轮事件，委托给当前工具"""
        if self.current_tool:
            self.current_tool.wheel_event(event)
        else:
            super().wheelEvent(event)
            
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """重写鼠标按下事件，委托给当前工具或处理测量线拖拽"""
        # 先让工具处理事件
        if self.current_tool:
            self.current_tool.mouse_press_event(event)
        else:
            super().mousePressEvent(event)
            
        # 只有在当前工具不是测量工具时，才处理ImageViewer的测量线拖拽
        # 检查工具类型而不是方法存在性
        is_measurement_tool = (self.current_tool and 
                              self.current_tool.__class__.__name__ == 'MeasurementTool')
        
        if (not self.current_tool or not is_measurement_tool) and self.measurement_start_point and self.measurement_end_point:
            self._check_measurement_line_drag(event)
        
        # 处理视图选中 - 转发给父ViewFrame
        if event.button() == Qt.LeftButton:
            parent = self.parent()
            if parent and hasattr(parent, 'mousePressEvent'):
                # 创建一个新的事件，坐标转换到父组件
                parent_pos = self.mapToParent(event.pos())
                parent_event = QMouseEvent(
                    event.type(),
                    parent_pos,
                    event.globalPosition(),
                    event.button(),
                    event.buttons(),
                    event.modifiers()
                )
                parent.mousePressEvent(parent_event)
            
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """重写鼠标移动事件，委托给当前工具或处理测量线拖拽"""
        if self.current_tool:
            self.current_tool.mouse_move_event(event)
        else:
            super().mouseMoveEvent(event)
            
        # 只有在当前工具不是测量工具时，才处理ImageViewer的测量线拖拽
        is_measurement_tool = (self.current_tool and 
                              self.current_tool.__class__.__name__ == 'MeasurementTool')
        
        if (not is_measurement_tool and hasattr(self, '_measurement_dragging') and 
            self._measurement_dragging):
            self._update_measurement_drag(event)
            
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """重写鼠标释放事件，委托给当前工具或处理测量线拖拽"""
        if self.current_tool:
            self.current_tool.mouse_release_event(event)
        else:
            super().mouseReleaseEvent(event)
            
        # 只有在当前工具不是测量工具时，才处理ImageViewer的测量线拖拽
        is_measurement_tool = (self.current_tool and 
                              self.current_tool.__class__.__name__ == 'MeasurementTool')
        
        if (not is_measurement_tool and hasattr(self, '_measurement_dragging') and 
            self._measurement_dragging and event.button() == Qt.LeftButton):
            self._stop_measurement_drag()
            
    def keyPressEvent(self, event) -> None:
        """处理键盘按下事件，先委托给当前工具，然后处理ROI删除等。"""
        # 先委托给当前工具处理
        if self.current_tool:
            self.current_tool.key_press_event(event)
            if event.isAccepted():
                return
        
        # 如果工具没有处理，则由视图处理
        if event.key() == Qt.Key_Delete and self.model:
            # 删除模型中的ROI
            deleted_ids = self.model.delete_selected_rois()
            
            # 从视图中移除对应的信息板
            for roi_id in deleted_ids:
                if roi_id in self.stats_box_positions:
                    del self.stats_box_positions[roi_id]
            
            # 不需要手动更新视图，因为 model 的 clear_selection 会发出 data_changed 信号
            event.accept()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        """处理拖拽进入事件 - 转发给父ViewFrame"""
        # 检查父组件是否是ViewFrame
        parent = self.parent()
        if parent and hasattr(parent, 'dragEnterEvent'):
            parent.dragEnterEvent(event)
        else:
            super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """处理拖拽移动事件 - 转发给父ViewFrame"""
        parent = self.parent()
        if parent and hasattr(parent, 'dragMoveEvent'):
            parent.dragMoveEvent(event)
        else:
            super().dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """处理拖拽离开事件 - 转发给父ViewFrame"""
        parent = self.parent()
        if parent and hasattr(parent, 'dragLeaveEvent'):
            parent.dragLeaveEvent(event)
        else:
            super().dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """处理拖拽放下事件 - 转发给父ViewFrame"""
        parent = self.parent()
        if parent and hasattr(parent, 'dropEvent'):
            parent.dropEvent(event)
        else:
            super().dropEvent(event)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """在前景中绘制内容，如ROI、锚点、统计信息和临时形状。"""
        super().drawForeground(painter, rect)

        if not self.model or not self.model.has_image():
            return

        painter.setRenderHint(QPainter.Antialiasing, True)
        current_slice_index = self.model.current_slice_index

        # Draw ROIs
        if self.model:
            for roi in self.model.rois:
                if roi.slice_index != current_slice_index:
                    continue

                # 1. ROI自己绘制轮廓和锚点
                roi.draw(painter, self.transform())
                
                # 2. 绘制统计信息框 (由Viewer管理位置)
                if roi.id in self.stats_box_positions and roi.show_stats:
                    stats = calculate_roi_statistics(self.model, roi)
                    if stats:
                        draw_stats_box(painter, stats, self.stats_box_positions[roi.id])

        # Draw measurement tool if it is active and has points
        if self.current_tool and hasattr(self.current_tool, 'draw_temporary_shape'):
            self.current_tool.draw_temporary_shape(painter)
            
        # --- 绘制测量线 (独立于当前工具) ---
        if self.measurement_start_point and self.measurement_end_point:
            self._draw_measurement_line(painter)
        elif self.current_tool and hasattr(self.current_tool, 'draw_measurement_line'):
            # 如果当前工具是测量工具，使用工具的绘制方法
            self.current_tool.draw_measurement_line(painter)
            
    def _update_pixel_info(self, scene_pos: QPointF) -> None:
        """更新状态栏的像素信息和放大镜"""
        # 首先检查是否有图像
        if self.image_item is None:
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return
        # 获取图像的实际像素范围
        pixmap = self.image_item.pixmap()
        if pixmap.isNull():
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return
        image_rect = pixmap.rect()  # 这是实际的图像像素矩形
        # 检查鼠标位置是否在实际图像像素范围内
        if not image_rect.contains(scene_pos.toPoint()):
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return
        
        self.magnifier.show()
        
        # 更新放大镜
        source_qimage = pixmap.toImage()
        # 定义放大镜源区域大小, 必须是偶数
        magnifier_source_size = 8 
        half_size = magnifier_source_size // 2
        # 创建源矩形
        source_rect = QRect(
            int(scene_pos.x() - half_size),
            int(scene_pos.y() - half_size),
            magnifier_source_size,
            magnifier_source_size
        )
        # 确保源矩形在图像范围内
        source_rect = source_rect.intersected(image_rect)
        # 如果源区域有效则更新放大镜
        if not source_rect.isEmpty() and source_rect.width() > 0 and source_rect.height() > 0:
            self.magnifier.update_magnifier(source_qimage, source_rect)
        
        # 更新像素值
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        
        # 检查坐标是否在图像范围内并且模型有效
        if self.model and self.model.has_image():
            shape = self.model.get_image_shape()
            if shape and 0 <= x < shape[2] and 0 <= y < shape[1]:
                # 获取像素值
                pixel_value = self.model.get_pixel_value(x, y)
                if pixel_value is not None:
                    # 发出像素值变化信号
                    self.pixel_value_changed.emit(x, y, pixel_value)
                    return
        
        # 如果没有有效的像素值，则清除状态
        self.cursor_left_image.emit()

    def clear_roi_dependent_state(self) -> None:
        """当ROI被清空或加载新图像时，重置与ROI相关的状态"""
        self.hovered_roi_index = None
        self.stats_box_positions = {}
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        """窗口大小改变事件"""
        super().resizeEvent(event)
        # 将放大镜放在右上角
        magnifier_size = self.magnifier.size()
        self.magnifier.move(self.width() - magnifier_size.width() - 5, 5)
        # 可以选择在改变大小时自动适应窗口
        # self.fit_to_window() 

    def _update_view(self):
        """当模型数据变化时，重新渲染视图"""
        if self.model:
            self.model.update_qimage()

    def zoom_in(self, level=1.2):
        """放大"""
        self.scale(level, level)
        self.zoom_factor = self.transform().m11()
        self.zoom_changed.emit(self.zoom_factor)

    def zoom_out(self, level=1.2):
        """缩小"""
        self.scale(1 / level, 1 / level)
        self.zoom_factor = self.transform().m11()
        self.zoom_changed.emit(self.zoom_factor)

    def fit_to_window(self):
        """图像自适应窗口大小"""
        if not self.image_item or self.image_item.pixmap().isNull():
            return
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio) 

    def is_shift_pressed(self) -> bool:
        """检查Shift键是否被按下"""
        return QApplication.keyboardModifiers() == Qt.ShiftModifier

    def set_measurement_line(self, start_point: QPointF, end_point: QPointF, distance: float, unit: str = "mm"):
        """设置测量线，用于在工具切换后保持显示"""
        self.measurement_start_point = start_point
        self.measurement_end_point = end_point
        self.measurement_distance = distance
        self.measurement_unit = unit
        self.viewport().update()

    def clear_measurement_line(self):
        """清除测量线"""
        self.measurement_start_point = None
        self.measurement_end_point = None
        self.measurement_distance = None
        self.measurement_unit = "mm"
        self.viewport().update()

    def _draw_measurement_line(self, painter):
        """绘制测量线（独立于工具）"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return
            
        # 从主题文件中获取样式
        try:
            from medimager.utils.theme_manager import get_theme_settings
            
            # 使用统一的主题设置读取函数
            theme_data = get_theme_settings('measurement')
        
            line_color = theme_data.get('line_color', "#00FF00")
            anchor_color = theme_data.get('anchor_color', "#00FF00")
            text_color = theme_data.get('text_color', "#FFFFFF")
            bg_color = theme_data.get('background_color', "#00000080")
            line_width = theme_data.get('line_width', 2)
            anchor_size = theme_data.get('anchor_size', 8)
            font_size = theme_data.get('font_size', 14)
        except Exception:
            # 默认设置
            line_color = "#00FF00"
            anchor_color = "#00FF00"
            text_color = "#FFFFFF"
            bg_color = "#00000080"
            line_width = 2
            anchor_size = 8
            font_size = 14

        from PySide6.QtGui import QColor, QPen, QFont, QBrush
        from PySide6.QtCore import QPointF, QRectF, Qt

        painter.save()

        # 1. 绘制线
        pen = QPen(QColor(line_color), line_width)
        pen.setCosmetic(True) # 确保线宽不受缩放影响
        painter.setPen(pen)
        painter.drawLine(self.measurement_start_point, self.measurement_end_point)

        # 2. 绘制锚点 (大小固定)
        painter.setBrush(QColor(anchor_color))
        painter.setPen(Qt.NoPen)
        pixel_size = 1.0 / self.transform().m11()
        scaled_anchor_size = anchor_size * pixel_size
        painter.drawEllipse(self.measurement_start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
        painter.drawEllipse(self.measurement_end_point, scaled_anchor_size / 2, scaled_anchor_size / 2)

        # 3. 绘制距离文本
        if self.measurement_distance is not None:
            font = QFont()
            font.setPixelSize(font_size)
            painter.setFont(font)

            text = f"{self.measurement_distance:.2f} {self.measurement_unit}"
            metrics = painter.fontMetrics()
            text_rect = metrics.boundingRect(text).adjusted(-4, -2, 4, 2)
            
            mid_point = (self.measurement_start_point + self.measurement_end_point) / 2
            text_rect.moveCenter(mid_point.toPoint())
            
            # 绘制背景
            painter.setBrush(QColor(bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(text_rect, 5, 5)

            # 绘制文本
            painter.setPen(QColor(text_color))
            painter.drawText(text_rect, Qt.AlignCenter, text)

        painter.restore()

    def _check_measurement_line_drag(self, event: QMouseEvent):
        """检查鼠标是否开始拖动测量线或其锚点"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return
            
        # 计算点击位置到测量线的距离
        click_pos = self.mapToScene(event.pos())
        if self._is_click_on_measurement_line(click_pos):
            self._start_measurement_drag(event)

    def _is_click_on_measurement_line(self, click_pos: QPointF) -> bool:
        """检查点击位置是否在测量线上"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return False
            
        # 计算点击位置到测量线的距离
        line_start = self.measurement_start_point
        line_end = self.measurement_end_point
        
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

    def _calculate_pixel_distance(self, point1: QPointF, point2: QPointF) -> float:
        """计算两点间的像素距离"""
        import math
        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()
        return math.sqrt(dx * dx + dy * dy)

    def _start_measurement_drag(self, event: QMouseEvent):
        """开始拖拽测量线"""
        self._measurement_dragging = True
        self._measurement_drag_start_pos = self.mapToScene(event.pos())
        self._measurement_drag_offset = QPointF(0, 0)
        self.setCursor(Qt.ClosedHandCursor)

    def _update_measurement_drag(self, event: QMouseEvent):
        """更新测量线拖拽"""
        if not hasattr(self, '_measurement_dragging') or not self._measurement_dragging:
            return
            
        # 计算拖拽偏移
        current_pos = self.mapToScene(event.pos())
        self._measurement_drag_offset = current_pos - self._measurement_drag_start_pos
        
        # 更新测量点位置
        if self.measurement_start_point and self.measurement_end_point:
            self.measurement_start_point += self._measurement_drag_offset
            self.measurement_end_point += self._measurement_drag_offset
            self._measurement_drag_start_pos = current_pos
            
            # 更新视图
            self.viewport().update()

    def _stop_measurement_drag(self):
        """停止测量线拖拽"""
        if hasattr(self, '_measurement_dragging'):
            self._measurement_dragging = False
        self.setCursor(Qt.ArrowCursor)
        if hasattr(self, '_measurement_drag_offset'):
            self._measurement_drag_offset = QPointF(0, 0)