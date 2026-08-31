#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置管理模块
处理用户偏好设置的保存与加载
"""

import base64
import json
import gc
import os
import sys
import tempfile
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QByteArray, QSettings, QStandardPaths, QObject, Signal
from medimager.core.settings_registry import (
    DEFAULT_SETTINGS_REGISTRY,
    SettingSpec,
    SettingsRegistry,
)
from medimager.utils.logger import get_logger


_SETTINGS_EXPORT_FORMAT = "medimager-settings"
_SETTINGS_SCHEMA_VERSION = 2
_MAX_IMPORT_BYTES = 5 * 1024 * 1024
_MAX_IMPORT_KEYS = 2048
_MISSING = object()
_STATE_KEYS = {
    "recent_files",
    "window_geometry",
    "window_state",
    "study_workspace.document",
    "study_workspace.states",
}


def _encode_json_value(value: Any) -> Any:
    """Encode QSettings-native values without stringifying their type."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (QByteArray, bytes, bytearray, memoryview)):
        return {
            "__medimager_type__": "bytes",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, Path):
        return {"__medimager_type__": "path", "value": str(value)}
    if isinstance(value, Mapping):
        return {str(key): _encode_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_json_value(item) for item in value]
    raise TypeError(f"Unsupported settings value type: {type(value).__name__}")


def _decode_json_value(value: Any, depth: int = 0) -> Any:
    if depth > 32:
        raise ValueError("Settings document nesting is too deep")
    if isinstance(value, list):
        return [_decode_json_value(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        raise ValueError("Unsupported settings JSON value")
    marker = value.get("__medimager_type__")
    if marker is not None:
        if set(value) == {"__medimager_type__", "base64"} and marker == "bytes":
            try:
                return QByteArray(base64.b64decode(value["base64"], validate=True))
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid encoded byte array") from error
        if set(value) == {"__medimager_type__", "value"} and marker == "path":
            return str(value["value"])
        raise ValueError("Unknown encoded settings value")
    return {
        str(key): _decode_json_value(item, depth + 1)
        for key, item in value.items()
    }


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate settings key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str):
    raise ValueError(f"Non-finite JSON number is not allowed: {value}")


class PerformanceManager:
    """性能管理器
    
    负责管理应用程序的性能相关设置
    """
    
    def __init__(self):
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._cache_size_mb: int = 256
        self._thread_count: int = 4
        self._cache_data: "OrderedDict[str, Any]" = OrderedDict()
        self._cache_sizes: Dict[str, int] = {}
        self._cache_usage_bytes: int = 0
        self._cache_lock = threading.Lock()
        self.logger = get_logger(__name__)
        
    def set_thread_count(self, count: int) -> None:
        """设置线程数量
        
        Args:
            count: 线程数量
        """
        if count < 1:
            count = 1
        elif count > 16:
            count = 16
            
        self._thread_count = count
        
        # 重新创建线程池
        if self._thread_pool is not None:
            # 设置对话框运行在 GUI 线程，不能等待正在解码的大序列。
            self._thread_pool.shutdown(wait=False, cancel_futures=True)
            
        self._thread_pool = ThreadPoolExecutor(max_workers=self._thread_count)
        self.logger.debug(f"线程数量已设置为: {self._thread_count}")
        
    def get_thread_count(self) -> int:
        """获取当前线程数量
        
        Returns:
            int: 线程数量
        """
        return self._thread_count
        
    def get_thread_pool(self) -> ThreadPoolExecutor:
        """获取线程池
        
        Returns:
            ThreadPoolExecutor: 线程池实例
        """
        if self._thread_pool is None:
            self._thread_pool = ThreadPoolExecutor(max_workers=self._thread_count)
        return self._thread_pool
        
    def set_cache_size(self, size_mb: int) -> None:
        """设置缓存大小
        
        Args:
            size_mb: 缓存大小（MB）
        """
        if size_mb < 64:
            size_mb = 64
        elif size_mb > 2048:
            size_mb = 2048
            
        old_size = self._cache_size_mb
        self._cache_size_mb = size_mb
        
        # 如果缓存大小减少，清理超出的缓存
        if size_mb < old_size:
            self._cleanup_cache()
            
        self.logger.debug(f"缓存大小已设置为: {self._cache_size_mb}MB")
        
    def get_cache_size(self) -> int:
        """获取当前缓存大小
        
        Returns:
            int: 缓存大小（MB）
        """
        return self._cache_size_mb
        
    def add_to_cache(self, key: str, data: Any) -> None:
        """添加数据到缓存
        
        Args:
            key: 缓存键
            data: 缓存数据
        """
        item_size = self._estimate_size_bytes(data)
        max_bytes = self._cache_limit_bytes

        with self._cache_lock:
            if key in self._cache_data:
                self._cache_usage_bytes -= self._cache_sizes.pop(key, 0)
                del self._cache_data[key]

            # An item larger than the configured budget can never be retained.
            if item_size > max_bytes:
                return

            self._cache_data[key] = data
            self._cache_sizes[key] = item_size
            self._cache_usage_bytes += item_size
            self._cache_data.move_to_end(key)
            self._evict_to_limit_locked(max_bytes)
                
    def get_from_cache(self, key: str) -> Optional[Any]:
        """从缓存获取数据
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存数据，不存在返回None
        """
        with self._cache_lock:
            data = self._cache_data.get(key)
            if data is not None:
                # A cache hit makes this the most recently used item.
                self._cache_data.move_to_end(key)
            return data
            
    def clear_cache(self) -> None:
        """清空缓存"""
        with self._cache_lock:
            self._cache_data.clear()
            self._cache_sizes.clear()
            self._cache_usage_bytes = 0
        gc.collect()  # 强制垃圾回收
            
    def _cleanup_cache(self) -> None:
        """清理超出大小限制的缓存"""
        with self._cache_lock:
            self._evict_to_limit_locked(self._cache_limit_bytes)
        gc.collect()

    @property
    def _cache_limit_bytes(self) -> int:
        return int(self._cache_size_mb * 1024 * 1024)

    def _evict_to_limit_locked(self, max_bytes: int) -> None:
        """Evict least-recently-used entries while holding the cache lock."""
        while self._cache_data and self._cache_usage_bytes > max_bytes:
            oldest_key, _ = self._cache_data.popitem(last=False)
            self._cache_usage_bytes -= self._cache_sizes.pop(oldest_key, 0)

    @classmethod
    def _estimate_size_bytes(cls, data: Any, seen: Optional[set[int]] = None) -> int:
        """Return a conservative byte count for cache accounting.

        Display cache entries are normally NumPy arrays, for which nbytes is
        exact. Container handling keeps this utility safe for the other small
        objects accepted by the public cache API.
        """
        if seen is None:
            seen = set()

        object_id = id(data)
        if object_id in seen:
            return 0
        seen.add(object_id)

        try:
            import numpy as np
            if isinstance(data, np.ndarray):
                return int(data.nbytes)
        except ImportError:
            pass

        if isinstance(data, (bytes, bytearray, memoryview)):
            return len(data)
        if isinstance(data, str):
            return len(data.encode("utf-8"))

        size = sys.getsizeof(data)
        if isinstance(data, dict):
            size += sum(
                cls._estimate_size_bytes(key, seen) + cls._estimate_size_bytes(value, seen)
                for key, value in data.items()
            )
        elif isinstance(data, (list, tuple, set, frozenset)):
            size += sum(cls._estimate_size_bytes(value, seen) for value in data)
        return int(size)
            
    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息
        
        Returns:
            Dict[str, Any]: 缓存信息
        """
        with self._cache_lock:
            return {
                'size_mb': self._cache_size_mb,
                'item_count': len(self._cache_data),
                # Keep the legacy key for UI compatibility, but report the
                # actual accounted memory rather than an item-count estimate.
                'estimated_usage_mb': self._cache_usage_bytes / (1024 * 1024),
                'usage_bytes': self._cache_usage_bytes,
                'limit_bytes': self._cache_limit_bytes,
            }
            
    def shutdown(self) -> None:
        """关闭性能管理器"""
        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=False, cancel_futures=True)
            self._thread_pool = None
        self.clear_cache()


class SettingsManager(QObject):
    """设置管理器
    
    负责应用程序设置的保存、加载和管理
    支持多种存储格式和位置
    """
    
    # 性能设置变化信号
    performance_settings_changed = Signal(str, object)  # 设置类型, 新值
    setting_changed = Signal(str, object)
    settings_imported = Signal(object)
    
    def __init__(self, 
                 app_name: str = "MedImager",
                 org_name: str = "MedImager Project",
                 use_json: bool = False,
                 parent: Optional[QObject] = None,
                 registry: Optional[SettingsRegistry] = None,
                 config_dir: Optional[Union[str, Path]] = None) -> None:
        """初始化设置管理器
        
        Args:
            app_name: 应用程序名称
            org_name: 组织名称
            use_json: 是否使用JSON格式存储（否则使用Qt的原生格式）
            parent: 父对象
        """
        super().__init__(parent)
        self.app_name = app_name
        self.org_name = org_name
        self.use_json = use_json
        self.registry = registry or DEFAULT_SETTINGS_REGISTRY
        
        # 初始化性能管理器
        self.performance_manager = PerformanceManager()
        
        if use_json:
            # 使用JSON文件存储
            self.config_dir = (
                Path(config_dir).expanduser().resolve(strict=False)
                if config_dir is not None
                else Path(
                    QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
                )
            )
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.config_file = self.config_dir / f"{app_name.lower()}_settings.json"
            self._settings_data: Dict[str, Any] = {}
            self._load_json_settings()
        else:
            # 使用Qt的QSettings
            self.qt_settings = QSettings(org_name, app_name)

        self._ensure_schema_version()
            
        # 初始化性能设置
        self._initialize_performance_settings()
        
    def _initialize_performance_settings(self) -> None:
        """初始化性能设置"""
        # 从设置中加载性能配置
        thread_count = self.get_setting('thread_count', 4)
        cache_size = self.get_setting('cache_size', 256)
        
        # 应用设置
        self.performance_manager.set_thread_count(thread_count)
        self.performance_manager.set_cache_size(cache_size)
            
    def _load_json_settings(self) -> None:
        """Load JSON settings, accepting both legacy and encoded values."""
        try:
            if not self.config_file.exists():
                self._settings_data = {}
                return
            with self.config_file.open("r", encoding="utf-8") as handle:
                loaded = json.load(
                    handle,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            decoded = _decode_json_value(loaded)
            self._settings_data = decoded if isinstance(decoded, dict) else {}
        except Exception as error:
            get_logger(__name__).warning(
                "Settings file could not be loaded: %s", error.__class__.__name__
            )
            self._settings_data = {}

    def _save_json_settings(self) -> bool:
        """Atomically save the JSON test/portable backend."""
        temporary_path: Optional[Path] = None
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                _encode_json_value(self._settings_data),
                indent=2,
                ensure_ascii=False,
            ) + "\n"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.config_file.name}.",
                suffix=".tmp",
                dir=self.config_dir,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.config_file)
            return True
        except Exception as error:
            get_logger(__name__).warning(
                "Settings file could not be saved: %s", error.__class__.__name__
            )
            return False
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def _raw_value(self, key: str, default: Any = _MISSING) -> Any:
        if self.use_json:
            return self._settings_data.get(key, default)
        if not self.qt_settings.contains(key):
            return default
        return self.qt_settings.value(key)

    def _ensure_schema_version(self) -> None:
        raw = self._raw_value("settings.schema_version", _MISSING)
        try:
            version = int(raw) if raw is not _MISSING else 0
        except (TypeError, ValueError):
            version = 0
        if version >= _SETTINGS_SCHEMA_VERSION:
            return
        if self.use_json:
            self._settings_data["settings.schema_version"] = _SETTINGS_SCHEMA_VERSION
            self._save_json_settings()
        else:
            self.qt_settings.setValue("settings.schema_version", _SETTINGS_SCHEMA_VERSION)
            self.qt_settings.sync()

    def get_setting(self, key: str, default_value: Any = None) -> Any:
        raw = self._raw_value(key, _MISSING)
        spec = self.registry.spec(key)
        if raw is _MISSING:
            if default_value is not None:
                return self.registry.coerce(key, default_value)
            return spec.coerce(spec.default) if spec is not None else None
        if spec is None:
            return raw
        fallback = spec.default if default_value is None else default_value
        return spec.coerce(raw, fallback)

    def get_typed(self, setting: str | SettingSpec[Any]) -> Any:
        spec = setting if isinstance(setting, SettingSpec) else self.registry.require(setting)
        return self.get_setting(spec.key, spec.default)

    def set_setting(self, key: str, value: Any) -> None:
        self.set_many({key: value})

    def set_typed(self, setting: str | SettingSpec[Any], value: Any) -> Any:
        spec = setting if isinstance(setting, SettingSpec) else self.registry.require(setting)
        normalized = spec.coerce(value)
        self.set_many({spec.key: normalized})
        return normalized

    def set_many(self, values: Mapping[str, Any]) -> None:
        normalized = {
            str(key): self.registry.coerce(str(key), value)
            for key, value in values.items()
        }
        previous = {
            key: self._raw_value(key, _MISSING)
            for key in normalized
        }
        if self.use_json:
            self._settings_data.update(normalized)
            if not self._save_json_settings():
                for key, old_value in previous.items():
                    if old_value is _MISSING:
                        self._settings_data.pop(key, None)
                    else:
                        self._settings_data[key] = old_value
                raise OSError("Settings could not be saved")
        else:
            for key, value in normalized.items():
                self.qt_settings.setValue(key, value)
            self.qt_settings.sync()
            if self.qt_settings.status() != QSettings.Status.NoError:
                for key, old_value in previous.items():
                    if old_value is _MISSING:
                        self.qt_settings.remove(key)
                    else:
                        self.qt_settings.setValue(key, old_value)
                self.qt_settings.sync()
                raise OSError("Settings could not be saved")
        for key, value in normalized.items():
            self._apply_setting_change(key, value)

    def _apply_setting_change(self, key: str, value: Any) -> None:
        if key == "thread_count":
            self.performance_manager.set_thread_count(int(value))
            self.performance_settings_changed.emit(key, value)
        elif key == "cache_size":
            self.performance_manager.set_cache_size(int(value))
            self.performance_settings_changed.emit(key, value)
        self.setting_changed.emit(key, value)

    def has_setting(self, key: str) -> bool:
        return self._raw_value(key, _MISSING) is not _MISSING

    def remove_setting(self, key: str) -> None:
        if self.use_json:
            if key in self._settings_data:
                del self._settings_data[key]
                self._save_json_settings()
        else:
            self.qt_settings.remove(key)
            self.qt_settings.sync()

    def get_all_settings(self) -> Dict[str, Any]:
        if self.use_json:
            return self._settings_data.copy()
        return {
            key: self.qt_settings.value(key)
            for key in self.qt_settings.allKeys()
        }

    def clear_all_settings(self) -> None:
        if self.use_json:
            self._settings_data.clear()
            self._save_json_settings()
        else:
            self.qt_settings.clear()
            self.qt_settings.sync()

    def save_settings(self) -> None:
        if self.use_json:
            self._save_json_settings()
        else:
            self.qt_settings.sync()

    def export_settings(
        self,
        file_path: Union[str, Path],
        *,
        include_state: bool = False,
    ) -> bool:
        """Atomically export a versioned, JSON-safe settings document."""
        temporary_path: Optional[Path] = None
        try:
            exported = {}
            for key, value in self.get_all_settings().items():
                spec = self.registry.spec(key)
                if key == "settings.schema_version":
                    continue
                if not include_state and key in _STATE_KEYS:
                    continue
                if spec is not None and not spec.exportable and not (
                    include_state and key in _STATE_KEYS
                ):
                    continue
                exported[key] = _encode_json_value(value)
            document = {
                "format": _SETTINGS_EXPORT_FORMAT,
                "schema_version": _SETTINGS_SCHEMA_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "settings": exported,
            }
            destination = Path(file_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            return True
        except Exception as error:
            get_logger(__name__).warning(
                "Settings export failed: %s", error.__class__.__name__
            )
            return False
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def import_settings(
        self,
        file_path: Union[str, Path],
        *,
        allow_unknown: bool = True,
        include_state: bool = False,
    ) -> bool:
        """Validate the complete document before applying any imported value."""
        try:
            source = Path(file_path)
            if source.stat().st_size > _MAX_IMPORT_BYTES:
                raise ValueError("Settings document is too large")
            with source.open("r", encoding="utf-8") as handle:
                document = json.load(
                    handle,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            if not isinstance(document, dict):
                raise ValueError("Settings document must be an object")
            if document.get("format") == _SETTINGS_EXPORT_FORMAT:
                version = int(document.get("schema_version", 0))
                if version < 1 or version > _SETTINGS_SCHEMA_VERSION:
                    raise ValueError("Unsupported settings schema")
                imported = document.get("settings")
            else:
                # Legacy exports were a plain key/value mapping.
                legacy_version = document.get("settings.schema_version")
                if legacy_version is not None and int(legacy_version) > _SETTINGS_SCHEMA_VERSION:
                    raise ValueError("Unsupported settings schema")
                imported = document
            if not isinstance(imported, dict) or len(imported) > _MAX_IMPORT_KEYS:
                raise ValueError("Invalid settings mapping")
            normalized: dict[str, Any] = {}
            for raw_key, encoded in imported.items():
                key = str(raw_key)
                if (
                    not key
                    or len(key) > 256
                    or any(ord(character) < 32 for character in key)
                ):
                    raise ValueError("Invalid settings key")
                if key == "settings.schema_version":
                    continue
                if not include_state and key in _STATE_KEYS:
                    continue
                spec = self.registry.spec(key)
                if spec is None and not allow_unknown:
                    continue
                if spec is not None and not spec.exportable and not (
                    include_state and key in _STATE_KEYS
                ):
                    continue
                decoded = _decode_json_value(encoded)
                normalized[key] = (
                    spec.coerce(decoded) if spec is not None else decoded
                )
            self.set_many(normalized)
            self.settings_imported.emit(tuple(normalized))
            return True
        except Exception as error:
            get_logger(__name__).warning(
                "Settings import failed: %s", error.__class__.__name__
            )
            return False

    def backup_settings(self, *, include_state: bool = False) -> Optional[Path]:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            directory = self.get_config_directory() / "settings_backups"
            directory.mkdir(parents=True, exist_ok=True)
            backup_file = directory / f"{self.app_name.lower()}_backup_{timestamp}.json"
            return backup_file if self.export_settings(
                backup_file, include_state=include_state
            ) else None
        except Exception as error:
            get_logger(__name__).warning(
                "Settings backup failed: %s", error.__class__.__name__
            )
            return None

    def restore_settings(
        self, backup_file: Union[str, Path], *, include_state: bool = False
    ) -> bool:
        return self.import_settings(backup_file, include_state=include_state)
    def get_config_directory(self) -> Path:
        """Return a writable directory for themes, caches, drafts, and backups.

        Native QSettings is registry-backed on Windows, where ``fileName()``
        is a registry path rather than a filesystem location.
        """
        if self.use_json:
            directory = self.config_dir
        else:
            directory = Path(
                QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
            )
            if directory.name.casefold() != self.app_name.casefold():
                safe_app_name = "".join(
                    character
                    for character in self.app_name
                    if character.isalnum() or character in {"-", "_", " "}
                ).strip() or "MedImager"
                directory = directory / safe_app_name
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def reset_to_defaults(self, default_settings: Dict[str, Any]) -> None:
        """重置为默认设置
        
        Args:
            default_settings: 默认设置字典
        """
        self.clear_all_settings()
        self.set_many(default_settings)
        self._ensure_schema_version()
            
    def get_performance_manager(self) -> PerformanceManager:
        """获取性能管理器
        
        Returns:
            PerformanceManager: 性能管理器实例
        """
        return self.performance_manager
        
    def get_performance_info(self) -> Dict[str, Any]:
        """获取性能信息
        
        Returns:
            Dict[str, Any]: 性能信息
        """
        return {
            'thread_count': self.performance_manager.get_thread_count(),
            'cache_info': self.performance_manager.get_cache_info()
        }
        
    def shutdown(self) -> None:
        """关闭设置管理器"""
        self.performance_manager.shutdown()


# 全局设置管理器实例
_settings_manager: Optional[SettingsManager] = None
_settings_manager_lock = threading.Lock()


def get_settings_manager() -> SettingsManager:
    """获取全局设置管理器单例实例

    所有组件应通过此函数获取 SettingsManager，而不是自行创建实例。

    Returns:
        SettingsManager: 设置管理器实例
    """
    global _settings_manager
    if _settings_manager is None:
        with _settings_manager_lock:
            if _settings_manager is None:
                smoke_root = os.environ.get(
                    "MEDIMAGER_SMOKE_APP_DATA_ROOT", ""
                ).strip()
                _settings_manager = (
                    SettingsManager(
                        use_json=True,
                        config_dir=Path(smoke_root) / "config",
                    )
                    if smoke_root
                    else SettingsManager()
                )
    return _settings_manager


def get_setting(key: str, default_value: Any = None) -> Any:
    """获取设置值的便捷函数
    
    Args:
        key: 设置键名
        default_value: 默认值
        
    Returns:
        Any: 设置值
    """
    return get_settings_manager().get_setting(key, default_value)


def set_setting(key: str, value: Any) -> None:
    """设置值的便捷函数
    
    Args:
        key: 设置键名
        value: 设置值
    """
    get_settings_manager().set_setting(key, value)


def get_performance_manager() -> PerformanceManager:
    """获取性能管理器的便捷函数
    
    Returns:
        PerformanceManager: 性能管理器实例
    """
    return get_settings_manager().get_performance_manager()


def shutdown_settings_manager() -> None:
    """关闭设置管理器的便捷函数"""
    global _settings_manager
    if _settings_manager is not None:
        _settings_manager.shutdown()
        _settings_manager = None
