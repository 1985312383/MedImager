from abc import ABC, abstractmethod
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtCore import QEvent, Qt, QPointF, QCoreApplication
from PySide6.QtGui import QMouseEvent, QWheelEvent, QKeyEvent

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

    def wheelEvent(self, event: QWheelEvent) -> bool:
        """
        处理鼠标滚轮事件
        返回 True 表示事件已被处理，False 则表示未处理
        """
        return False

    def key_press_event(self, event: QKeyEvent):
        """处理键盘按键事件。子类可以重写此方法以处理特定的按键。"""
        pass

    def key_release_event(self, event: QKeyEvent):
        """处理键盘释放事件。子类可以重写此方法以处理特定的按键。"""
        pass