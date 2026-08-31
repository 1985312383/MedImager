"""Standalone startup center for local studies and sample cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from medimager.core.local_source import RecentStudyEntry
from medimager.utils.i18n import t
from medimager.utils.resource_path import get_icon_path


class StartCenterState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"


class RecentAvailability(str, Enum):
    CHECKING = "checking"
    AVAILABLE = "available"
    MISSING = "missing"


@dataclass(frozen=True)
class StartCenterSample:
    sample_id: str
    title: str
    subtitle: str = ""
    preview_path: str = ""


def _tr(key: str, fallback: str, **params) -> str:
    value = t(key, **params)
    if value == key:
        try:
            return fallback.format(**params)
        except (KeyError, ValueError):
            return fallback
    return value


class StartCenter(QWidget):
    """A non-modal home page with stable integration signals.

    The widget never opens a QFileDialog or touches SettingsManager. The host
    controls those concerns and supplies recent entries asynchronously.
    """

    open_folder_requested = Signal()
    open_multiple_folders_requested = Signal()
    open_dicomdir_requested = Signal()
    open_image_requested = Signal()
    recent_requested = Signal(str)
    recent_remove_requested = Signal(str)
    recent_relocate_requested = Signal(str)
    recent_pin_requested = Signal(str, bool)
    clear_recent_requested = Signal()
    sample_requested = Signal(str)
    cancel_requested = Signal()
    paths_dropped = Signal(object)

    ENTRY_ID_ROLE = Qt.ItemDataRole.UserRole
    PINNED_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StartCenter")
        self.setAcceptDrops(True)
        self._state = StartCenterState.IDLE
        self._recent_entries: tuple[RecentStudyEntry, ...] = ()
        self._availability: dict[str, RecentAvailability] = {}
        self._samples: tuple[StartCenterSample, ...] = ()
        self._privacy_enabled = False
        self._setup_ui()
        self.retranslate_ui()

    @property
    def state(self) -> StartCenterState:
        return self._state

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setObjectName("StartCenterScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        wrapper = QWidget(scroll)
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget(wrapper)
        content.setObjectName("StartCenterContent")
        content.setMaximumWidth(1040)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 30, 36, 36)
        layout.setSpacing(20)
        wrapper_layout.addStretch(1)
        wrapper_layout.addWidget(content, 1)
        wrapper_layout.addStretch(1)
        scroll.setWidget(wrapper)

        self.title_label = QLabel(content)
        self.title_label.setObjectName("StartCenterTitle")
        title_font = self.title_label.font()
        title_font.setPointSize(23)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(content)
        self.subtitle_label.setObjectName("StartCenterSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(12)
        self.open_folder_button = self._action_button(
            QStyle.StandardPixmap.SP_DirOpenIcon,
            self.open_folder_requested.emit,
        )
        self.open_dicomdir_button = self._action_button(
            QStyle.StandardPixmap.SP_DriveCDIcon,
            self.open_dicomdir_requested.emit,
        )
        self.open_image_button = self._action_button(
            QStyle.StandardPixmap.SP_FileIcon,
            self.open_image_requested.emit,
        )
        self.open_multiple_button = self._action_button(
            QStyle.StandardPixmap.SP_DirIcon,
            self.open_multiple_folders_requested.emit,
        )
        for index, button in enumerate(
            (
                self.open_folder_button,
                self.open_dicomdir_button,
                self.open_image_button,
                self.open_multiple_button,
            )
        ):
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)

        self.status_frame = QFrame(content)
        self.status_frame.setObjectName("StartCenterStatus")
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(12, 10, 12, 10)
        self.status_label = QLabel(self.status_frame)
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label, 1)
        self.progress_bar = QProgressBar(self.status_frame)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumWidth(180)
        status_layout.addWidget(self.progress_bar)
        self.cancel_button = QPushButton(self.status_frame)
        self.cancel_button.clicked.connect(self.cancel_requested)
        status_layout.addWidget(self.cancel_button)
        self.status_frame.hide()
        layout.addWidget(self.status_frame)

        recent_header = QHBoxLayout()
        self.recent_title = QLabel(content)
        recent_font = self.recent_title.font()
        recent_font.setPointSize(13)
        recent_font.setBold(True)
        self.recent_title.setFont(recent_font)
        recent_header.addWidget(self.recent_title)
        recent_header.addStretch(1)
        self.clear_recent_button = QPushButton(content)
        self.clear_recent_button.clicked.connect(self.clear_recent_requested)
        recent_header.addWidget(self.clear_recent_button)
        layout.addLayout(recent_header)

        self.recent_list = QListWidget(content)
        self.recent_list.setObjectName("RecentStudyList")
        self.recent_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recent_list.setAlternatingRowColors(True)
        self.recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._show_recent_menu)
        self.recent_list.itemActivated.connect(self._activate_recent_item)
        # Keep the three one-click teaching cases discoverable in the first
        # 1280x800 viewport.  Longer recent histories remain scrollable inside
        # this bounded list instead of pushing every sample action below fold.
        self.recent_list.setMinimumHeight(132)
        self.recent_list.setMaximumHeight(156)
        layout.addWidget(self.recent_list)

        self.recent_empty_label = QLabel(content)
        self.recent_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_empty_label.setWordWrap(True)
        layout.addWidget(self.recent_empty_label)

        self.samples_frame = QFrame(content)
        self.samples_frame.setObjectName("StartCenterSamples")
        self.samples_layout = QVBoxLayout(self.samples_frame)
        self.samples_layout.setContentsMargins(0, 0, 0, 0)
        self.samples_title = QLabel(self.samples_frame)
        sample_font = self.samples_title.font()
        sample_font.setPointSize(13)
        sample_font.setBold(True)
        self.samples_title.setFont(sample_font)
        self.samples_layout.addWidget(self.samples_title)
        self._sample_buttons_layout = QGridLayout()
        self.samples_layout.addLayout(self._sample_buttons_layout)
        self.samples_frame.hide()
        layout.addWidget(self.samples_frame)
        self.disclaimer_label = QLabel(content)
        self.disclaimer_label.setObjectName("StartCenterDisclaimer")
        self.disclaimer_label.setWordWrap(True)
        self.disclaimer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.disclaimer_label)
        layout.addStretch(1)

        self.setStyleSheet(
            """
            #StartCenterContent { background: transparent; }
            #StartCenterStatus { border: 1px solid palette(mid); border-radius: 6px; }
            #RecentStudyList { border: 1px solid palette(mid); border-radius: 6px; padding: 4px; }
            QPushButton[startAction="true"] {
                min-height: 54px; text-align: left; padding: 9px 14px;
                border: 1px solid palette(mid); border-radius: 7px;
            }
            QPushButton[startAction="true"]:hover { border-color: palette(highlight); }
            """
        )

    def _action_button(self, pixmap: QStyle.StandardPixmap, callback) -> QPushButton:
        button = QPushButton(self)
        button.setProperty("startAction", True)
        button.setIcon(self.style().standardIcon(pixmap))
        button.setIconSize(button.iconSize() * 1.25)
        button.clicked.connect(callback)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return button

    def retranslate_ui(self) -> None:
        self.title_label.setText(_tr("startcenter.title", "Open a medical imaging study"))
        self.subtitle_label.setText(
            _tr(
                "startcenter.subtitle",
                "Open local DICOM media, resume a recent study, or load a bundled sample.",
            )
        )
        self.open_folder_button.setText(_tr("startcenter.open_folder", "Open DICOM folder"))
        self.open_dicomdir_button.setText(_tr("startcenter.open_dicomdir", "Open DICOMDIR media"))
        self.open_image_button.setText(_tr("startcenter.open_image", "Open image file"))
        self.open_multiple_button.setText(
            _tr("startcenter.open_multiple", "Open multiple DICOM folders")
        )
        self.cancel_button.setText(_tr("startcenter.cancel", "Cancel"))
        self.recent_title.setText(_tr("startcenter.recent", "Recent studies"))
        self.clear_recent_button.setText(_tr("startcenter.clear_recent", "Clear"))
        self.recent_empty_label.setText(
            _tr("startcenter.no_recent", "Successfully opened local studies will appear here.")
        )
        self.samples_title.setText(_tr("startcenter.samples", "Sample studies"))
        self.disclaimer_label.setText(
            _tr(
                "startcenter.disclaimer",
                "For research and teaching only. MedImager is not a diagnostic device.",
            )
        )
        self._refresh_recent_list()

    def set_privacy_mode(self, enabled: bool) -> None:
        self._privacy_enabled = bool(enabled)
        self._refresh_recent_list()

    def set_recent_entries(
        self,
        entries: Sequence[RecentStudyEntry],
        availability: Mapping[str, RecentAvailability | str | bool | None] | None = None,
    ) -> None:
        self._recent_entries = tuple(entries)
        self._availability = {
            entry_id: self._coerce_availability(value)
            for entry_id, value in (availability or {}).items()
        }
        self._refresh_recent_list()

    def update_recent_availability(
        self,
        entry_id: str,
        availability: RecentAvailability | str | bool | None,
    ) -> None:
        self._availability[str(entry_id)] = self._coerce_availability(availability)
        self._refresh_recent_list()

    @staticmethod
    def _coerce_availability(value) -> RecentAvailability:
        if value is True:
            return RecentAvailability.AVAILABLE
        if value is False:
            return RecentAvailability.MISSING
        if value is None:
            return RecentAvailability.CHECKING
        return RecentAvailability(value)

    def _refresh_recent_list(self) -> None:
        if not hasattr(self, "recent_list"):
            return
        selected_id = self._selected_recent_id()
        self.recent_list.clear()
        for entry_index, entry in enumerate(self._recent_entries, start=1):
            availability = self._availability.get(
                entry.entry_id, RecentAvailability.CHECKING
            )
            modalities = "/".join(entry.modalities) or "DICOM"
            details = _tr(
                "startcenter.recent_details",
                "{modalities} · {series_count} series",
                modalities=modalities,
                series_count=entry.series_count,
            )
            if entry.study_date:
                details = f"{entry.study_date} · {details}"
            if entry.patient_label and not self._privacy_enabled:
                details = f"{entry.patient_label} · {details}"
            prefix = "★ " if entry.pinned else ""
            suffix = ""
            if availability is RecentAvailability.MISSING:
                suffix = "  — " + _tr("startcenter.media_missing", "media unavailable")
            elif availability is RecentAvailability.CHECKING:
                suffix = "  — " + _tr("startcenter.media_checking", "checking media…")
            display_label = (
                _tr("startcenter.private_study", "Study {number:02d}", number=entry_index)
                if self._privacy_enabled
                else entry.display_label
            )
            item = QListWidgetItem(f"{prefix}{display_label}{suffix}\n{details}")
            item.setData(self.ENTRY_ID_ROLE, entry.entry_id)
            item.setData(self.PINNED_ROLE, entry.pinned)
            item.setToolTip("" if self._privacy_enabled else entry.source_path)
            if availability is RecentAvailability.MISSING:
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            else:
                primary_modality = next(iter(entry.modalities), "").upper()
                icon_name = {
                    "CT": "modality-ct.svg",
                    "MR": "modality-mr.svg",
                }.get(primary_modality, "modality-generic.svg")
                icon = QIcon(get_icon_path(icon_name))
            item.setIcon(icon)
            if availability is RecentAvailability.MISSING:
                item.setForeground(self.palette().brush(self.foregroundRole()))
            self.recent_list.addItem(item)
            if entry.entry_id == selected_id:
                item.setSelected(True)
        visible = bool(self._recent_entries)
        self.recent_list.setVisible(visible)
        self.recent_empty_label.setVisible(not visible)
        self.clear_recent_button.setEnabled(visible)

    def _selected_recent_id(self) -> str:
        item = self.recent_list.currentItem() if hasattr(self, "recent_list") else None
        return str(item.data(self.ENTRY_ID_ROLE)) if item is not None else ""

    def _activate_recent_item(self, item: QListWidgetItem) -> None:
        entry_id = str(item.data(self.ENTRY_ID_ROLE) or "")
        if not entry_id:
            return
        availability = self._availability.get(entry_id, RecentAvailability.CHECKING)
        if availability is RecentAvailability.MISSING:
            self.recent_relocate_requested.emit(entry_id)
        else:
            self.recent_requested.emit(entry_id)

    def _show_recent_menu(self, position) -> None:
        item = self.recent_list.itemAt(position)
        if item is None:
            return
        entry_id = str(item.data(self.ENTRY_ID_ROLE) or "")
        pinned = bool(item.data(self.PINNED_ROLE))
        menu = QMenu(self)
        open_action = menu.addAction(_tr("startcenter.open_recent", "Open"))
        locate_action = menu.addAction(_tr("startcenter.relocate_recent", "Locate media…"))
        pin_action = menu.addAction(
            _tr("startcenter.unpin_recent", "Unpin")
            if pinned
            else _tr("startcenter.pin_recent", "Pin")
        )
        menu.addSeparator()
        remove_action = menu.addAction(_tr("startcenter.remove_recent", "Remove from recent"))
        selected = menu.exec(self.recent_list.viewport().mapToGlobal(position))
        if selected is open_action:
            self.recent_requested.emit(entry_id)
        elif selected is locate_action:
            self.recent_relocate_requested.emit(entry_id)
        elif selected is pin_action:
            self.recent_pin_requested.emit(entry_id, not pinned)
        elif selected is remove_action:
            self.recent_remove_requested.emit(entry_id)

    def set_samples(self, samples: Sequence[StartCenterSample]) -> None:
        self._samples = tuple(samples)
        while self._sample_buttons_layout.count():
            item = self._sample_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, sample in enumerate(self._samples):
            card = QFrame(self.samples_frame)
            card.setObjectName("StartCenterSampleCard")
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(5)
            button = QPushButton(sample.title, card)
            button.setProperty("startAction", True)
            button.setToolTip(sample.subtitle)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            button.clicked.connect(
                lambda checked=False, sample_id=sample.sample_id: self.sample_requested.emit(
                    sample_id
                )
            )
            # The title is the primary launch target and must remain visible
            # even when a short window requires the preview/description area
            # to scroll.
            card_layout.addWidget(button)
            if sample.preview_path:
                preview = QLabel(card)
                preview.setObjectName("StartCenterSamplePreview")
                preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview.setPixmap(QIcon(sample.preview_path).pixmap(QSize(168, 96)))
                preview.setMinimumHeight(96)
                card_layout.addWidget(preview)
            if sample.subtitle:
                description = QLabel(sample.subtitle, card)
                description.setObjectName("StartCenterSampleDescription")
                description.setWordWrap(True)
                # A word-wrapped QLabel otherwise contributes its unwrapped
                # text width to the card's minimum size on Windows.  Ignore
                # that horizontal hint so the three cards can shrink and the
                # layout can reflow the description vertically at high DPI.
                description.setSizePolicy(
                    QSizePolicy.Policy.Ignored,
                    QSizePolicy.Policy.Preferred,
                )
                description.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                )
                card_layout.addWidget(description)
            card_layout.addStretch(1)
            self._sample_buttons_layout.addWidget(card, index // 3, index % 3)
        self.samples_frame.setVisible(bool(self._samples))

    def set_busy(
        self,
        message: str,
        *,
        completed: int | None = None,
        total: int | None = None,
        cancellable: bool = True,
    ) -> None:
        self._state = StartCenterState.BUSY
        self.status_frame.setProperty("state", "busy")
        self.status_label.setText(str(message))
        if completed is None or total is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, max(1, int(total)))
            self.progress_bar.setValue(max(0, min(int(total), int(completed))))
        self.progress_bar.show()
        self.cancel_button.setVisible(bool(cancellable))
        self.status_frame.show()
        self._set_open_actions_enabled(False)

    def set_error(self, message: str) -> None:
        self._state = StartCenterState.ERROR
        self.status_frame.setProperty("state", "error")
        self.status_label.setText(str(message))
        self.progress_bar.hide()
        self.cancel_button.hide()
        self.status_frame.show()
        self._set_open_actions_enabled(True)

    def set_idle(self) -> None:
        self._state = StartCenterState.IDLE
        self.status_frame.hide()
        self._set_open_actions_enabled(True)

    def _set_open_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.open_folder_button,
            self.open_dicomdir_button,
            self.open_image_button,
            self.open_multiple_button,
        ):
            button.setEnabled(enabled)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._local_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._local_paths(event.mimeData().urls())
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _local_paths(urls: Sequence[QUrl]) -> tuple[str, ...]:
        return tuple(
            str(Path(url.toLocalFile()).resolve(strict=False))
            for url in urls
            if url.isLocalFile() and url.toLocalFile()
        )


__all__ = [
    "RecentAvailability",
    "StartCenter",
    "StartCenterSample",
    "StartCenterState",
]
