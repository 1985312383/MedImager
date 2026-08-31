"""Bounded inspection and cleanup for MedImager-owned local state."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, QStandardPaths, Signal

from medimager.core.thumbnail_cache import ThumbnailDiskCache


class StorageCategory(str, Enum):
    DISPLAY_MEMORY = "display_memory"
    THUMBNAILS = "thumbnails"
    DEMO_STUDIES = "demo_studies"
    WORKSPACE_HISTORY = "workspace_history"
    RECOVERY_DRAFTS = "recovery_drafts"


@dataclass(frozen=True)
class StorageUsage:
    category: StorageCategory
    item_count: int
    bytes: int
    clearable: bool = True
    destructive: bool = False


@dataclass(frozen=True)
class ClearResult:
    category: StorageCategory
    removed_items: int = 0
    freed_bytes: int = 0
    skipped_active: int = 0
    errors: tuple[str, ...] = ()


class StorageCleanupService(QObject):
    """Clear only explicitly owned cache/state locations.

    Tree cleanup is restricted to the generated-demo whitelist and never
    follows symlinks or reparse points. Annotation sidecars beside source
    images are never touched.
    """

    usage_changed = Signal(object)
    cleared = Signal(object)

    def __init__(
        self,
        settings_manager,
        parent: Optional[QObject] = None,
        protected_drafts_provider: Optional[Callable[[], Iterable[Path]]] = None,
        demo_cache_root: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.performance_manager = settings_manager.get_performance_manager()
        self._protected_drafts_provider = protected_drafts_provider
        self._demo_cache_root = (
            Path(demo_cache_root) if demo_cache_root is not None else None
        )

    @property
    def thumbnail_directory(self) -> Path:
        return self.settings_manager.get_config_directory() / "thumbnail_cache"

    @property
    def recovery_directory(self) -> Path:
        return self.settings_manager.get_config_directory() / "annotation_drafts"

    @property
    def demo_directory(self) -> Path:
        if self._demo_cache_root is not None:
            return self._demo_cache_root
        base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        if not base:
            return self.settings_manager.get_config_directory() / "demo_studies" / "v1"
        return Path(base) / "demo_studies" / "v1"

    def set_protected_drafts_provider(
        self, provider: Optional[Callable[[], Iterable[Path]]]
    ) -> None:
        self._protected_drafts_provider = provider

    def inspect(
        self, categories: Optional[Iterable[StorageCategory]] = None
    ) -> tuple[StorageUsage, ...]:
        selected = tuple(categories or StorageCategory)
        usage = tuple(self._inspect_one(category) for category in selected)
        self.usage_changed.emit(usage)
        return usage

    def clear(
        self, category: StorageCategory, *, include_active: bool = False
    ) -> ClearResult:
        category = StorageCategory(category)
        if category is StorageCategory.DISPLAY_MEMORY:
            before = self.performance_manager.get_cache_info()
            self.performance_manager.clear_cache()
            result = ClearResult(
                category,
                removed_items=int(before.get("item_count", 0)),
                freed_bytes=int(before.get("usage_bytes", 0)),
            )
        elif category is StorageCategory.THUMBNAILS:
            result = self._clear_files(category, self.thumbnail_directory, ".png")
        elif category is StorageCategory.DEMO_STUDIES:
            result = self._clear_demo_tree()
        elif category is StorageCategory.WORKSPACE_HISTORY:
            usage = self._inspect_one(category)
            self.settings_manager.remove_setting("study_workspace.document")
            self.settings_manager.remove_setting("study_workspace.states")
            self.settings_manager.save_settings()
            result = ClearResult(
                category,
                removed_items=usage.item_count,
                freed_bytes=usage.bytes,
            )
        else:
            protected = set() if include_active else self._protected_drafts()
            result = self._clear_files(
                category,
                self.recovery_directory,
                ".json",
                protected=protected,
            )
        self.cleared.emit(result)
        self.inspect((category,))
        return result

    def clear_temporary_caches(self) -> tuple[ClearResult, ...]:
        """Clear rebuildable data only; recovery and workspace state are excluded."""

        return (
            self.clear(StorageCategory.DISPLAY_MEMORY),
            self.clear(StorageCategory.THUMBNAILS),
            self.clear(StorageCategory.DEMO_STUDIES),
        )

    def prune_thumbnails(self) -> ClearResult:
        pruned = ThumbnailDiskCache(self.settings_manager).prune()
        result = ClearResult(
            StorageCategory.THUMBNAILS,
            pruned.removed_items,
            pruned.freed_bytes,
            errors=pruned.errors,
        )
        self.cleared.emit(result)
        self.inspect((StorageCategory.THUMBNAILS,))
        return result

    def _inspect_one(self, category: StorageCategory) -> StorageUsage:
        if category is StorageCategory.DISPLAY_MEMORY:
            info = self.performance_manager.get_cache_info()
            return StorageUsage(
                category,
                int(info.get("item_count", 0)),
                int(info.get("usage_bytes", 0)),
            )
        if category is StorageCategory.THUMBNAILS:
            files = self._safe_files(self.thumbnail_directory, ".png")
            return StorageUsage(
                category,
                len(files),
                sum(self._safe_stat(path)[0] for path in files),
            )
        if category is StorageCategory.DEMO_STUDIES:
            files, _directories, errors = self._scan_demo_tree()
            return StorageUsage(
                category,
                len(files),
                sum(size for _path, size, _is_directory_link in files),
                clearable=not errors,
            )
        if category is StorageCategory.RECOVERY_DRAFTS:
            files = self._safe_files(self.recovery_directory, ".json")
            return StorageUsage(
                category,
                len(files),
                sum(self._safe_stat(path)[0] for path in files),
                destructive=True,
            )

        document = self.settings_manager.get_setting("study_workspace.document", {})
        legacy = self.settings_manager.get_setting("study_workspace.states", {})
        states = document.get("states", {}) if isinstance(document, dict) else {}
        if not isinstance(states, dict) or not states:
            states = legacy if isinstance(legacy, dict) else {}
        try:
            byte_count = len(
                json.dumps(states, ensure_ascii=False, default=str).encode("utf-8")
            )
        except (TypeError, ValueError):
            byte_count = 0
        return StorageUsage(
            category,
            len(states),
            byte_count,
            destructive=True,
        )

    def _protected_drafts(self) -> set[Path]:
        if self._protected_drafts_provider is None:
            return set()
        try:
            return {
                Path(path).resolve(strict=False)
                for path in self._protected_drafts_provider()
            }
        except Exception:
            return set()

    def _clear_demo_tree(self) -> ClearResult:
        files, directories, scan_errors = self._scan_demo_tree()
        removed = 0
        freed = 0
        errors = list(scan_errors)
        for path, size, is_directory_link in files:
            try:
                if is_directory_link:
                    path.rmdir()
                else:
                    path.unlink(missing_ok=True)
                removed += 1
                freed += size
            except OSError as error:
                errors.append(f"{path.name}: {error.__class__.__name__}")
        for directory in sorted(
            directories,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError as error:
                errors.append(f"{directory.name}: {error.__class__.__name__}")
        root = self.demo_directory
        if root.is_dir() and not root.is_symlink():
            try:
                root.rmdir()
            except OSError as error:
                errors.append(f"{root.name}: {error.__class__.__name__}")
        return ClearResult(
            StorageCategory.DEMO_STUDIES,
            removed,
            freed,
            errors=tuple(errors),
        )

    def _scan_demo_tree(
        self,
    ) -> tuple[
        list[tuple[Path, int, bool]],
        list[Path],
        tuple[str, ...],
    ]:
        """Inspect only the owned demo root without following reparse points."""

        root = self.demo_directory
        try:
            if not root.exists():
                return [], [], ()
            if root.is_symlink() or not root.is_dir():
                return [], [], ("demo_studies: UnsafeRoot",)
            resolved_root = root.resolve(strict=True)
        except OSError as error:
            return [], [], (f"demo_studies: {error.__class__.__name__}",)

        files: list[tuple[Path, int, bool]] = []
        directories: list[Path] = []
        errors: list[str] = []
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as iterator:
                    entries = tuple(iterator)
            except OSError as error:
                errors.append(f"{directory.name}: {error.__class__.__name__}")
                continue
            for entry in entries:
                path = Path(entry.path)
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    attributes = int(getattr(metadata, "st_file_attributes", 0))
                    is_reparse = entry.is_symlink() or bool(
                        attributes
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                    )
                    is_directory_link = is_reparse and bool(
                        attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
                    )
                    if is_reparse:
                        files.append((path, int(metadata.st_size), is_directory_link))
                        continue
                    if entry.is_file(follow_symlinks=False):
                        files.append((path, int(metadata.st_size), False))
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    resolved = path.resolve(strict=True)
                    if (
                        resolved == resolved_root
                        or resolved_root not in resolved.parents
                    ):
                        errors.append(f"{path.name}: UnsafePath")
                        continue
                    directories.append(path)
                    pending.append(path)
                except OSError as error:
                    errors.append(f"{path.name}: {error.__class__.__name__}")
        return files, directories, tuple(errors)

    def _clear_files(
        self,
        category: StorageCategory,
        directory: Path,
        suffix: str,
        *,
        protected: Optional[set[Path]] = None,
    ) -> ClearResult:
        protected = protected or set()
        files = self._safe_files(directory, suffix)
        removable = {
            path for path in files if path.resolve(strict=False) not in protected
        }
        result = self._remove_paths(category, removable)
        skipped = len(files) - len(removable)
        if skipped:
            result = ClearResult(
                category,
                result.removed_items,
                result.freed_bytes,
                skipped,
                result.errors,
            )
        return result

    def _remove_paths(
        self, category: StorageCategory, paths: Iterable[Path]
    ) -> ClearResult:
        removed = 0
        freed = 0
        errors: list[str] = []
        for path in paths:
            size, _mtime = self._safe_stat(path)
            try:
                path.unlink(missing_ok=True)
                removed += 1
                freed += size
            except OSError as error:
                errors.append(f"{path.name}: {error.__class__.__name__}")
        return ClearResult(category, removed, freed, errors=tuple(errors))

    @staticmethod
    def _safe_stat(path: Path) -> tuple[int, float]:
        try:
            stat = path.stat()
            return int(stat.st_size), float(stat.st_mtime)
        except OSError:
            return 0, 0.0

    @staticmethod
    def _safe_files(directory: Path, suffix: str) -> tuple[Path, ...]:
        try:
            root = directory.resolve(strict=False)
            if not directory.is_dir() or directory.is_symlink():
                return ()
            safe: list[Path] = []
            for candidate in directory.iterdir():
                if (
                    candidate.suffix.casefold() != suffix.casefold()
                    or not candidate.is_file()
                    or candidate.is_symlink()
                ):
                    continue
                try:
                    if candidate.resolve(strict=False).parent == root:
                        safe.append(candidate)
                except OSError:
                    continue
            return tuple(safe)
        except OSError:
            return ()
