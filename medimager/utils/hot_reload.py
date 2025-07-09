#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热重载 (Hot Reload) 工具模块
支持在Qt应用运行时动态重载Python模块
"""

import importlib
import sys
import os
import time
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QFileSystemWatcher, Signal


class HotReloader(QObject):
    """热重载管理器
    
    监控Python文件变化并自动重载模块
    """
    
    # 信号：模块重载完成
    module_reloaded = Signal(str)
    reload_failed = Signal(str, str)
    ui_module_reloaded = Signal(str)  # 为UI模块添加的新信号
    
    def __init__(self, ui_modules: Optional[List[str]] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        
        self.watched_modules: Dict[str, Any] = {}  # 模块名 -> 模块对象
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.fileChanged.connect(self._on_file_changed)
        
        # 延迟重载定时器（避免频繁重载）
        self.reload_timer = QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.timeout.connect(self._perform_reload)
        self.pending_files = set()
        
        self.ui_modules = ui_modules or [] # 需要特殊处理的UI模块列表
        
    def watch_module(self, module_name: str) -> bool:
        """添加模块到监控列表
        
        Args:
            module_name: 模块名，如 'medimager.core.analysis'
            
        Returns:
            bool: 是否成功添加监控
        """
        try:
            # 导入模块
            module = importlib.import_module(module_name)
            
            # 获取模块文件路径
            if hasattr(module, '__file__') and module.__file__:
                file_path = Path(module.__file__)
                if file_path.suffix == '.pyc':
                    file_path = file_path.with_suffix('.py')
                    
                if file_path.exists():
                    self.watched_modules[module_name] = module
                    self.file_watcher.addPath(str(file_path))
                    print(f"✓ 开始监控模块: {module_name} ({file_path})")
                    return True
                else:
                    print(f"✗ 模块文件不存在: {file_path}")
                    return False
            else:
                print(f"✗ 无法获取模块文件路径: {module_name}")
                return False
                
        except ImportError as e:
            print(f"✗ 导入模块失败: {module_name} - {e}")
            return False
            
    def unwatch_module(self, module_name: str) -> None:
        """停止监控指定模块
        
        Args:
            module_name: 模块名
        """
        if module_name in self.watched_modules:
            module = self.watched_modules[module_name]
            if hasattr(module, '__file__') and module.__file__:
                file_path = str(Path(module.__file__))
                self.file_watcher.removePath(file_path)
            del self.watched_modules[module_name]
            print(f"✓ 停止监控模块: {module_name}")
            
    def reload_module(self, module_name: str) -> bool:
        """手动重载指定模块
        
        Args:
            module_name: 模块名
            
        Returns:
            bool: 是否重载成功
        """
        if module_name not in self.watched_modules:
            print(f"✗ 模块未在监控列表中: {module_name}")
            return False
            
        try:
            print(f"🔄 重载模块: {module_name}")
            
            # 重载模块
            old_module = self.watched_modules[module_name]
            reloaded_module = importlib.reload(old_module)
            self.watched_modules[module_name] = reloaded_module
            
            print(f"✓ 模块重载成功: {module_name}")
            self.module_reloaded.emit(module_name)
            
            # 如果是UI模块，则发出专用信号
            if module_name in self.ui_modules:
                print(f"UI模块 {module_name} 已重载，发送UI更新信号")
                self.ui_module_reloaded.emit(module_name)
            
            return True
            
        except Exception as e:
            error_msg = f"模块重载失败: {e}"
            print(f"✗ {error_msg}")
            self.reload_failed.emit(module_name, error_msg)
            return False
            
    def _on_file_changed(self, file_path: str) -> None:
        """文件变化回调"""
        # 将文件添加到待重载列表
        self.pending_files.add(file_path)
        
        # 延迟执行重载（避免频繁重载）
        self.reload_timer.start(500)  # 500ms延迟
        
    def _perform_reload(self) -> None:
        """执行延迟重载"""
        for file_path in self.pending_files:
            # 查找对应的模块
            for module_name, module in self.watched_modules.items():
                if hasattr(module, '__file__') and module.__file__:
                    module_path = str(Path(module.__file__))
                    if module_path == file_path or module_path.replace('.pyc', '.py') == file_path:
                        self.reload_module(module_name)
                        break
                        
        self.pending_files.clear()


class DynamicFunctionLoader:
    """动态函数加载器
    
    支持从文件中动态加载和执行函数
    """
    
    def __init__(self) -> None:
        self.loaded_functions: Dict[str, Callable] = {}
        
    def load_function_from_file(self, file_path: str, function_name: str) -> Optional[Callable]:
        """从文件中加载指定函数
        
        Args:
            file_path: Python文件路径
            function_name: 函数名
            
        Returns:
            Optional[Callable]: 加载的函数对象，失败返回None
        """
        try:
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
                
            # 创建模块命名空间
            namespace = {}
            
            # 执行代码
            exec(code, namespace)
            
            # 获取函数
            if function_name in namespace:
                func = namespace[function_name]
                if callable(func):
                    key = f"{file_path}::{function_name}"
                    self.loaded_functions[key] = func
                    print(f"✓ 动态加载函数: {function_name} from {file_path}")
                    return func
                else:
                    print(f"✗ {function_name} 不是可调用对象")
                    return None
            else:
                print(f"✗ 函数 {function_name} 在文件中未找到")
                return None
                
        except Exception as e:
            print(f"✗ 加载函数失败: {e}")
            return None
            
    def reload_function(self, file_path: str, function_name: str) -> Optional[Callable]:
        """重新加载函数
        
        Args:
            file_path: Python文件路径
            function_name: 函数名
            
        Returns:
            Optional[Callable]: 重新加载的函数对象
        """
        print(f"🔄 重新加载函数: {function_name} from {file_path}")
        return self.load_function_from_file(file_path, function_name)
        
    def execute_function(self, file_path: str, function_name: str, *args, **kwargs) -> Any:
        """执行动态加载的函数
        
        Args:
            file_path: Python文件路径
            function_name: 函数名
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 函数执行结果
        """
        key = f"{file_path}::{function_name}"
        
        if key not in self.loaded_functions:
            # 尝试加载函数
            func = self.load_function_from_file(file_path, function_name)
            if not func:
                raise RuntimeError(f"无法加载函数: {function_name}")
        else:
            func = self.loaded_functions[key]
            
        # 执行函数
        return func(*args, **kwargs)


# 全局热重载管理器实例
_hot_reloader: Optional[HotReloader] = None


def get_hot_reloader() -> HotReloader:
    """获取全局热重载管理器实例"""
    global _hot_reloader
    if _hot_reloader is None:
        _hot_reloader = HotReloader()
    return _hot_reloader


def enable_hot_reload(*module_names: str) -> None:
    """启用指定模块的热重载
    
    Args:
        *module_names: 要监控的模块名列表
    """
    reloader = get_hot_reloader()
    for module_name in module_names:
        reloader.watch_module(module_name)


def disable_hot_reload(*module_names: str) -> None:
    """禁用指定模块的热重载
    
    Args:
        *module_names: 要停止监控的模块名列表
    """
    reloader = get_hot_reloader()
    for module_name in module_names:
        reloader.unwatch_module(module_name)


def enable_directory_hot_reload(
    package_name: str,
    excluded_modules: Optional[List[str]] = None,
    ui_modules: Optional[List[str]] = None,
    parent: Optional[QObject] = None
) -> HotReloader:
    """启用整个包目录的热重载
    
    Args:
        package_name: 包名，如 'medimager'
        excluded_modules: 要排除的模块列表
        ui_modules: 要特殊处理的模块列表
        parent: 父对象
    """
    if excluded_modules is None:
        excluded_modules = []
    
    try:
        import pkgutil
        import importlib
        
        # 导入包
        package = importlib.import_module(package_name)
        
        if not hasattr(package, '__path__'):
            print(f"✗ {package_name} 不是一个包")
            return
            
        modules_found = []
        
        # 遍历包中的所有模块
        for importer, modname, ispkg in pkgutil.walk_packages(
            package.__path__, 
            package.__name__ + "."
        ):
            # 跳过排除的模块
            if any(excluded in modname for excluded in excluded_modules):
                print(f"⚠ 跳过排除的模块: {modname}")
                continue
                
            # 跳过__pycache__等特殊目录
            if '__pycache__' in modname or '.pyc' in modname:
                continue
                
            try:
                # 尝试导入模块以验证其有效性
                importlib.import_module(modname)
                modules_found.append(modname)
            except Exception as e:
                print(f"⚠ 跳过无法导入的模块: {modname} - {e}")
                
        # 启用热重载
        if modules_found:
            print(f"✓ 为包 {package_name} 启用热重载，找到 {len(modules_found)} 个模块:")
            reloader = HotReloader(ui_modules, parent)
            for module_name in modules_found:
                if module_name not in excluded_modules:
                    reloader.watch_module(module_name)
            return reloader
        else:
            print(f"⚠ 在包 {package_name} 中未找到可监控的模块")
            
    except Exception as e:
        print(f"✗ 启用目录热重载失败: {e}") 