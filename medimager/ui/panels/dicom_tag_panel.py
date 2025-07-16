#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM 标签面板，用于以树形结构显示 DICOM 文件的元数据。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt
from typing import Optional
import pydicom

class DicomTagPanel(QWidget):
    """
    右侧的 DICOM 标签面板，以一个按字母排序的列表显示元数据。
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.tree_widget = QTreeWidget()
        # 1. 移除 "Tag" 列，只保留 "Name" 和 "Value"
        self.tree_widget.setHeaderLabels([self.tr("Name"), self.tr("Value")])
        self.tree_widget.setColumnWidth(0, 200)
        # 自动拉伸第二列以填充剩余空间
        self.tree_widget.header().setStretchLastSection(True)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree_widget)
        self.setLayout(layout)

    def update_tags(self, dataset: Optional[pydicom.Dataset]) -> None:
        """
        使用新的 DICOM 数据集更新标签列表。
        
        Args:
            dataset: pydicom.Dataset 对象，如果为 None 则清空列表。
        """
        self.tree_widget.clear()
        if dataset is None:
            return

        # 2. 获取要显示的标签列表 (排除像素数据)
        tags_to_display = [de for de in dataset if de.tag != (0x7fe0, 0x0010)]

        # 3. 按标签名称的字母顺序排序
        tags_to_display.sort(key=lambda de: de.name)
            
        # 4. 将排序后的标签以扁平列表形式添加到控件中
        for data_element in tags_to_display:
            tag_name = data_element.name
            
            value = str(data_element.value)
            if len(value) > 256: # 稍微增加一点截断长度
                value = value[:256] + "..."
                
            QTreeWidgetItem(self.tree_widget, [tag_name, value])
    
    def clear(self) -> None:
        """
        清空树形控件。
        """
        self.tree_widget.clear()