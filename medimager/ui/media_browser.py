"""Patient/Study/Series browser for a pre-indexed local DICOM medium."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from medimager.core.local_source import (
    LocalIndexResult,
    LocalIssueSeverity,
    LocalSelection,
)
from medimager.utils.i18n import t


def _tr(key: str, fallback: str, **params) -> str:
    value = t(key, **params)
    if value == key:
        try:
            return fallback.format(**params)
        except (KeyError, ValueError):
            return fallback
    return value


class MediaBrowserPage(QWidget):
    """Select studies or series from an immutable ``LocalIndexResult``."""

    selection_confirmed = Signal(object)
    back_requested = Signal()
    cancel_requested = Signal()
    scan_as_folder_requested = Signal(str)

    KIND_ROLE = Qt.ItemDataRole.UserRole
    STUDY_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
    SERIES_UID_ROLE = Qt.ItemDataRole.UserRole + 2
    VIEWABLE_ROLE = Qt.ItemDataRole.UserRole + 3
    KIND_PATIENT = "patient"
    KIND_STUDY = "study"
    KIND_SERIES = "series"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaBrowserPage")
        self._index: LocalIndexResult | None = None
        self._updating_checks = False
        self._privacy_enabled = False
        self._setup_ui()
        self.retranslate_ui()

    @property
    def index_result(self) -> LocalIndexResult | None:
        return self._index

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton(self)
        self.back_button.clicked.connect(self.back_requested)
        header.addWidget(self.back_button)
        self.title_label = QLabel(self)
        title_font = self.title_label.font()
        title_font.setPointSize(17)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        header.addWidget(self.title_label)
        header.addStretch(1)
        root.addLayout(header)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setWordWrap(True)
        root.addWidget(self.subtitle_label)

        self.progress_frame = QFrame(self)
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(10, 8, 10, 8)
        self.progress_label = QLabel(self.progress_frame)
        progress_layout.addWidget(self.progress_label, 1)
        self.progress_bar = QProgressBar(self.progress_frame)
        self.progress_bar.setRange(0, 0)
        progress_layout.addWidget(self.progress_bar)
        self.cancel_button = QPushButton(self.progress_frame)
        self.cancel_button.clicked.connect(self.cancel_requested)
        progress_layout.addWidget(self.cancel_button)
        self.progress_frame.hide()
        root.addWidget(self.progress_frame)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("DicomDirStudyTree")
        self.tree.setColumnCount(4)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.tree, 1)

        self.issue_label = QLabel(self)
        self.issue_label.setObjectName("MediaBrowserIssues")
        self.issue_label.setWordWrap(True)
        self.issue_label.hide()
        root.addWidget(self.issue_label)

        footer = QHBoxLayout()
        self.summary_label = QLabel(self)
        footer.addWidget(self.summary_label, 1)
        self.scan_folder_button = QPushButton(self)
        self.scan_folder_button.clicked.connect(self._request_folder_scan)
        footer.addWidget(self.scan_folder_button)
        self.open_button = QPushButton(self)
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._confirm_selection)
        footer.addWidget(self.open_button)
        root.addLayout(footer)

        self.setStyleSheet(
            """
            #DicomDirStudyTree { border: 1px solid palette(mid); border-radius: 6px; }
            #MediaBrowserIssues { padding: 8px; border: 1px solid palette(mid); border-radius: 5px; }
            """
        )

    def retranslate_ui(self) -> None:
        self.back_button.setText(_tr("mediabrowser.back", "Back"))
        self.title_label.setText(_tr("mediabrowser.title", "DICOM media browser"))
        self.subtitle_label.setText(
            _tr(
                "mediabrowser.subtitle",
                "Choose the studies or individual series to load from this read-only medium.",
            )
        )
        self.cancel_button.setText(_tr("mediabrowser.cancel", "Cancel"))
        self.scan_folder_button.setText(
            _tr("mediabrowser.scan_folder", "Scan media as folder")
        )
        self.open_button.setText(_tr("mediabrowser.open_selected", "Open selected"))
        self.tree.setHeaderLabels(
            [
                _tr("mediabrowser.name", "Patient / study / series"),
                _tr("mediabrowser.modality", "Modality"),
                _tr("mediabrowser.date", "Date"),
                _tr("mediabrowser.instances", "Images"),
            ]
        )
        self._update_summary()

    def set_index(self, result: LocalIndexResult) -> None:
        self._index = result
        self._updating_checks = True
        try:
            self.tree.clear()
            patients: dict[str, QTreeWidgetItem] = {}
            first_study: QTreeWidgetItem | None = None
            patient_aliases: dict[str, int] = {}
            study_number = 0
            series_number = 0
            for study in result.studies:
                patient_key = study.patient_id.strip() or study.patient_name.strip() or study.study_key
                patient_item = patients.get(patient_key)
                if patient_item is None:
                    patient_label = study.patient_name.strip() or study.patient_id.strip()
                    patient_aliases[patient_key] = len(patient_aliases) + 1
                    if self._privacy_enabled:
                        patient_label = _tr(
                            "mediabrowser.private_patient",
                            "Patient {number:02d}",
                            number=patient_aliases[patient_key],
                        )
                    patient_item = QTreeWidgetItem(
                        self.tree,
                        [patient_label or _tr("mediabrowser.unknown_patient", "Unknown patient")],
                    )
                    patient_item.setData(0, self.KIND_ROLE, self.KIND_PATIENT)
                    patient_item.setFlags(
                        patient_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsAutoTristate
                    )
                    patient_item.setCheckState(0, Qt.CheckState.Unchecked)
                    patients[patient_key] = patient_item
                study_label = study.study_description.strip() or _tr(
                    "mediabrowser.unnamed_study", "Unnamed study"
                )
                study_number += 1
                if self._privacy_enabled:
                    study_label = _tr(
                        "mediabrowser.private_study",
                        "Study {number:02d}",
                        number=study_number,
                    )
                study_item = QTreeWidgetItem(
                    patient_item,
                    [
                        study_label,
                        "/".join(study.modalities),
                        study.study_date,
                        str(study.instance_count),
                    ],
                )
                study_item.setData(0, self.KIND_ROLE, self.KIND_STUDY)
                study_item.setData(0, self.STUDY_KEY_ROLE, study.study_key)
                study_item.setFlags(
                    study_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsAutoTristate
                )
                study_item.setCheckState(0, Qt.CheckState.Unchecked)
                for series in study.series:
                    label = series.series_description.strip() or _tr(
                        "mediabrowser.unnamed_series", "Unnamed series"
                    )
                    series_number += 1
                    if self._privacy_enabled:
                        label = _tr(
                            "mediabrowser.private_series",
                            "Series {number:02d}",
                            number=series_number,
                        )
                    series_item = QTreeWidgetItem(
                        study_item,
                        [label, series.modality, series.acquisition_date, str(series.slice_count)],
                    )
                    series_item.setData(0, self.KIND_ROLE, self.KIND_SERIES)
                    series_item.setData(0, self.STUDY_KEY_ROLE, study.study_key)
                    series_item.setData(
                        0, self.SERIES_UID_ROLE, series.series_instance_uid
                    )
                    series_item.setData(0, self.VIEWABLE_ROLE, series.is_viewable)
                    if series.is_viewable:
                        series_item.setFlags(
                            series_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                        )
                        series_item.setCheckState(0, Qt.CheckState.Unchecked)
                        if first_study is None:
                            first_study = study_item
                    else:
                        series_item.setFlags(
                            series_item.flags()
                            & ~Qt.ItemFlag.ItemIsEnabled
                            & ~Qt.ItemFlag.ItemIsSelectable
                        )
                        series_item.setText(
                            3,
                            _tr("mediabrowser.not_viewable", "Not viewable"),
                        )
                        series_item.setToolTip(0, series.unsupported_reason)
            if first_study is not None:
                self._set_subtree_check_state(first_study, Qt.CheckState.Checked)
                first_study.setExpanded(True)
                if first_study.parent() is not None:
                    first_study.parent().setExpanded(True)
            self.tree.resizeColumnToContents(0)
        finally:
            self._updating_checks = False
        self.progress_frame.hide()
        self._show_issues(result)
        self._update_summary()

    def set_privacy_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._privacy_enabled == enabled:
            return
        self._privacy_enabled = enabled
        if self._index is not None:
            self.set_index(self._index)

    def clear_index(self) -> None:
        self._index = None
        self.tree.clear()
        self.issue_label.hide()
        self.progress_frame.hide()
        self._update_summary()

    def set_busy(self, message: str, *, cancellable: bool = True) -> None:
        self.progress_label.setText(str(message))
        self.progress_bar.setRange(0, 0)
        self.cancel_button.setVisible(bool(cancellable))
        self.progress_frame.show()
        self.tree.setEnabled(False)
        self.open_button.setEnabled(False)

    def set_progress(self, completed: int, total: int, message: str = "") -> None:
        if message:
            self.progress_label.setText(str(message))
        self.progress_bar.setRange(0, max(1, int(total)))
        self.progress_bar.setValue(max(0, min(int(completed), int(total))))
        self.progress_frame.show()

    def set_idle(self) -> None:
        self.progress_frame.hide()
        self.tree.setEnabled(True)
        self._update_summary()

    def set_error(self, message: str, *, allow_folder_scan: bool = True) -> None:
        self.progress_frame.hide()
        self.tree.setEnabled(False)
        self.issue_label.setText(str(message))
        self.issue_label.show()
        self.scan_folder_button.setVisible(bool(allow_folder_scan))
        self.open_button.setEnabled(False)

    def selected_selection(self) -> LocalSelection:
        study_keys: list[str] = []
        series_uids: list[str] = []
        for patient_index in range(self.tree.topLevelItemCount()):
            patient = self.tree.topLevelItem(patient_index)
            for study_index in range(patient.childCount()):
                study = patient.child(study_index)
                study_key = str(study.data(0, self.STUDY_KEY_ROLE) or "")
                checked_series = [
                    study.child(index)
                    for index in range(study.childCount())
                    if study.child(index).checkState(0) is Qt.CheckState.Checked
                ]
                if checked_series and len(checked_series) == study.childCount():
                    study_keys.append(study_key)
                else:
                    series_uids.extend(
                        str(item.data(0, self.SERIES_UID_ROLE) or "")
                        for item in checked_series
                        if item.data(0, self.SERIES_UID_ROLE)
                    )
        return LocalSelection(tuple(study_keys), tuple(series_uids))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if state is not Qt.CheckState.PartiallyChecked:
                self._set_subtree_check_state(item, state)
            self._refresh_parent_check_state(item.parent())
        finally:
            self._updating_checks = False
        self._update_summary()

    def _set_subtree_check_state(
        self, item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        if item.data(0, self.KIND_ROLE) != self.KIND_SERIES or bool(
            item.data(0, self.VIEWABLE_ROLE)
        ):
            item.setCheckState(0, state)
        for index in range(item.childCount()):
            self._set_subtree_check_state(item.child(index), state)

    def _refresh_parent_check_state(self, item: QTreeWidgetItem | None) -> None:
        while item is not None:
            states = [item.child(index).checkState(0) for index in range(item.childCount())]
            if states and all(state is Qt.CheckState.Checked for state in states):
                item.setCheckState(0, Qt.CheckState.Checked)
            elif states and all(state is Qt.CheckState.Unchecked for state in states):
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setCheckState(0, Qt.CheckState.PartiallyChecked)
            item = item.parent()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, self.KIND_ROLE) == self.KIND_SERIES:
            self._confirm_selection()

    def _confirm_selection(self) -> None:
        selection = self.selected_selection()
        if not selection.is_empty:
            self.selection_confirmed.emit(selection)

    def _request_folder_scan(self) -> None:
        if self._index is not None and self._index.media_root:
            self.scan_as_folder_requested.emit(self._index.media_root)

    def _show_issues(self, result: LocalIndexResult) -> None:
        visible_issues = [
            issue
            for issue in result.issues
            if issue.severity
            in {
                LocalIssueSeverity.WARNING,
                LocalIssueSeverity.ERROR,
                LocalIssueSeverity.FATAL,
            }
        ]
        if not visible_issues:
            self.issue_label.hide()
            self.scan_folder_button.setVisible(False)
            return
        messages = [issue.detail for issue in visible_issues[:4] if issue.detail]
        remaining = len(visible_issues) - len(messages)
        if remaining > 0:
            messages.append(
                _tr("mediabrowser.more_issues", "{count} more issues", count=remaining)
            )
        self.issue_label.setText("\n".join(f"• {message}" for message in messages))
        self.issue_label.show()
        self.scan_folder_button.setVisible(result.has_fatal_issue)

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        selection = self.selected_selection() if self._index is not None else LocalSelection()
        selected = self._index.select(selection) if self._index is not None else ()
        self.summary_label.setText(
            _tr(
                "mediabrowser.selection_summary",
                "{series_count} series selected",
                series_count=len(selected),
            )
        )
        self.open_button.setEnabled(bool(selected) and not self.progress_frame.isVisible())


__all__ = ["MediaBrowserPage"]
