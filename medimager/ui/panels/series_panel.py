#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
序列面板，用于显示已加载序列中的所有图像切片。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem
from PySide6.QtCore import Signal
from PySide6.QtGui import QWheelEvent
from typing import List, Optional
import pydicom

class SeriesPanel(QWidget):
    """
    左侧的序列面板，显示一个DICOM序列中的所有实例（切片）。
    """
    # 当用户在列表中选择一个切片时发出此信号
    # 参数: int - 所选切片的索引
    slice_selected = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_item_selected)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """鼠标滚轮事件，用于在列表中滚动切片"""
        num_degrees = event.angleDelta().y() / 8
        num_steps = num_degrees / 15
        
        # 根据滚轮方向计算要移动的行数
        scroll_direction = -1 if num_steps > 0 else 1
        
        current_row = self.list_widget.currentRow()
        new_row = current_row + scroll_direction
        # 确保新行在有效范围内
        if 0 <= new_row < self.list_widget.count():
            self.list_widget.setCurrentRow(new_row)
        event.accept()

    def update_series(self, dicom_files: List[pydicom.FileDataset]) -> None:
        """
        用新的DICOM文件列表更新面板。
        
        Args:
            dicom_files: pydicom.FileDataset 对象的列表。
        """
        self.list_widget.clear()
        if not dicom_files:
            return
            
        for i, ds in enumerate(dicom_files):
            # 尝试获取实例号，如果失败则使用索引+1
            instance_number = getattr(ds, 'InstanceNumber', i + 1)
            item_text = f"Image: {instance_number}"
            self.list_widget.addItem(QListWidgetItem(item_text))
    
    def clear(self) -> None:
        """
        清空列表。
        """
        self.list_widget.clear()

    def set_current_slice(self, index: int) -> None:
        """
        在列表中以编程方式设置当前选定的切片。
        
        Args:
            index: 要选择的切片的索引。
        """
        if 0 <= index < self.list_widget.count():
            # 暂时断开信号连接，避免在程序设置时触发循环信号
            self.list_widget.currentItemChanged.disconnect(self._on_item_selected)
            self.list_widget.setCurrentRow(index)
            self.list_widget.currentItemChanged.connect(self._on_item_selected)

    def _on_item_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        """
        当列表中的选择项改变时调用。
        """
        if current is not None:
            row = self.list_widget.row(current)
            self.slice_selected.emit(row) 