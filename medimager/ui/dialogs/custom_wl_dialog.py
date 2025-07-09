#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义窗宽窗位设置对话框。
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QSpinBox, 
    QDialogButtonBox, QWidget
)
from typing import Optional, Tuple
from PySide6.QtCore import QCoreApplication

class CustomWLDialog(QDialog):
    """
    一个用于手动输入窗宽(Window Width)和窗位(Window Level)的对话框。
    """
    def __init__(self, current_width: int, current_level: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("自定义窗宽窗位"))

        # 创建控件
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(1, 10000)
        self.width_spinbox.setValue(current_width)

        self.level_spinbox = QSpinBox()
        self.level_spinbox.setRange(-10000, 10000)
        self.level_spinbox.setValue(current_level)

        # 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # 布局
        form_layout = QFormLayout()
        form_layout.addRow(self.tr("窗宽 (Width):"), self.width_spinbox)
        form_layout.addRow(self.tr("窗位 (Level):"), self.level_spinbox)

        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)

    def get_values(self) -> Tuple[int, int]:
        """
        获取对话框中设置的窗宽和窗位值。
        """
        return self.width_spinbox.value(), self.level_spinbox.value()

    def tr(self, text):
        return QCoreApplication.translate("CustomWLDialog", text) 