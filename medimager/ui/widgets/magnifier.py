#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
像素放大镜控件
"""
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QImage, QPixmap
from typing import Optional

class MagnifierWidget(QWidget):
    """一个显示鼠标周围像素放大视图的悬浮小部件。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setAttribute(Qt.WA_TransparentForMouseEvents) # 让鼠标事件穿透此控件
        self.hide()

        self.zoom_level = 8
        self.source_image: Optional[QImage] = None
        self.source_rect: Optional[QRect] = None
        
    def update_magnifier(self, source_image: QImage, source_rect: QRect):
        """
        更新放大镜内容。
        
        Args:
            source_image: 完整的原始图像 (QImage)。
            source_rect: 要放大的源区域 (在 source_image 中的坐标)。
        """
        self.source_image = source_image
        self.source_rect = source_rect
        self.update() # 触发 paintEvent

    def paintEvent(self, event):
        """绘制放大后的图像和网格"""
        if self.source_image is None or self.source_rect is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        # 绘制背景
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        # 绘制放大后的图像
        target_rect = self.rect()
        painter.drawImage(target_rect, self.source_image, self.source_rect)
        
        # 绘制网格
        pen = QPen(QColor(255, 255, 255, 80))
        pen.setWidth(1)
        painter.setPen(pen)

        grid_size = self.source_rect.width()
        cell_width = self.width() / grid_size
        cell_height = self.height() / grid_size

        for i in range(1, grid_size):
            x = int(i * cell_width)
            y = int(i * cell_height)
            painter.drawLine(x, 0, x, self.height())
            painter.drawLine(0, y, self.width(), y)
            
        # 绘制中心十字标记
        center_pen = QPen(QColor("magenta"))
        center_pen.setWidth(1)
        painter.setPen(center_pen)
        
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        painter.drawLine(center_x, 0, center_x, self.height())
        painter.drawLine(0, center_y, self.width(), center_y) 