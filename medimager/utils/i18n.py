#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国际化 (i18n) 工具模块
用于加载和管理翻译文件
"""

import os
from typing import Optional
from PySide6.QtCore import QTranslator, QCoreApplication, QLocale


class TranslationManager:
    """翻译管理器
    
    负责加载和管理应用程序的翻译文件
    """
    
    def __init__(self) -> None:
        self.current_translator: Optional[QTranslator] = None
        self.app = QCoreApplication.instance()
        
    def load_translation(self, language_code: str) -> bool:
        """加载指定语言的翻译文件
        
        Args:
            language_code: 语言代码，如 'zh_CN', 'en_US'
            
        Returns:
            bool: 是否成功加载翻译文件
        """
        # 如果已经有翻译器，先移除它
        if self.current_translator:
            self.app.removeTranslator(self.current_translator)
            self.current_translator = None
            
        # 如果是默认语言（中文），不需要加载翻译文件
        if language_code == 'zh_CN':
            print(f"切换到默认语言: {language_code}")
            return True
            
        # 获取翻译文件路径
        translations_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            'translations'
        )
        
        # 构建翻译文件路径
        ts_file = os.path.join(translations_dir, f"{language_code}.qm")
        
        # 检查翻译文件是否存在
        if not os.path.exists(ts_file):
            print(f"翻译文件不存在: {ts_file}")
            return False
            
        # 创建并加载翻译器
        translator = QTranslator()
        if translator.load(ts_file):
            self.app.installTranslator(translator)
            self.current_translator = translator
            print(f"成功加载翻译文件: {ts_file}")
            return True
        else:
            print(f"加载翻译文件失败: {ts_file}")
            return False
            
    def get_system_language(self) -> str:
        """获取系统默认语言
        
        Returns:
            str: 语言代码
        """
        system_locale = QLocale.system()
        language_code = system_locale.name()  # 例如: 'zh_CN', 'en_US'
        
        # 支持的语言列表
        supported_languages = ['zh_CN', 'en_US']
        
        if language_code in supported_languages:
            return language_code
        else:
            # 如果系统语言不支持，返回默认语言
            return 'zh_CN'
            
    def get_available_languages(self) -> list[str]:
        """获取可用的语言列表
        
        Returns:
            list[str]: 可用的语言代码列表
        """
        languages = ['zh_CN']  # 默认语言始终可用
        
        translations_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            'translations'
        )
        
        if os.path.exists(translations_dir):
            for file in os.listdir(translations_dir):
                if file.endswith('.qm'):
                    lang_code = file[:-3]  # 移除 .qm 扩展名
                    if lang_code not in languages:
                        languages.append(lang_code)
                        
        return languages 