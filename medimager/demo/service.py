"""Asynchronous, validated cache management for generated example studies."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from concurrent.futures import CancelledError, Executor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QStandardPaths, Signal

from medimager.demo.catalog import DemoStudyId, DemoStudySpec, get_demo_study_spec
from medimager.demo.generator import (
    PRODUCTION_PROFILE,
    DemoGenerationCancelled,
    DemoGenerationProfile,
    generate_demo_study,
    validate_demo_study,
)
from medimager.demo.manifest import DemoStudyManifest
from medimager.utils.settings import get_performance_manager


_DISK_HEADROOM_BYTES = 16 * 1024 * 1024


class DemoStudyError(RuntimeError):
    """Error with a stable localization key and a non-PHI technical detail."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class DemoBuildResult:
    study_id: DemoStudyId
    root: Path
    manifest: DemoStudyManifest
    generated: bool
    disk_bytes: int


@dataclass(frozen=True)
class DemoCacheInfo:
    root: Path
    disk_bytes: int
    ready_studies: tuple[DemoStudyId, ...]
    running_studies: tuple[DemoStudyId, ...]


class DemoStudyService(QObject):
    """Generate example data off the GUI thread and reuse verified caches."""

    progress = Signal(str, int, int)
    ready = Signal(str, object)
    failed = Signal(str, str, str)
    cancelled = Signal(str)

    def __init__(
        self,
        cache_root: str | Path | None = None,
        *,
        executor: Optional[Executor] = None,
        profile: DemoGenerationProfile = PRODUCTION_PROFILE,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.cache_root = (
            Path(cache_root) if cache_root is not None else _default_cache_root()
        )
        self.profile = profile
        self.profile.validate()
        self._executor = executor or get_performance_manager().get_thread_pool()
        self._lock = threading.Lock()
        self._futures: dict[DemoStudyId, Future[DemoBuildResult]] = {}
        self._cancel_events: dict[DemoStudyId, threading.Event] = {}

    def ensure_ready(
        self,
        study_id: DemoStudyId | str,
        *,
        force: bool = False,
    ) -> Future[DemoBuildResult]:
        """Return a shared Future for a valid generated study directory."""

        normalized = DemoStudyId(study_id)
        spec = get_demo_study_spec(normalized)
        with self._lock:
            running = self._futures.get(normalized)
            if running is not None and not running.done():
                return running
            cancel_event = threading.Event()
            future = self._executor.submit(
                self._ensure_ready_worker,
                spec,
                force,
                cancel_event,
            )
            self._futures[normalized] = future
            self._cancel_events[normalized] = cancel_event
        future.add_done_callback(
            lambda done, current=normalized: self._handle_done(current, done)
        )
        return future

    def cancel(self, study_id: DemoStudyId | str) -> bool:
        """Request cooperative cancellation for an in-flight generation."""

        normalized = DemoStudyId(study_id)
        with self._lock:
            event = self._cancel_events.get(normalized)
            future = self._futures.get(normalized)
            if event is None or future is None or future.done():
                return False
            event.set()
        # Future.cancel() can synchronously run callbacks. Never call it while
        # holding _lock because _handle_done() acquires the same lock.
        future.cancel()
        return True

    def clear_cache(
        self,
        study_id: DemoStudyId | str | None = None,
    ) -> Future[int]:
        """Delete only the service-owned cache target and return freed bytes."""

        normalized = DemoStudyId(study_id) if study_id is not None else None
        with self._lock:
            running = {
                current
                for current, future in self._futures.items()
                if not future.done()
            }
        if normalized is None and running:
            raise DemoStudyError("demo.cache_busy")
        if normalized in running:
            raise DemoStudyError("demo.cache_busy", normalized.value)
        return self._executor.submit(self._clear_cache_worker, normalized)

    def cache_info(self) -> DemoCacheInfo:
        """Return a lightweight snapshot without decoding any DICOM files."""

        ready: list[DemoStudyId] = []
        total = 0
        for study_id in DemoStudyId:
            target = self._target_path(study_id)
            manifest_path = target / "manifest.json"
            if manifest_path.is_file():
                ready.append(study_id)
            total += _tree_size(target)
        with self._lock:
            running = tuple(
                study_id
                for study_id, future in self._futures.items()
                if not future.done()
            )
        return DemoCacheInfo(
            root=self.cache_root,
            disk_bytes=total,
            ready_studies=tuple(ready),
            running_studies=running,
        )

    def _ensure_ready_worker(
        self,
        spec: DemoStudySpec,
        force: bool,
        cancel_event: threading.Event,
    ) -> DemoBuildResult:
        try:
            self.cache_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DemoStudyError("demo.cache_unavailable", str(error)) from error
        target = self._target_path(spec.id)
        if not force:
            validation = validate_demo_study(target, spec)
            if validation.valid and validation.manifest is not None:
                return DemoBuildResult(
                    study_id=spec.id,
                    root=target,
                    manifest=validation.manifest,
                    generated=False,
                    disk_bytes=validation.manifest.disk_bytes,
                )

        self._preflight_disk(spec)
        staging = self.cache_root / f".staging-{spec.id.value}-{uuid.uuid4().hex}"
        self._assert_owned_child(staging)
        try:
            manifest = generate_demo_study(
                spec,
                staging,
                progress=lambda current, total: self.progress.emit(
                    spec.id.value, current, total
                ),
                cancelled=cancel_event.is_set,
                profile=self.profile,
            )
            if cancel_event.is_set():
                raise DemoGenerationCancelled(spec.id.value)
            validation = validate_demo_study(staging, spec)
            if not validation.valid or validation.manifest is None:
                raise DemoStudyError("demo.generated_data_invalid", validation.reason)

            self._promote_staging(staging, target)
            return DemoBuildResult(
                study_id=spec.id,
                root=target,
                manifest=manifest,
                generated=True,
                disk_bytes=manifest.disk_bytes,
            )
        except DemoGenerationCancelled:
            raise
        except DemoStudyError:
            raise
        except OSError as error:
            raise DemoStudyError("demo.generation_failed", str(error)) from error
        finally:
            if staging.exists():
                self._assert_owned_child(staging)
                shutil.rmtree(staging, ignore_errors=True)

    def _promote_staging(self, staging: Path, target: Path) -> None:
        """Atomically publish a validated staging tree and restore on failure."""

        self._assert_owned_child(staging)
        self._assert_owned_child(target)
        backup = self.cache_root / f".replaced-{target.name}-{uuid.uuid4().hex}"
        self._assert_owned_child(backup)
        had_target = target.exists()
        if had_target:
            target.replace(backup)
        try:
            staging.replace(target)
        except OSError:
            if had_target and backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    def _preflight_disk(self, spec: DemoStudySpec) -> None:
        try:
            free = shutil.disk_usage(self.cache_root).free
        except OSError as error:
            raise DemoStudyError("demo.disk_check_failed", str(error)) from error
        required = int(spec.estimated_bytes) + _DISK_HEADROOM_BYTES
        if free < required:
            raise DemoStudyError(
                "demo.insufficient_disk_space",
                f"required={required}; available={free}",
            )

    def _clear_cache_worker(self, study_id: Optional[DemoStudyId]) -> int:
        target = self.cache_root if study_id is None else self._target_path(study_id)
        if not target.exists():
            return 0
        if study_id is None:
            resolved = target.resolve()
            expected = self.cache_root.resolve()
            if resolved != expected:
                raise DemoStudyError("demo.unsafe_cache_path")
        else:
            self._assert_owned_child(target)
        size = _tree_size(target)
        shutil.rmtree(target)
        return size

    def _target_path(self, study_id: DemoStudyId) -> Path:
        target = self.cache_root / study_id.value
        self._assert_owned_child(target)
        return target

    def _assert_owned_child(self, target: Path) -> None:
        root = self.cache_root.resolve()
        resolved = target.resolve()
        if resolved == root or root not in resolved.parents:
            raise DemoStudyError("demo.unsafe_cache_path", str(resolved))

    def _handle_done(
        self,
        study_id: DemoStudyId,
        future: Future[DemoBuildResult],
    ) -> None:
        try:
            result = future.result()
        except (CancelledError, DemoGenerationCancelled):
            self.cancelled.emit(study_id.value)
        except DemoStudyError as error:
            self.failed.emit(study_id.value, error.code, error.detail)
        except Exception as error:  # defensive boundary for GUI callbacks
            self.failed.emit(study_id.value, "demo.generation_failed", str(error))
        else:
            _write_packaged_smoke_result(study_id, result)
            self.ready.emit(study_id.value, result)
        finally:
            with self._lock:
                if self._futures.get(study_id) is future:
                    self._futures.pop(study_id, None)
                    self._cancel_events.pop(study_id, None)


def _default_cache_root() -> Path:
    smoke_root = os.environ.get("MEDIMAGER_SMOKE_APP_DATA_ROOT", "").strip()
    if smoke_root:
        # Release automation must exercise the packaged generator without
        # writing into (or reusing) the operator's real application data.
        return Path(smoke_root).expanduser().resolve(strict=False) / "demo_studies" / "v1"
    base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not base:
        raise DemoStudyError("demo.cache_unavailable")
    return Path(base) / "demo_studies" / "v1"


def _write_packaged_smoke_result(
    study_id: DemoStudyId,
    result: DemoBuildResult,
) -> None:
    """Publish a non-PHI completion handshake for packaged release probes.

    Both environment variables are required, so normal application runs never
    create this automation-only artifact.  The request token is hashed before
    it becomes a filename and the payload contains only generator state.
    """

    root_value = os.environ.get("MEDIMAGER_SMOKE_APP_DATA_ROOT", "").strip()
    token = os.environ.get("MEDIMAGER_SMOKE_REQUEST_TOKEN", "").strip()
    if not root_value or not token:
        return
    temporary: Path | None = None
    try:
        root = Path(root_value).expanduser().resolve(strict=False)
        result_root = result.root.resolve(strict=False)
        if root != result_root and root not in result_root.parents:
            return
        marker_dir = root / "smoke_results"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_name = hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()[:24]
        destination = marker_dir / f"{marker_name}.json"
        temporary = marker_dir / f".{marker_name}.{uuid.uuid4().hex}.tmp"
        payload = {
            "schema_version": 1,
            "request_token": token,
            "study_id": study_id.value,
            "generated": bool(result.generated),
            "manifest_digest": result.manifest.semantic_digest,
        }
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except (OSError, TypeError, ValueError):
        # A release-test handshake must never turn a valid demo into a user
        # visible failure.  The external probe will time out and report it.
        return
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
