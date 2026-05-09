#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internationalization helpers.

The new application text path is key-based:

    t("settings.title")
    t("viewer.active_view", position="1x1")

Human-maintained source files live under ``medimager/i18n/locales`` as YAML.
Runtime reads compiled JSON catalogs from ``medimager/i18n/compiled``.
Application code should use stable message keys through ``t("...")``.
"""

from __future__ import annotations

import json
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QObject, Signal
from PySide6.QtWidgets import QApplication

from medimager.utils.logger import get_logger
from medimager.utils.resource_path import get_resource_path

logger = get_logger(__name__)


DEFAULT_LANGUAGE = "en_US"


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    name: str
    fallback: Optional[str] = DEFAULT_LANGUAGE


class TranslationManager(QObject):
    """Manage key-based translation catalogs."""

    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.app = QCoreApplication.instance()
        self._subscribers = weakref.WeakSet()
        self._language = DEFAULT_LANGUAGE
        self._catalogs: dict[str, dict[str, str]] = {}
        self._metadata: dict[str, LanguageInfo] = {}
        self._load_catalog(DEFAULT_LANGUAGE)

    def set_language(self, language_code: str) -> bool:
        """Switch the active key-based catalog."""
        if not self._load_catalog(language_code):
            logger.error("Translation catalog does not exist: %s", language_code)
            return False

        self._language = language_code
        self._notify_language_changed(language_code)
        return True

    def load_translation(self, language_code: str) -> bool:
        """Compatibility wrapper used by existing code."""
        return self.set_language(language_code)

    def current_language(self) -> str:
        return self._language

    def t(self, key: str, **params: Any) -> str:
        """Translate a stable key with named placeholders."""
        text = self._lookup(key)
        if params:
            try:
                return text.format(**params)
            except Exception as exc:
                logger.error("Failed to format translation %s with %s: %s", key, params, exc)
        return text

    def available_language_info(self) -> list[LanguageInfo]:
        """Return language metadata from compiled catalogs."""
        languages: list[LanguageInfo] = []
        compiled_dir = self._compiled_dir()
        if not compiled_dir.exists():
            return [LanguageInfo(DEFAULT_LANGUAGE, "English", None)]

        for catalog_file in sorted(compiled_dir.glob("*.json")):
            info = self._read_catalog_metadata(catalog_file)
            if info:
                languages.append(info)

        if not any(info.code == DEFAULT_LANGUAGE for info in languages):
            languages.insert(0, LanguageInfo(DEFAULT_LANGUAGE, "English", None))
        return languages

    def get_available_languages(self) -> list[str]:
        """Return available language codes.

        Kept for existing settings UI code.  New code should prefer
        ``available_language_info`` when it needs display names.
        """
        languages = [info.code for info in self.available_language_info()]

        return languages

    def get_system_language(self) -> str:
        language_code = QLocale.system().name()
        if language_code in self.get_available_languages():
            return language_code
        return DEFAULT_LANGUAGE

    def subscribe(self, widget: Any) -> None:
        if hasattr(widget, "retranslate_ui"):
            self._subscribers.add(widget)
            logger.debug("%s subscribed to language changes", widget.__class__.__name__)

    def unsubscribe(self, widget: Any) -> None:
        self._subscribers.discard(widget)

    def notify_subscribers(self) -> None:
        subscribers = list(self._subscribers)
        logger.debug("Notifying %s translation subscribers", len(subscribers))
        for widget in subscribers:
            try:
                widget.retranslate_ui()
            except Exception as exc:
                logger.error("Failed to retranslate %s: %s", widget.__class__.__name__, exc)

    def _lookup(self, key: str) -> str:
        current = self._catalogs.get(self._language, {})
        if key in current:
            return current[key]

        info = self._metadata.get(self._language)
        fallback_code = info.fallback if info else DEFAULT_LANGUAGE
        if fallback_code and fallback_code != self._language:
            self._load_catalog(fallback_code)
            fallback = self._catalogs.get(fallback_code, {})
            if key in fallback:
                logger.debug("Missing translation %s in %s; using %s", key, self._language, fallback_code)
                return fallback[key]

        logger.warning("Missing translation key: %s", key)
        return key

    def _load_catalog(self, language_code: str) -> bool:
        if language_code in self._catalogs:
            return True

        path = self._compiled_dir() / f"{language_code}.json"
        if not path.exists():
            return False

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            messages = payload.get("messages", {})
            if not isinstance(messages, dict):
                logger.error("Invalid messages section in %s", path)
                return False

            self._catalogs[language_code] = {str(k): str(v) for k, v in messages.items()}
            meta = payload.get("meta", {})
            self._metadata[language_code] = LanguageInfo(
                code=str(meta.get("language", language_code)),
                name=str(meta.get("name", language_code)),
                fallback=meta.get("fallback", DEFAULT_LANGUAGE),
            )
            return True
        except Exception as exc:
            logger.error("Failed to load translation catalog %s: %s", path, exc)
            return False

    def _notify_language_changed(self, language_code: str) -> None:
        app = QCoreApplication.instance()
        if app:
            QApplication.sendEvent(app, QEvent(QEvent.LanguageChange))
        self.notify_subscribers()
        self.language_changed.emit(language_code)

    def _read_catalog_metadata(self, catalog_file: Path) -> Optional[LanguageInfo]:
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
            meta = payload.get("meta", {})
            code = str(meta.get("language", catalog_file.stem))
            name = str(meta.get("name", code))
            fallback = meta.get("fallback", DEFAULT_LANGUAGE)
            return LanguageInfo(code=code, name=name, fallback=fallback)
        except Exception as exc:
            logger.warning("Ignoring invalid translation catalog %s: %s", catalog_file, exc)
            return None

    def _compiled_dir(self) -> Path:
        return Path(get_resource_path("medimager/i18n/compiled"))

_translation_manager: Optional[TranslationManager] = None
_translation_manager_lock = threading.Lock()


def get_translation_manager() -> TranslationManager:
    global _translation_manager
    if _translation_manager is None:
        with _translation_manager_lock:
            if _translation_manager is None:
                _translation_manager = TranslationManager()
    return _translation_manager


def t(key: str, **params: Any) -> str:
    return get_translation_manager().t(key, **params)
