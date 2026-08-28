#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Searchable, recursive DICOM metadata inspector."""

from __future__ import annotations

from typing import Optional

import pydicom
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from medimager.utils.i18n import t
from medimager.utils.settings import get_settings_manager


class DicomTagPanel(QWidget):
    """Display complete DICOM metadata without exposing bulk pixel bytes."""

    TAG_COLUMN = 0
    KEYWORD_COLUMN = 1
    NAME_COLUMN = 2
    VR_COLUMN = 3
    VALUE_COLUMN = 4
    _FULL_VALUE_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._dataset: Optional[pydicom.Dataset] = None
        self._settings_manager = self._find_settings_manager(parent)
        self._advanced_actions: dict[int, QAction] = {}

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(t("dicomtagpanel.search_placeholder"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName(t("dicomtagpanel.search_placeholder"))
        self.search_edit.textChanged.connect(self._apply_filter)

        self.show_private_checkbox = QCheckBox(t("dicomtagpanel.show_private"), self)
        self.show_private_checkbox.toggled.connect(self._rebuild_tree)

        self.advanced_columns_button = QToolButton(self)
        advanced_label = f"{t('dicomtagpanel.keyword')} / {t('dicomtagpanel.vr')}"
        self.advanced_columns_button.setText(advanced_label)
        self.advanced_columns_button.setToolTip(advanced_label)
        self.advanced_columns_button.setAccessibleName(advanced_label)
        self.advanced_columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        advanced_menu = QMenu(self.advanced_columns_button)
        self._add_advanced_column_action(advanced_menu, self.KEYWORD_COLUMN, t("dicomtagpanel.keyword"))
        self._add_advanced_column_action(advanced_menu, self.VR_COLUMN, t("dicomtagpanel.vr"))
        self.advanced_columns_button.setMenu(advanced_menu)

        self.tree_widget = QTreeWidget(self)
        self.tree_widget.setHeaderLabels([
            t("dicomtagpanel.tag"),
            t("dicomtagpanel.keyword"),
            t("dicomtagpanel.name"),
            t("dicomtagpanel.vr"),
            t("dicomtagpanel.value"),
        ])
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.setUniformRowHeights(True)
        self.tree_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree_widget.setAccessibleName(f"DICOM {t('dicomtagpanel.tag')}")
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._show_context_menu)
        header = self.tree_widget.header()
        header.setSectionResizeMode(self.TAG_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.KEYWORD_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.NAME_COLUMN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.VR_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.VALUE_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.tree_widget.setColumnWidth(self.NAME_COLUMN, 150)
        for column, action in self._advanced_actions.items():
            self.tree_widget.setColumnHidden(column, not action.isChecked())

        self.copy_row_action = QAction(t("dicomtagpanel.copy_row"), self.tree_widget)
        self.copy_row_action.setShortcut(QKeySequence.Copy)
        self.copy_row_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.copy_row_action.triggered.connect(self._copy_current_row)
        self.tree_widget.addAction(self.copy_row_action)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.search_edit)
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(self.show_private_checkbox)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.advanced_columns_button)
        layout.addLayout(controls_layout)
        layout.addWidget(self.tree_widget, 1)

    @staticmethod
    def _find_settings_manager(parent: Optional[QWidget]):
        candidate = parent
        while candidate is not None:
            manager = getattr(candidate, "settings_manager", None)
            if manager is not None:
                return manager
            candidate = candidate.parentWidget()
        return get_settings_manager()

    def _bool_setting(self, key: str, default: bool = False) -> bool:
        value = self._settings_manager.get_setting(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _add_advanced_column_action(
        self,
        menu: QMenu,
        column: int,
        label: str,
    ) -> None:
        key = f"dicom_tags.column_{column}_visible"
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(self._bool_setting(key, False))
        action.toggled.connect(
            lambda visible, target=column, setting_key=key: self._set_advanced_column_visible(
                target, setting_key, visible
            )
        )
        self._advanced_actions[column] = action

    def _set_advanced_column_visible(self, column: int, setting_key: str, visible: bool) -> None:
        self.tree_widget.setColumnHidden(column, not visible)
        self._settings_manager.set_setting(setting_key, bool(visible))

    def update_tags(self, dataset: Optional[pydicom.Dataset]) -> None:
        """Show one frame/dataset and preserve the current filter text."""
        self._dataset = dataset
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        self.tree_widget.setUpdatesEnabled(False)
        try:
            self.tree_widget.clear()
            if self._dataset is not None:
                self._add_dataset_items(self.tree_widget.invisibleRootItem(), self._dataset)
        finally:
            self.tree_widget.setUpdatesEnabled(True)
        self._apply_filter(self.search_edit.text())

    def _add_dataset_items(
        self,
        parent: QTreeWidgetItem,
        dataset: pydicom.Dataset,
        depth: int = 0,
    ) -> None:
        if depth > 16:
            return
        elements = sorted(dataset, key=lambda element: int(element.tag))
        for element in elements:
            if element.tag == (0x7FE0, 0x0010):
                continue
            if element.tag.is_private and not self.show_private_checkbox.isChecked():
                continue

            tag_text = f"({element.tag.group:04X},{element.tag.element:04X})"
            keyword = str(getattr(element, 'keyword', '') or '')
            name = str(getattr(element, 'name', '') or keyword or tag_text)
            vr = str(getattr(element, 'VR', '') or '')

            if vr == 'SQ':
                sequence = element.value or []
                full_value = t("dicomtagpanel.sequence_items", count=len(sequence))
                item = QTreeWidgetItem(parent, [tag_text, keyword, name, vr, full_value])
                item.setData(self.VALUE_COLUMN, self._FULL_VALUE_ROLE, full_value)
                for index, nested_dataset in enumerate(sequence):
                    nested_item = QTreeWidgetItem(
                        item,
                        [
                            f"[{index + 1}]",
                            '',
                            t("dicomtagpanel.sequence_item", index=index + 1),
                            '',
                            '',
                        ],
                    )
                    if isinstance(nested_dataset, pydicom.Dataset):
                        self._add_dataset_items(nested_item, nested_dataset, depth + 1)
                continue

            display_value, full_value = self._format_value(element.value)
            item = QTreeWidgetItem(parent, [tag_text, keyword, name, vr, display_value])
            item.setData(self.VALUE_COLUMN, self._FULL_VALUE_ROLE, full_value)
            for column in range(self.tree_widget.columnCount()):
                tooltip = full_value if column == self.VALUE_COLUMN else item.text(column)
                item.setToolTip(column, tooltip[:4096])

    @staticmethod
    def _format_value(value) -> tuple[str, str]:
        if isinstance(value, (bytes, bytearray, memoryview)):
            length = len(value)
            text = t("dicomtagpanel.binary_value", length=length)
            return text, text
        try:
            full = str(value)
        except Exception:
            full = repr(value)
        single_line = ' '.join(full.replace('\x00', '').splitlines())
        display = single_line if len(single_line) <= 512 else single_line[:509] + '...'
        return display, single_line

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()

        def update_item(item: QTreeWidgetItem) -> bool:
            own_match = not needle or any(
                needle in item.text(column).casefold()
                for column in range(self.tree_widget.columnCount())
            )
            child_match = False
            for index in range(item.childCount()):
                child_match = update_item(item.child(index)) or child_match
            visible = own_match or child_match
            item.setHidden(not visible)
            if needle and child_match:
                item.setExpanded(True)
            return visible

        root = self.tree_widget.invisibleRootItem()
        for index in range(root.childCount()):
            update_item(root.child(index))

    def _show_context_menu(self, position) -> None:
        item = self.tree_widget.itemAt(position)
        if item is None:
            return
        self.tree_widget.setCurrentItem(item)
        menu = QMenu(self)
        copy_value = menu.addAction(t("dicomtagpanel.copy_value"))
        copy_row = menu.addAction(t("dicomtagpanel.copy_row"))
        menu.addSeparator()
        expand_all = menu.addAction(t("dicomtagpanel.expand_all"))
        collapse_all = menu.addAction(t("dicomtagpanel.collapse_all"))
        selected = menu.exec(self.tree_widget.viewport().mapToGlobal(position))
        if selected is copy_value:
            value = item.data(self.VALUE_COLUMN, self._FULL_VALUE_ROLE) or item.text(self.VALUE_COLUMN)
            QApplication.clipboard().setText(str(value))
        elif selected is copy_row:
            self._copy_current_row()
        elif selected is expand_all:
            self.tree_widget.expandAll()
        elif selected is collapse_all:
            self.tree_widget.collapseAll()

    def _copy_current_row(self) -> None:
        item = self.tree_widget.currentItem()
        if item is None:
            return
        # Clipboard rows remain structurally complete even when Keyword/VR
        # are hidden in the compact default presentation.
        values = [item.text(column) for column in range(self.tree_widget.columnCount())]
        full_value = item.data(self.VALUE_COLUMN, self._FULL_VALUE_ROLE)
        if full_value is not None:
            values[self.VALUE_COLUMN] = str(full_value)
        QApplication.clipboard().setText('\t'.join(values))

    def clear(self) -> None:
        self._dataset = None
        self.tree_widget.clear()
