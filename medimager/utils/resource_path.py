#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源路径处理工具

用于处理开发环境和打包环境中的资源文件路径问题。
"""

import os
import sys
from pathlib import Path
from typing import Optional

from medimager.utils.logger import get_logger

logger = get_logger(__name__)


def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径
    
    在开发环境中，返回相对于项目根目录的路径。
    在打包环境中，返回相对于可执行文件的路径。
    
    Args:
        relative_path: 相对路径，如 'medimager/icons/logo.png'
        
    Returns:
        资源文件的绝对路径
    """
    try:
        # 检查是否在打包环境中（PyInstaller）
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # 打包环境：使用 _MEIPASS 路径
            base_path = sys._MEIPASS
            resource_path = os.path.join(base_path, relative_path)
            logger.debug(f"[get_resource_path] 打包环境路径: {resource_path}")
        else:
            # 开发环境：使用项目根目录
            # 获取项目根目录（medimager包的父目录）
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent  # utils -> medimager -> project_root
            resource_path = os.path.join(project_root, relative_path)
            logger.debug(f"[get_resource_path] 开发环境路径: {resource_path}")
        
        # 验证文件是否存在
        if os.path.exists(resource_path):
            logger.debug(f"[get_resource_path] 资源文件找到: {resource_path}")
            return resource_path
        else:
            logger.warning(f"[get_resource_path] 资源文件不存在: {resource_path}")
            return resource_path  # 即使不存在也返回路径，让调用者处理
            
    except Exception as e:
        logger.error(f"[get_resource_path] 获取资源路径失败: {e}")
        return relative_path


def get_icon_path(icon_name: str) -> str:
    """获取图标文件路径
    
    Args:
        icon_name: 图标文件名，如 'logo.png' 或 'layout.svg'
        
    Returns:
        图标文件的绝对路径
    """
    return get_resource_path(f"medimager/icons/{icon_name}")


def get_test_data_path(test_file: str) -> str:
    """获取测试数据文件路径
    
    Args:
        test_file: 测试文件相对路径，如 'dcm/water_phantom/water_phantom_slice_001.dcm'
        
    Returns:
        测试数据文件的绝对路径
    """
    return get_resource_path(f"medimager/tests/{test_file}")


def get_theme_path(theme_file: str) -> str:
    """获取主题文件路径
    
    Args:
        theme_file: 主题文件相对路径，如 'ui/dark.toml'
        
    Returns:
        主题文件的绝对路径
    """
    return get_resource_path(f"medimager/themes/{theme_file}")


def get_translation_path(translation_file: str) -> str:
    """获取翻译文件路径
    
    Args:
        translation_file: 翻译文件名，如 'zh_CN.qm'
        
    Returns:
        翻译文件的绝对路径
    """
    return get_resource_path(f"medimager/translations/{translation_file}")


def verify_resource_exists(resource_path: str) -> bool:
    """验证资源文件是否存在
    
    Args:
        resource_path: 资源文件路径
        
    Returns:
        文件是否存在
    """
    exists = os.path.exists(resource_path)
    if not exists:
        logger.warning(f"[verify_resource_exists] 资源文件不存在: {resource_path}")
    return exists


def list_available_icons() -> list:
    """列出所有可用的图标文件
    
    Returns:
        图标文件名列表
    """
    try:
        icons_dir = get_resource_path("medimager/icons")
        if os.path.exists(icons_dir):
            return [f for f in os.listdir(icons_dir) if f.endswith(('.svg', '.png', '.ico'))]
        else:
            logger.warning(f"[list_available_icons] 图标目录不存在: {icons_dir}")
            return []
    except Exception as e:
        logger.error(f"[list_available_icons] 列出图标文件失败: {e}")
        return []


def list_available_test_data() -> list:
    """列出所有可用的测试数据文件
    
    Returns:
        测试数据文件相对路径列表
    """
    try:
        test_data_dir = get_resource_path("medimager/tests")
        if os.path.exists(test_data_dir):
            files = []
            for root, dirs, filenames in os.walk(test_data_dir):
                for filename in filenames:
                    if filename.endswith('.dcm'):
                        rel_path = os.path.relpath(os.path.join(root, filename), test_data_dir)
                        files.append(rel_path.replace('\\', '/'))
            return files
        else:
            logger.warning(f"[list_available_test_data] 测试数据目录不存在: {test_data_dir}")
            return []
    except Exception as e:
        logger.error(f"[list_available_test_data] 列出测试数据文件失败: {e}")
        return []