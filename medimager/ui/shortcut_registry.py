"""Central, focus-safe keyboard shortcut registry for the main window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)


@dataclass(frozen=True)
class ShortcutSpec:
    command_id: str
    sequence: str
    description: str


class ShortcutRegistry(QObject):
    """Own application shortcuts and expose consistent tooltip suffixes.

    Plain-character shortcuts such as ``F`` and ``1`` must not fire while a
    user is typing in an editor.  Qt ``QAction`` shortcuts do not provide a
    convenient per-activation focus guard, so this registry owns QShortcut
    objects and performs that guard centrally.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._specs: Dict[str, ShortcutSpec] = {}
        self._shortcuts: Dict[str, QShortcut] = {}

    def register(
        self,
        command_id: str,
        sequence: str,
        description: str,
        callback: Callable[[], None],
        *,
        allow_in_editor: bool = False,
    ) -> QShortcut:
        if command_id in self._shortcuts:
            raise ValueError(f"Shortcut already registered: {command_id}")
        shortcut = QShortcut(QKeySequence(sequence), self._window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)

        def activate() -> None:
            if not allow_in_editor and self._focus_accepts_text():
                return
            callback()

        shortcut.activated.connect(activate)
        self._specs[command_id] = ShortcutSpec(
            command_id=command_id,
            sequence=sequence,
            description=description,
        )
        self._shortcuts[command_id] = shortcut
        return shortcut

    def sequence(self, command_id: str) -> str:
        spec = self._specs.get(command_id)
        return spec.sequence if spec else ""

    def tooltip(self, command_id: str, text: Optional[str] = None) -> str:
        spec = self._specs.get(command_id)
        if spec is None:
            return text or ""
        label = text or spec.description
        native = QKeySequence(spec.sequence).toString(QKeySequence.NativeText)
        return f"{label} ({native})" if native else label

    def apply_tooltip(
        self, widget: QWidget, command_id: str, text: Optional[str] = None
    ) -> None:
        widget.setToolTip(self.tooltip(command_id, text))

    def specs(self) -> tuple[ShortcutSpec, ...]:
        return tuple(self._specs.values())

    @staticmethod
    def _focus_accepts_text() -> bool:
        focus = QApplication.focusWidget()
        if isinstance(
            focus,
            (
                QLineEdit,
                QTextEdit,
                QPlainTextEdit,
                QAbstractSpinBox,
                QComboBox,
            ),
        ):
            return True
        return bool(focus and focus.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled))
