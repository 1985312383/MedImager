"""Presentation-only privacy mode for screen sharing and screenshots.

Privacy mode never mutates DICOM datasets, annotations, or patient-space
identity.  It is a UI shield and therefore cannot remove burned-in text from
pixel data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, Signal

from medimager.core.settings_registry import SETTINGS


class PrivacyService(QObject):
    """Central privacy state plus stable, session-local display aliases."""

    enabled_changed = Signal(bool)

    def __init__(self, settings_manager: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._persisted_enabled = bool(
            settings_manager.get_typed(SETTINGS["privacy.screen_mode"])
            if hasattr(settings_manager, "get_typed")
            else settings_manager.get_setting("privacy.screen_mode", False)
        )
        self._preview_enabled: Optional[bool] = None
        self._aliases: dict[str, dict[str, int]] = defaultdict(dict)
        changed = getattr(settings_manager, "setting_changed", None)
        if changed is not None:
            changed.connect(self._on_setting_changed)

    @property
    def enabled(self) -> bool:
        return (
            self._persisted_enabled
            if self._preview_enabled is None
            else self._preview_enabled
        )

    @property
    def hides_metadata(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if hasattr(self.settings_manager, "set_typed"):
            self.settings_manager.set_typed(SETTINGS["privacy.screen_mode"], enabled)
        else:
            self.settings_manager.set_setting("privacy.screen_mode", enabled)
        # Older manager stubs may not expose setting_changed.
        self._set_persisted(enabled)

    def set_preview(self, enabled: bool) -> None:
        previous = self.enabled
        self._preview_enabled = bool(enabled)
        if previous != self.enabled:
            self.enabled_changed.emit(self.enabled)

    def clear_preview(self) -> None:
        previous = self.enabled
        self._preview_enabled = None
        if previous != self.enabled:
            self.enabled_changed.emit(self.enabled)

    def alias_number(self, kind: str, stable_key: object) -> int:
        """Return a stable number without persisting or exposing the key."""

        category = str(kind or "item").strip().casefold() or "item"
        identity = str(stable_key or "unknown")
        aliases = self._aliases[category]
        if identity not in aliases:
            aliases[identity] = len(aliases) + 1
        return aliases[identity]

    def alias_for(
        self,
        kind: str,
        stable_key: object,
        original: str = "",
        prefix: Optional[str] = None,
    ) -> str:
        if not self.enabled:
            return str(original or "")
        label = prefix or str(kind or "Item").replace("_", " ").title()
        return f"{label} {self.alias_number(kind, stable_key):02d}"

    def _on_setting_changed(self, key: str, value: object) -> None:
        if key == "privacy.screen_mode":
            self._set_persisted(bool(value))

    def _set_persisted(self, enabled: bool) -> None:
        previous = self.enabled
        self._persisted_enabled = bool(enabled)
        if self._preview_enabled is not None:
            self._preview_enabled = None
        if previous != self.enabled:
            self.enabled_changed.emit(self.enabled)


_services: "WeakKeyDictionary[Any, PrivacyService]" = WeakKeyDictionary()


def get_privacy_service(settings_manager: Any = None) -> PrivacyService:
    if settings_manager is None:
        from medimager.utils.settings import get_settings_manager

        settings_manager = get_settings_manager()
    service = _services.get(settings_manager)
    if service is None:
        parent = settings_manager if isinstance(settings_manager, QObject) else None
        service = PrivacyService(settings_manager, parent)
        _services[settings_manager] = service
    return service

