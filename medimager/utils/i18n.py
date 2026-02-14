#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国际化 (i18n) 工具模块
用于加载和管理翻译文件
"""

import os
import threading
from typing import Optional
from PySide6.QtCore import QTranslator, QCoreApplication, QLocale, QEvent
from PySide6.QtWidgets import QApplication

from medimager.utils.logger import get_logger

import weakref

logger = get_logger(__name__)


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
        logger.debug(f"开始加载翻译: {language_code}")

        # 如果已经有翻译器，先移除它
        if self.current_translator and self.app:
            self.app.removeTranslator(self.current_translator)
            self.current_translator = None

        # 如果是默认语言（中文），不需要加载翻译文件
        if language_code == 'zh_CN':
            logger.debug(f"切换到默认语言: {language_code}")

            # 发送语言变更事件，通知所有组件更新显示的文本
            if self.app:
                language_change_event = QEvent(QEvent.LanguageChange)
                QApplication.sendEvent(self.app, language_change_event)

            self.notify_subscribers()
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
            logger.error(f"翻译文件不存在: {ts_file}")
            return False

        # 创建并加载翻译器
        translator = QTranslator()

        if translator.load(ts_file):
            if self.app:
                self.app.installTranslator(translator)
            self.current_translator = translator
            logger.info(f"成功加载翻译文件: {ts_file}")

            # 发送语言变更事件
            if self.app:
                language_change_event = QEvent(QEvent.LanguageChange)
                QApplication.sendEvent(self.app, language_change_event)

            self.notify_subscribers()
            return True
        else:
            logger.error(f"加载翻译文件失败: {ts_file}")
            return False

    def subscribe(self, widget):
        """订阅语言变更通知"""
        if hasattr(widget, 'retranslate_ui'):
            self._subscribers.add(widget)
            logger.debug(f"{widget.__class__.__name__} 已订阅语言变更")

    def unsubscribe(self, widget):
        """取消订阅语言变更通知"""
        self._subscribers.discard(widget)
        logger.debug(f"{widget.__class__.__name__} 已取消订阅语言变更")

    def notify_subscribers(self):
        """通知所有订阅者更新UI"""
        # 迭代WeakSet的快照，防止迭代期间集合大小变化
        subscribers = list(self._subscribers)
        logger.debug(f"通知 {len(subscribers)} 个订阅者更新UI")
        for widget in subscribers:
            try:
                widget.retranslate_ui()
            except Exception as e:
                logger.error(f"更新 {widget.__class__.__name__} 时出错: {e}")

    def get_system_language(self) -> str:
        """获取系统默认语言

        Returns:
            str: 语言代码
        """
        system_locale = QLocale.system()
        language_code = system_locale.name()  # 例如: 'zh_CN', 'en_US'

        # 动态获取支持的语言列表
        supported_languages = self.get_available_languages()

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


# 全局翻译管理器单例
_translation_manager: Optional[TranslationManager] = None
_translation_manager_lock = threading.Lock()


def get_translation_manager() -> TranslationManager:
    """获取全局翻译管理器单例实例

    Returns:
        TranslationManager: 翻译管理器实例
    """
    global _translation_manager
    if _translation_manager is None:
        with _translation_manager_lock:
            if _translation_manager is None:
                _translation_manager = TranslationManager()
    return _translation_manager