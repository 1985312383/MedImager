"""Bounded, expiring on-disk thumbnail cache for local study navigation."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ThumbnailCachePolicy:
    max_items: int = 256
    max_age_days: int = 30

    @property
    def max_age_seconds(self) -> float:
        return float(self.max_age_days * 86_400)


@dataclass(frozen=True)
class ThumbnailPruneResult:
    removed_items: int = 0
    freed_bytes: int = 0
    errors: tuple[str, ...] = ()


class ThumbnailDiskCache:
    """Store PNG thumbnails with settings-backed LRU and age limits.

    Modification time is the cache access timestamp. Reads touch a valid entry,
    writes use a same-directory temporary file and atomic replacement, and all
    directory enumeration is limited to regular PNG files directly under the
    application-owned thumbnail directory.
    """

    MAX_ITEMS_KEY = "cache.thumbnail.max_items"
    MAX_AGE_DAYS_KEY = "cache.thumbnail.max_age_days"

    def __init__(
        self,
        settings_manager,
        *,
        now_provider: Callable[[], float] = time.time,
    ) -> None:
        self.settings_manager = settings_manager
        self._now_provider = now_provider

    @property
    def directory(self) -> Path:
        return self.settings_manager.get_config_directory() / "thumbnail_cache"

    @property
    def policy(self) -> ThumbnailCachePolicy:
        return ThumbnailCachePolicy(
            max_items=self._positive_setting(self.MAX_ITEMS_KEY, 256),
            max_age_days=self._positive_setting(self.MAX_AGE_DAYS_KEY, 30),
        )

    def path_for_identity(self, identity: str) -> Path:
        digest = hashlib.sha256(str(identity).encode("utf-8", "replace")).hexdigest()
        return self.directory / f"{digest}.png"

    def lookup(self, identity: str) -> Path | None:
        """Return and touch a valid cached PNG, or remove an expired entry."""

        now = float(self._now_provider())
        self.prune(now=now)
        path = self.path_for_identity(identity)
        if not self._is_safe_file(path):
            return None
        try:
            if path.stat().st_mtime < now - self.policy.max_age_seconds:
                path.unlink(missing_ok=True)
                return None
            # The path was already rejected if it is a symlink. Windows does
            # not implement os.utime(..., follow_symlinks=False).
            os.utime(path, (now, now))
        except OSError:
            return None
        return path

    def write_png(
        self,
        identity: str,
        writer: Callable[[Path], bool],
    ) -> Path | None:
        """Atomically write one PNG and enforce the current settings policy."""

        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise OSError("Thumbnail cache directory must not be a symbolic link")
        target = self.path_for_identity(identity)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.stem}.",
            suffix=".tmp",
            dir=directory,
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            if writer(temporary_path) is False or not self._is_png(temporary_path):
                return None
            os.replace(temporary_path, target)
            now = float(self._now_provider())
            os.utime(target, (now, now))
            self.prune(now=now, protected=(target,))
            return target if target.is_file() else None
        finally:
            temporary_path.unlink(missing_ok=True)

    def discard(self, identity: str) -> bool:
        path = self.path_for_identity(identity)
        if not self._is_safe_file(path):
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def prune(
        self,
        *,
        now: float | None = None,
        protected: Iterable[Path] = (),
    ) -> ThumbnailPruneResult:
        """Remove expired entries, then least-recently-used overflow entries."""

        current_time = float(self._now_provider()) if now is None else float(now)
        policy = self.policy
        cutoff = current_time - policy.max_age_seconds
        protected_paths = {
            path.resolve(strict=False)
            for path in protected
            if path.parent == self.directory
        }
        records: list[tuple[Path, int, float]] = []
        for path in self._safe_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            records.append((path, int(stat.st_size), float(stat.st_mtime)))
        expired = [record for record in records if record[2] < cutoff]
        fresh = sorted(
            (record for record in records if record[2] >= cutoff),
            key=lambda record: (
                record[0].resolve(strict=False) in protected_paths,
                record[2],
                record[0].name,
            ),
            reverse=True,
        )
        removable = expired + fresh[policy.max_items :]
        removed = 0
        freed = 0
        errors: list[str] = []
        for path, size, _modified in removable:
            try:
                path.unlink(missing_ok=True)
                removed += 1
                freed += size
            except OSError as error:
                errors.append(f"{path.name}: {error.__class__.__name__}")
        return ThumbnailPruneResult(removed, freed, tuple(errors))

    def _safe_files(self) -> tuple[Path, ...]:
        directory = self.directory
        try:
            root = directory.resolve(strict=False)
            if not directory.is_dir() or directory.is_symlink():
                return ()
            files: list[Path] = []
            for candidate in directory.iterdir():
                if (
                    candidate.suffix.casefold() != ".png"
                    or candidate.is_symlink()
                    or not candidate.is_file()
                ):
                    continue
                if candidate.resolve(strict=False).parent == root:
                    files.append(candidate)
            return tuple(files)
        except OSError:
            return ()

    def _is_safe_file(self, path: Path) -> bool:
        try:
            return (
                path.suffix.casefold() == ".png"
                and path.is_file()
                and not path.is_symlink()
                and path.resolve(strict=False).parent
                == self.directory.resolve(strict=False)
            )
        except OSError:
            return False

    @staticmethod
    def _is_png(path: Path) -> bool:
        try:
            with path.open("rb") as stream:
                return stream.read(len(_PNG_SIGNATURE)) == _PNG_SIGNATURE
        except OSError:
            return False

    def _positive_setting(self, key: str, default: int) -> int:
        try:
            return max(1, int(self.settings_manager.get_setting(key, default)))
        except (TypeError, ValueError):
            return default
