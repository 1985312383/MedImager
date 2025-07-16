#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国际化 (i18n) 工具模块
用于加载和管理翻译文件
"""

import os
from typing import Optional
from PySide6.QtCore import QTranslator, QCoreApplication, QLocale, QEvent
from PySide6.QtWidgets import QApplication


import weakref


class TranslationManager:
    """翻译管理器

    负责加载和管理应用程序的翻译文件，并通知所有订阅者更新UI。
    """

    def __init__(self) -> None:
        self.current_translator: Optional[QTranslator] = None
        self.app = QCoreApplication.instance()
        self._subscribers = weakref.WeakSet()
        
    def load_translation(self, language_code: str) -> bool:
        """加载指定语言的翻译文件
        
        Args:
            language_code: 语言代码，如 'zh_CN', 'en_US'
            
        Returns:
            bool: 是否成功加载翻译文件
        """
        print(f"[DEBUG] 开始加载翻译: {language_code}")
        
        # 如果已经有翻译器，先移除它
        if self.current_translator:
            print(f"[DEBUG] 移除现有翻译器")
            self.app.removeTranslator(self.current_translator)
            self.current_translator = None
            
        # 如果是默认语言（中文），不需要加载翻译文件
        if language_code == 'zh_CN':
            print(f"[DEBUG] 切换到默认语言: {language_code}")
            
            # 发送语言变更事件，通知所有组件更新显示的文本
            print(f"[DEBUG] 发送语言变更事件（切换到中文）")
            language_change_event = QEvent(QEvent.LanguageChange)
            QApplication.sendEvent(self.app, language_change_event)
            print(f"[DEBUG] 语言变更事件已发送")

            self.notify_subscribers()

            self.notify_subscribers()
            return True
            
        # 获取翻译文件路径
        translations_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            'translations'
        )
        print(f"[DEBUG] 翻译文件目录: {translations_dir}")
        
        # 构建翻译文件路径
        ts_file = os.path.join(translations_dir, f"{language_code}.qm")
        print(f"[DEBUG] 翻译文件路径: {ts_file}")
        
        # 检查翻译文件是否存在
        if not os.path.exists(ts_file):
            print(f"[ERROR] 翻译文件不存在: {ts_file}")
            # 列出目录中的所有文件
            if os.path.exists(translations_dir):
                files = os.listdir(translations_dir)
                print(f"[DEBUG] 翻译目录中的文件: {files}")
            return False
            
        # 检查文件大小
        file_size = os.path.getsize(ts_file)
        print(f"[DEBUG] 翻译文件大小: {file_size} 字节")
        
        # 创建并加载翻译器
        translator = QTranslator()
        print(f"[DEBUG] 创建翻译器对象")
        
        if translator.load(ts_file):
            print(f"[DEBUG] 翻译器加载文件成功")
            self.app.installTranslator(translator)
            self.current_translator = translator
            print(f"[SUCCESS] 成功加载翻译文件: {ts_file}")
            
            # 发送语言变更事件，通知所有组件更新显示的文本
            print(f"[DEBUG] 发送语言变更事件")
            language_change_event = QEvent(QEvent.LanguageChange)
            QApplication.sendEvent(self.app, language_change_event)
            print(f"[DEBUG] 语言变更事件已发送")
            
            # 测试翻译是否工作
            from PySide6.QtCore import QCoreApplication
            test_text1 = QCoreApplication.translate("SeriesLoadingThread", "文件(&F)")
            test_text2 = QCoreApplication.translate("SeriesLoadingThread", "退出应用程序")
            print(f"[DEBUG] 测试翻译 '文件(&F)' -> '{test_text1}'")
            print(f"[DEBUG] 测试翻译 '退出应用程序' -> '{test_text2}'")
            
            return True
        else:
            print(f"[ERROR] 加载翻译文件失败: {ts_file}")
            return False

    def subscribe(self, widget):
        """订阅语言变更通知"""
        if hasattr(widget, 'retranslate_ui'):
            self._subscribers.add(widget)
            print(f"[DEBUG] {widget.__class__.__name__} 已订阅语言变更")

    def unsubscribe(self, widget):
        """取消订阅语言变更通知"""
        self._subscribers.discard(widget)
        print(f"[DEBUG] {widget.__class__.__name__} 已取消订阅语言变更")

    def notify_subscribers(self):
        """通知所有订阅者更新UI"""
        print(f"[DEBUG] 通知 {len(self._subscribers)} 个订阅者更新UI")
        for widget in self._subscribers:
            try:
                widget.retranslate_ui()
                print(f"[DEBUG] 已更新 {widget.__class__.__name__}")
            except Exception as e:
                print(f"[ERROR] 更新 {widget.__class__.__name__} 时出错: {e}")
            
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