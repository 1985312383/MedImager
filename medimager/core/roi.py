from abc import ABC, abstractmethod
from enum import Enum
from typing import Tuple, TYPE_CHECKING
import uuid

import numpy as np
import logging

from ..utils.settings import get_settings_manager

if TYPE_CHECKING:
    from PySide6.QtGui import QPainter, QTransform, QColor, QPen
    from PySide6.QtCore import QPointF, QRectF, Qt


def _get_settings():
    """延迟获取全局设置管理器，避免模块导入时过早实例化"""
    return get_settings_manager()


def _create_circle_mask(center_y: int, center_x: int, radius: int, height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """
    创建圆形掩码的坐标数组，替代skimage.draw.disk
    
    Args:
        center_y: 圆心Y坐标
        center_x: 圆心X坐标  
        radius: 半径
        height: 图像高度
        width: 图像宽度
        
    Returns:
        (rr, cc): 圆形区域内的行列坐标数组
    """
    y, x = np.ogrid[:height, :width]
    mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= radius ** 2
    rr, cc = np.where(mask)
    return rr, cc


def _create_ellipse_mask(center_y: int, center_x: int, radius_y: int, radius_x: int, height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """
    创建椭圆掩码的坐标数组，替代skimage.draw.ellipse
    
    Args:
        center_y: 椭圆中心Y坐标
        center_x: 椭圆中心X坐标
        radius_y: Y轴半径
        radius_x: X轴半径
        height: 图像高度
        width: 图像宽度
        
    Returns:
        (rr, cc): 椭圆区域内的行列坐标数组
    """
    y, x = np.ogrid[:height, :width]
    mask = ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2 <= 1
    rr, cc = np.where(mask)
    return rr, cc


class ROIShape(Enum):
    """定义支持的ROI形状类型"""
    CIRCLE = "Circle"
    RECTANGLE = "Rectangle"
    ELLIPSE = "Ellipse"


class BaseROI(ABC):
    """
    ROI的抽象基类.

    Attributes:
        shape (ROIShape): ROI的形状类型.
        slice_index (int): ROI所在的切片索引.
        selected (bool): 是否被选中.
        id (str): 每个ROI实例的唯一标识符.
    """
    def __init__(self, shape: ROIShape, slice_index: int):
        self.id = str(uuid.uuid4()) # 分配一个唯一的ID
        self.shape = shape
        self.slice_index = slice_index
        self.selected = False  # 新增：选中状态
        self.show_stats = True # 控制统计信息框的显示

    @abstractmethod
    def get_mask(self, height: int, width: int) -> np.ndarray:
        """
        为给定尺寸的图像生成一个布尔掩码.

        Args:
            height: 图像的高度.
            width: 图像的宽度.

        Returns:
            一个布尔值的numpy数组，ROI区域为True，其余为False.
        """
        pass

    @abstractmethod
    def get_anchor_points(self) -> list[tuple[int, int]]:
        """
        获取ROI的锚点（用于缩放/调整）。
        Returns:
            List of (row, col) tuples.
        """
        pass

    @abstractmethod
    def hit_test(self, pos: tuple[int, int], tol: int = 5) -> str:
        """
        命中测试：判断给定点是否在ROI内部、边缘或锚点上。
        Args:
            pos: (row, col)
            tol: 容差像素
        Returns:
            'anchor_{i}' | 'inside' | 'edge' | 'none'
        """
        pass

    @abstractmethod
    def move(self, dr: int, dc: int) -> None:
        """
        整体平移ROI。
        Args:
            dr: 行方向平移量
            dc: 列方向平移量
        """
        pass

    @abstractmethod
    def resize(self, anchor_idx: int, new_pos: tuple[int, int]) -> None:
        """
        拖动锚点调整ROI。
        Args:
            anchor_idx: 被拖动的锚点索引
            new_pos: 新的(row, col)位置
        """
        pass

    @abstractmethod
    def draw(self, painter: 'QPainter', view_transform: 'QTransform') -> None:
        """
        使用给定的QPainter绘制ROI.

        Args:
            painter: 用于绘制的 QPainter 实例.
            view_transform: 视图的当前变换，用于确保锚点等元素在屏幕上大小固定.
        """
        pass

    def _get_style_from_settings(self) -> Tuple[str, str, str, int, int]:
        """从设置中获取ROI的样式"""
        try:
            from medimager.utils.theme_manager import get_theme_settings
            
            # 使用统一的主题设置读取函数
            theme_data = get_theme_settings('roi')
            
            return (
                theme_data.get('border_color', "#FFFF00"),
                theme_data.get('selected_color', "#FF0000"),
                theme_data.get('anchor_color', "#FF0000"),
                theme_data.get('border_width', 2),
                theme_data.get('anchor_size', 8)
            )
        except Exception:
            # 默认设置
            return (
                "#FFFF00",  # border_color
                "#FF0000",  # selected_color
                "#FF0000",  # anchor_color
                2,          # border_width
                8           # anchor_size
            )


class EllipseROI(BaseROI):
    """椭圆ROI"""
    def __init__(self, center: tuple[int, int], radius_x: int, radius_y: int, slice_index: int):
        """
        初始化椭圆ROI

        Args:
            center (tuple[int, int]): 中心坐标 (row, col)
            radius_x (int): X轴方向的半径
            radius_y (int): Y轴方向的半径
            slice_index (int): ROI所在的切片索引
        """
        super().__init__(ROIShape.ELLIPSE, slice_index)
        self.center = center
        self.radius_x = radius_x
        self.radius_y = radius_y

    def draw(self, painter: 'QPainter', view_transform: 'QTransform') -> None:
        from PySide6.QtGui import QColor, QPen, QBrush
        from PySide6.QtCore import QPointF, Qt

        border_color_str, selected_color_str, anchor_color_str, border_width, anchor_size = self._get_style_from_settings()

        painter.save()
        
        pen_color = QColor(selected_color_str) if self.selected else QColor(border_color_str)
        pen = QPen(pen_color, border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        center_point = QPointF(self.center[1], self.center[0])
        painter.drawEllipse(center_point, self.radius_x, self.radius_y)

        if self.selected:
            # 锚点大小不受视图缩放影响
            pixel_size = 1.0 / view_transform.m11()
            scaled_anchor_size = anchor_size * pixel_size
            
            painter.setBrush(QColor(anchor_color_str))
            painter.setPen(Qt.PenStyle.NoPen)
            for ay, ax in self.get_anchor_points():
                painter.drawEllipse(QPointF(ax, ay), scaled_anchor_size / 2, scaled_anchor_size / 2)
        
        painter.restore()

    def get_mask(self, height: int, width: int) -> np.ndarray:
        """根据椭圆几何形状生成布尔掩码"""
        mask = np.zeros((height, width), dtype=bool)
        # 确保所有参数都是整数
        cy, cx = int(self.center[0]), int(self.center[1])
        ry, rx = int(self.radius_y), int(self.radius_x)
        # 使用自定义函数替代skimage.draw.ellipse
        rr, cc = _create_ellipse_mask(cy, cx, ry, rx, height, width)
        mask[rr, cc] = True
        return mask

    def get_anchor_points(self) -> list[tuple[int, int]]:
        # 四个角点（外接矩形）
        cy, cx = self.center
        rx, ry = self.radius_x, self.radius_y
        return [
            (cy - ry, cx - rx),  # 左上
            (cy - ry, cx + rx),  # 右上
            (cy + ry, cx - rx),  # 左下
            (cy + ry, cx + rx),  # 右下
        ]

    def hit_test(self, pos: tuple[int, int], tol: int = 5) -> str:
        # 先判断锚点
        for i, (ay, ax) in enumerate(self.get_anchor_points()):
            if abs(pos[0] - ay) <= tol and abs(pos[1] - ax) <= tol:
                return f'anchor_{i}'
        # 判断是否在椭圆内部
        cy, cx = self.center
        rx, ry = self.radius_x, self.radius_y
        if rx > 0 and ry > 0:
            norm = ((pos[1] - cx) / rx) ** 2 + ((pos[0] - cy) / ry) ** 2
            if norm <= 1:
                return 'inside'
        return 'none'

    def move(self, dr: int, dc: int) -> None:
        cy, cx = self.center
        self.center = (cy + dr, cx + dc)

    def start_resize(self, anchor_idx: int):
        """记录resize起始参数"""
        self._resize_anchor_idx = anchor_idx
        self._resize_opp_idx = (anchor_idx + 3) % 4
        self._resize_anchors = self.get_anchor_points()
        self._resize_center = self.center
        self._resize_rx = self.radius_x
        self._resize_ry = self.radius_y

    def resize(self, anchor_idx: int, new_pos: tuple[int, int]) -> None:
        import logging; logging.getLogger(__name__).debug(f"EllipseROI.resize: anchor_idx={anchor_idx}, new_pos={new_pos}")
        if not hasattr(self, '_resize_anchors'):
            self.start_resize(anchor_idx)
        anchors = list(self._resize_anchors)
        anchors[anchor_idx] = new_pos
        # 正确的对角锚点配对
        opp_idx_map = {0: 3, 1: 2, 2: 1, 3: 0}
        opp_idx = opp_idx_map[anchor_idx]
        y0, x0 = anchors[opp_idx]
        y1, x1 = anchors[anchor_idx]
        logging.getLogger(__name__).debug(f"EllipseROI.resize: opp_idx={opp_idx}, y0={y0}, x0={x0}, y1={y1}, x1={x1}")
        new_cy = (y0 + y1) // 2
        new_cx = (x0 + x1) // 2
        new_ry = abs(y1 - y0) // 2
        new_rx = abs(x1 - x0) // 2
        self.center = (new_cy, new_cx)
        self.radius_x = max(1, new_rx)
        self.radius_y = max(1, new_ry)

    def end_resize(self):
        if hasattr(self, '_resize_anchors'):
            del self._resize_anchors
            del self._resize_center
            del self._resize_rx
            del self._resize_ry
            del self._resize_anchor_idx
            del self._resize_opp_idx


class CircleROI(EllipseROI):
    """圆形ROI，作为椭圆ROI的一个特例"""
    def __init__(self, center: tuple[int, int], radius: int, slice_index: int):
        """
        初始化圆形ROI

        Args:
            center (tuple[int, int]): 圆心坐标 (row, col)
            radius (int): 半径
            slice_index (int): ROI所在的切片索引
        """
        super().__init__(center, radius, radius, slice_index)
        self.shape = ROIShape.CIRCLE # 重写形状
        self.radius = radius

    def draw(self, painter: 'QPainter', view_transform: 'QTransform') -> None:
        from PySide6.QtGui import QColor, QPen, QBrush
        from PySide6.QtCore import QPointF, Qt

        border_color_str, selected_color_str, anchor_color_str, border_width, anchor_size = self._get_style_from_settings()
        
        painter.save()

        pen_color = QColor(selected_color_str) if self.selected else QColor(border_color_str)
        pen = QPen(pen_color, border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        center_point = QPointF(self.center[1], self.center[0])
        painter.drawEllipse(center_point, self.radius, self.radius)

        if self.selected:
            pixel_size = 1.0 / view_transform.m11()
            scaled_anchor_size = anchor_size * pixel_size
            
            painter.setBrush(QColor(anchor_color_str))
            painter.setPen(Qt.PenStyle.NoPen)
            for ay, ax in self.get_anchor_points():
                painter.drawEllipse(QPointF(ax, ay), scaled_anchor_size / 2, scaled_anchor_size / 2)
        
        painter.restore()

    def get_mask(self, height: int, width: int) -> np.ndarray:
        """
        生成一个圆形的布尔掩码.

        Args:
            height: 图像的高度.
            width: 图像的宽度.

        Returns:
            一个布尔值的numpy数组，圆形ROI区域为True.
        """
        mask = np.zeros((height, width), dtype=bool)
        # 确保参数都是整数
        cy, cx = int(self.center[0]), int(self.center[1])
        r = int(self.radius)
        # 使用自定义函数替代skimage.draw.disk
        rr, cc = _create_circle_mask(cy, cx, r, height, width)
        mask[rr, cc] = True
        return mask 

    def get_anchor_points(self) -> list[tuple[int, int]]:
        """获取圆形的外接矩形的四个角点作为锚点"""
        cy, cx = self.center
        r = self.radius
        return [
            (cy - r, cx - r),  # 左上
            (cy - r, cx + r),  # 右上
            (cy + r, cx - r),  # 左下
            (cy + r, cx + r),  # 右下
        ]

    def hit_test(self, pos: tuple[int, int], tol: int = 5) -> str:
        # 先判断锚点
        for i, (ay, ax) in enumerate(self.get_anchor_points()):
            if abs(pos[0] - ay) <= tol and abs(pos[1] - ax) <= tol:
                return f'anchor_{i}'
        # 判断是否在圆内部
        cy, cx = self.center
        r = self.radius
        if r > 0:
            norm = (pos[1] - cx) ** 2 + (pos[0] - cy) ** 2
            if norm <= r ** 2:
                return 'inside'
        return 'none'

    def move(self, dr: int, dc: int) -> None:
        cy, cx = self.center
        self.center = (cy + dr, cx + dc)

    def start_resize(self, anchor_idx: int):
        self._resize_anchor_idx = anchor_idx
        self._resize_opp_idx = (anchor_idx + 3) % 4
        self._resize_anchors = self.get_anchor_points()
        self._resize_center = self.center
        self._resize_radius = self.radius

    def resize(self, anchor_idx: int, new_pos: tuple[int, int]) -> None:
        """通过拖动锚点调整圆形大小，保持圆形特性"""
        if not hasattr(self, '_resize_anchors'):
            self.start_resize(anchor_idx)

        # 圆形缩放是等轴的，使用外接矩形的对角点
        opp_idx_map = {0: 3, 1: 2, 2: 1, 3: 0}
        opp_anchor_pos = self._resize_anchors[opp_idx_map[anchor_idx]]

        y0, x0 = opp_anchor_pos
        y1, x1 = new_pos

        # 计算新的中心点
        new_cy = (y0 + y1) // 2
        new_cx = (x0 + x1) // 2
        
        # 计算新的半径 - 使用对角线距离的一半，确保圆形
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        # 使用较小的一边来保持圆形，或者使用对角线的一半
        new_radius = max(1, min(dx, dy) // 2)
        
        self.center = (new_cy, new_cx)
        self.radius = new_radius
        # 更新父类的半径，因为绘制依赖于它们
        self.radius_x = self.radius
        self.radius_y = self.radius

    def end_resize(self):
        if hasattr(self, '_resize_anchors'):
            del self._resize_anchors
            del self._resize_center
            del self._resize_radius
            del self._resize_anchor_idx
            del self._resize_opp_idx


class RectangleROI(BaseROI):
    """矩形ROI"""
    def __init__(self, top_left: tuple[int, int], bottom_right: tuple[int, int], slice_index: int):
        """
        初始化矩形ROI

        Args:
            top_left (tuple[int, int]): 左上角坐标 (row, col)
            bottom_right (tuple[int, int]): 右下角坐标 (row, col)
            slice_index (int): ROI所在的切片索引
        """
        super().__init__(ROIShape.RECTANGLE, slice_index)
        # 确保坐标顺序正确
        self.top_left = (min(top_left[0], bottom_right[0]), min(top_left[1], bottom_right[1]))
        self.bottom_right = (max(top_left[0], bottom_right[0]), max(top_left[1], bottom_right[1]))

    def draw(self, painter: 'QPainter', view_transform: 'QTransform') -> None:
        from PySide6.QtGui import QColor, QPen, QBrush
        from PySide6.QtCore import QPointF, QRectF, Qt

        border_color_str, selected_color_str, anchor_color_str, border_width, anchor_size = self._get_style_from_settings()
        
        painter.save()

        pen_color = QColor(selected_color_str) if self.selected else QColor(border_color_str)
        pen = QPen(pen_color, border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        painter.drawRect(rect)

        if self.selected:
            pixel_size = 1.0 / view_transform.m11()
            scaled_anchor_size = anchor_size * pixel_size
            
            painter.setBrush(QColor(anchor_color_str))
            painter.setPen(Qt.PenStyle.NoPen)
            for ay, ax in self.get_anchor_points():
                painter.drawEllipse(QPointF(ax, ay), scaled_anchor_size / 2, scaled_anchor_size / 2)
        
        painter.restore()

    @property
    def width(self) -> int:
        """矩形宽度"""
        return self.bottom_right[1] - self.top_left[1]

    @property
    def height(self) -> int:
        """矩形高度"""
        return self.bottom_right[0] - self.top_left[0]

    @property
    def center(self) -> tuple[int, int]:
        """矩形中心点"""
        cy = (self.top_left[0] + self.bottom_right[0]) // 2
        cx = (self.top_left[1] + self.bottom_right[1]) // 2
        return (cy, cx)

    def get_mask(self, height: int, width: int) -> np.ndarray:
        """生成矩形的布尔掩码"""
        mask = np.zeros((height, width), dtype=bool)
        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        
        # 确保坐标是整数并且在图像范围内
        y1 = max(0, min(int(y1), height - 1))
        y2 = max(0, min(int(y2), height - 1))
        x1 = max(0, min(int(x1), width - 1))
        x2 = max(0, min(int(x2), width - 1))
        
        if y1 <= y2 and x1 <= x2:
            mask[y1:y2+1, x1:x2+1] = True
        
        return mask

    def get_anchor_points(self) -> list[tuple[int, int]]:
        """获取矩形的四个角点作为锚点"""
        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        return [
            (y1, x1),  # 左上
            (y1, x2),  # 右上
            (y2, x1),  # 左下
            (y2, x2),  # 右下
        ]

    def hit_test(self, pos: tuple[int, int], tol: int = 5) -> str:
        """命中测试"""
        # 先判断锚点
        for i, (ay, ax) in enumerate(self.get_anchor_points()):
            if abs(pos[0] - ay) <= tol and abs(pos[1] - ax) <= tol:
                return f'anchor_{i}'
        
        # 判断是否在矩形内部
        y, x = pos
        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        
        if y1 <= y <= y2 and x1 <= x <= x2:
            return 'inside'
        
        return 'none'

    def move(self, dr: int, dc: int) -> None:
        """移动矩形"""
        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        self.top_left = (y1 + dr, x1 + dc)
        self.bottom_right = (y2 + dr, x2 + dc)

    def start_resize(self, anchor_idx: int):
        """开始缩放操作"""
        self._resize_anchor_idx = anchor_idx
        self._resize_anchors = self.get_anchor_points()
        self._resize_top_left = self.top_left
        self._resize_bottom_right = self.bottom_right

    def resize(self, anchor_idx: int, new_pos: tuple[int, int]) -> None:
        """通过拖动锚点调整矩形大小"""
        if not hasattr(self, '_resize_anchors'):
            self.start_resize(anchor_idx)

        # 根据被拖动的锚点更新矩形
        y, x = new_pos
        
        if anchor_idx == 0:  # 左上角
            self.top_left = (y, x)
        elif anchor_idx == 1:  # 右上角
            self.top_left = (y, self.top_left[1])
            self.bottom_right = (self.bottom_right[0], x)
        elif anchor_idx == 2:  # 左下角
            self.top_left = (self.top_left[0], x)
            self.bottom_right = (y, self.bottom_right[1])
        elif anchor_idx == 3:  # 右下角
            self.bottom_right = (y, x)

        # 确保坐标顺序正确
        y1, x1 = self.top_left
        y2, x2 = self.bottom_right
        self.top_left = (min(y1, y2), min(x1, x2))
        self.bottom_right = (max(y1, y2), max(x1, x2))

    def end_resize(self):
        """结束缩放操作"""
        if hasattr(self, '_resize_anchors'):
            del self._resize_anchors
            del self._resize_top_left
            del self._resize_bottom_right
            del self._resize_anchor_idx