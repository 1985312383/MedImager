#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置管理模块
处理用户偏好设置的保存与加载
"""

import json
import os
import gc
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QSettings, QStandardPaths, QObject, Signal


class PerformanceManager:
    """性能管理器
    
    负责管理应用程序的性能相关设置
    """
    
    def __init__(self):
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._cache_size_mb: int = 256
        self._thread_count: int = 4
        self._cache_data: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()
        
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
            self._thread_pool.shutdown(wait=True)
            
        self._thread_pool = ThreadPoolExecutor(max_workers=self._thread_count)
        print(f"线程数量已设置为: {self._thread_count}")
        
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
            
        print(f"缓存大小已设置为: {self._cache_size_mb}MB")
        
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
        with self._cache_lock:
            self._cache_data[key] = data
            
            # 简单的缓存大小控制（基于条目数量）
            max_items = self._cache_size_mb * 10  # 简单映射：1MB = 10个条目
            if len(self._cache_data) > max_items:
                # 移除最旧的条目（简单FIFO）
                oldest_key = next(iter(self._cache_data))
                del self._cache_data[oldest_key]
                
    def get_from_cache(self, key: str) -> Optional[Any]:
        """从缓存获取数据
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存数据，不存在返回None
        """
        with self._cache_lock:
            return self._cache_data.get(key)
            
    def clear_cache(self) -> None:
        """清空缓存"""
        with self._cache_lock:
            self._cache_data.clear()
            gc.collect()  # 强制垃圾回收
            
    def _cleanup_cache(self) -> None:
        """清理超出大小限制的缓存"""
        max_items = self._cache_size_mb * 10
        with self._cache_lock:
            while len(self._cache_data) > max_items:
                oldest_key = next(iter(self._cache_data))
                del self._cache_data[oldest_key]
            gc.collect()
            
    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息
        
        Returns:
            Dict[str, Any]: 缓存信息
        """
        with self._cache_lock:
            return {
                'size_mb': self._cache_size_mb,
                'item_count': len(self._cache_data),
                'estimated_usage_mb': len(self._cache_data) / 10  # 简单估算
            }
            
    def shutdown(self) -> None:
        """关闭性能管理器"""
        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=True)
        self.clear_cache()


class SettingsManager(QObject):
    """设置管理器
    
    负责应用程序设置的保存、加载和管理
    支持多种存储格式和位置
    """
    
    # 性能设置变化信号
    performance_settings_changed = Signal(str, object)  # 设置类型, 新值
    
    def __init__(self, 
                 app_name: str = "MedImager",
                 org_name: str = "MedImager Project",
                 use_json: bool = False,
                 parent: Optional[QObject] = None) -> None:
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
        
        # 初始化性能管理器
        self.performance_manager = PerformanceManager()
        
        if use_json:
            # 使用JSON文件存储
            self.config_dir = Path(
                QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
            )
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.config_file = self.config_dir / f"{app_name.lower()}_settings.json"
            self._settings_data: Dict[str, Any] = {}
            self._load_json_settings()
        else:
            # 使用Qt的QSettings
            self.qt_settings = QSettings(org_name, app_name)
            
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
        """从JSON文件加载设置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._settings_data = json.load(f)
            else:
                self._settings_data = {}
        except Exception as e:
            print(f"加载设置文件失败: {e}")
            self._settings_data = {}
            
    def _save_json_settings(self) -> None:
        """保存设置到JSON文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._settings_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存设置文件失败: {e}")
            
    def get_setting(self, key: str, default_value: Any = None) -> Any:
        """获取设置值
        
        Args:
            key: 设置键名
            default_value: 默认值
            
        Returns:
            Any: 设置值
        """
        if self.use_json:
            return self._settings_data.get(key, default_value)
        else:
            return self.qt_settings.value(key, default_value)
            
    def set_setting(self, key: str, value: Any) -> None:
        """设置值
        
        Args:
            key: 设置键名
            value: 设置值
        """
        if self.use_json:
            self._settings_data[key] = value
            self._save_json_settings()
        else:
            self.qt_settings.setValue(key, value)
            self.qt_settings.sync()
            
        # 处理性能设置的实时应用
        if key == 'thread_count':
            self.performance_manager.set_thread_count(int(value))
            self.performance_settings_changed.emit('thread_count', value)
        elif key == 'cache_size':
            self.performance_manager.set_cache_size(int(value))
            self.performance_settings_changed.emit('cache_size', value)
            
    def has_setting(self, key: str) -> bool:
        """检查是否存在指定设置
        
        Args:
            key: 设置键名
            
        Returns:
            bool: 是否存在
        """
        if self.use_json:
            return key in self._settings_data
        else:
            return self.qt_settings.contains(key)
            
    def remove_setting(self, key: str) -> None:
        """删除设置
        
        Args:
            key: 设置键名
        """
        if self.use_json:
            if key in self._settings_data:
                del self._settings_data[key]
                self._save_json_settings()
        else:
            self.qt_settings.remove(key)
            
    def get_all_settings(self) -> Dict[str, Any]:
        """获取所有设置
        
        Returns:
            Dict[str, Any]: 所有设置的字典
        """
        if self.use_json:
            return self._settings_data.copy()
        else:
            settings = {}
            for key in self.qt_settings.allKeys():
                settings[key] = self.qt_settings.value(key)
            return settings
            
    def clear_all_settings(self) -> None:
        """清除所有设置"""
        if self.use_json:
            self._settings_data.clear()
            self._save_json_settings()
        else:
            self.qt_settings.clear()
            
    def save_settings(self) -> None:
        """保存设置（对于Qt设置这是同步操作）"""
        if self.use_json:
            self._save_json_settings()
        else:
            self.qt_settings.sync()
            
    def export_settings(self, file_path: Union[str, Path]) -> bool:
        """导出设置到文件
        
        Args:
            file_path: 导出文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            settings = self.get_all_settings()
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"导出设置失败: {e}")
            return False
            
    def import_settings(self, file_path: Union[str, Path]) -> bool:
        """从文件导入设置
        
        Args:
            file_path: 导入文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_settings = json.load(f)
                
            # 批量设置
            for key, value in imported_settings.items():
                self.set_setting(key, value)
                
            return True
        except Exception as e:
            print(f"导入设置失败: {e}")
            return False
            
    def backup_settings(self) -> Optional[Path]:
        """备份当前设置
        
        Returns:
            Optional[Path]: 备份文件路径，失败返回None
        """
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.config_dir / f"{self.app_name.lower()}_backup_{timestamp}.json"
            
            if self.export_settings(backup_file):
                return backup_file
            return None
        except Exception as e:
            print(f"备份设置失败: {e}")
            return None
            
    def restore_settings(self, backup_file: Union[str, Path]) -> bool:
        """从备份恢复设置
        
        Args:
            backup_file: 备份文件路径
            
        Returns:
            bool: 是否成功
        """
        return self.import_settings(backup_file)
        
    def get_config_directory(self) -> Path:
        """获取配置目录路径
        
        Returns:
            Path: 配置目录路径
        """
        if self.use_json:
            return self.config_dir
        else:
            # Qt设置的位置因平台而异
            return Path(self.qt_settings.fileName()).parent
            
    def reset_to_defaults(self, default_settings: Dict[str, Any]) -> None:
        """重置为默认设置
        
        Args:
            default_settings: 默认设置字典
        """
        self.clear_all_settings()
        for key, value in default_settings.items():
            self.set_setting(key, value)
            
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


def get_settings_manager() -> SettingsManager:
    """获取全局设置管理器实例
    
    Returns:
        SettingsManager: 设置管理器实例
    """
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
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