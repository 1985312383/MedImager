#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom window width/window level dialog."""

from typing import Optional, Tuple

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QVBoxLayout, QWidget

from medimager.utils.i18n import t


class CustomWLDialog(QDialog):
    """Dialog for entering window width and window level manually."""

    def __init__(self, current_width: int, current_level: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(t("dialogs.custom_wl.title"))

        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(1, 10000)
        self.width_spinbox.setValue(current_width)

        self.level_spinbox = QSpinBox()
        self.level_spinbox.setRange(-10000, 10000)
        self.level_spinbox.setValue(current_level)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        form_layout = QFormLayout()
        form_layout.addRow(t("dialogs.custom_wl.width"), self.width_spinbox)
        form_layout.addRow(t("dialogs.custom_wl.level"), self.level_spinbox)

        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)

    def get_values(self) -> Tuple[int, int]:
        return self.width_spinbox.value(), self.level_spinbox.value()

