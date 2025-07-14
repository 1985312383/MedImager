print("--- MedImager main.py loaded ---")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MedImager - 现代化的 DICOM 查看器与图像分析工具
应用程序入口点

职责:
- 初始化 QApplication
- 加载全局配置（日志、设置）
- 加载多语言翻译文件
- 创建并显示 MainWindow
- 启动应用程序事件循环
"""

import sys
import os
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QTranslator, QLocale
from PySide6.QtGui import QIcon

# 兼容直接 python main.py 运行
if __name__ == "__main__" and __package__ is None:
    sys.path.append(str(Path(__file__).parent.parent.resolve()))
    __package__ = "medimager"

# 导入项目模块
from medimager.utils.logger import setup_logger, get_logger
from medimager.utils.settings import SettingsManager
from medimager.utils.i18n import TranslationManager

from medimager.ui.main_window import MainWindow


class MedImagerApplication:
    """MedImager应用程序类
    
    负责应用程序的完整初始化和生命周期管理
    """
    
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.main_window: Optional[MainWindow] = None

        self.logger = None
        self.settings_manager = None
        self.translation_manager = None
        
    def initialize(self) -> bool:
        """初始化应用程序"""
        try:
            # 1. 初始化日志系统 (必须最先)
            if not self._setup_logging():
                return False


            
            # 2. 加载应用程序设置
            if not self._load_settings():
                return False

            # 3. 设置应用程序图标
            self._setup_application_icon()

            # 4. 加载国际化翻译文件
            if not self._setup_translations():
                return False
            
            # 5. 创建主窗口
            if not self._create_main_window():
                return False
            
            self.logger.info("应用程序初始化完成")
            return True

        except Exception as e:
            # 使用 print 因为此时 logger 可能还不可用
            print(f"应用程序初始化过程中发生严重错误: {e}")
            self._show_error(f"应用程序初始化失败: {e}")
            return False
            


    def _setup_logging(self) -> bool:
        """设置日志系统"""
        try:
            # 创建日志目录
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            
            # 初始化日志系统
            setup_logger(
                log_file=log_dir / "medimager.log",
                level="INFO",
                console_output=True
            )
            
            self.logger = get_logger(__name__)
            self.logger.info("日志系统初始化完成")
            
            return True
            
        except Exception as e:
            self._show_error(f"日志系统初始化失败: {e}")
            return False
            
    def _load_settings(self) -> bool:
        """加载应用程序设置"""
        try:
            self.settings_manager = SettingsManager()
            
            # 设置默认值
            default_settings = {
                'language': 'zh_CN',
                'ui_theme': 'dark',  # 改为深色主题
                'window_geometry': None,
                'window_state': None,
                'recent_files': [],
                'max_recent_files': 10,
                'auto_save_interval': 300,  # 5分钟
                'log_level': 'INFO'
            }
            
            # 加载设置并设置默认值
            for key, default_value in default_settings.items():
                if not self.settings_manager.has_setting(key):
                    self.settings_manager.set_setting(key, default_value)
                    
            self.logger.info("应用程序设置加载完成")
            return True
            
        except Exception as e:
            self._show_error(f"设置加载失败: {e}")
            return False
            
    def _setup_application_icon(self) -> None:
        """设置应用程序图标"""
        try:
            icon_path = "medimager/icons/logo.png"
            if Path(icon_path).exists():
                icon = QIcon(icon_path)
                self.app.setWindowIcon(icon)
                self.logger.info(f"应用程序图标设置完成: {icon_path}")
            else:
                self.logger.warning("未找到应用程序图标文件: medimager/icons/logo.png")
                
        except Exception as e:
            self.logger.warning(f"设置应用程序图标失败: {e}")
            
    def _setup_translations(self) -> bool:
        """设置多语言支持"""
        try:
            self.translation_manager = TranslationManager()
            
            # 获取语言设置，确保默认为中文
            language = self.settings_manager.get_setting('language', 'zh_CN')
            
            # 只在非中文时加载翻译文件，中文是源语言不需要翻译
            if language != 'zh_CN':
                if self.translation_manager.load_translation(language):
                    self.logger.info(f"翻译文件加载完成: {language}")
                else:
                    self.logger.warning(f"翻译文件加载失败，使用默认语言: {language}")
            else:
                self.logger.info(f"使用默认语言: {language}")
                
            return True
            
        except Exception as e:
            self.logger.error(f"多语言支持初始化失败: {e}")
            return False
            
    def _create_main_window(self) -> bool:
        """创建主窗口"""
        try:
            self.main_window = MainWindow()
            
            # 恢复窗口几何和状态
            self._restore_window_state()
            
            # 连接窗口关闭信号
            self.main_window.closeEvent = self._on_main_window_close
            
            self.logger.info("主窗口创建完成")
            return True
            
        except Exception as e:
            self._show_error(f"主窗口创建失败: {e}")
            return False
            
    def _restore_window_state(self) -> None:
        """恢复窗口状态"""
        try:
            # 恢复窗口几何
            geometry = self.settings_manager.get_setting('window_geometry')
            if geometry:
                self.main_window.restoreGeometry(geometry)
            else:
                # 如果没有保存的几何信息（例如首次启动），则设置一个默认大小
                self.main_window.setGeometry(100, 100, 1280, 720)
                
            # 恢复窗口状态
            state = self.settings_manager.get_setting('window_state')
            if state:
                self.main_window.restoreState(state)
                
            self.logger.info("窗口状态恢复完成")
            
        except Exception as e:
            self.logger.warning(f"窗口状态恢复失败: {e}")
            
    def _save_window_state(self) -> None:
        """保存窗口状态"""
        try:
            if self.main_window:
                # 保存窗口几何
                self.settings_manager.set_setting(
                    'window_geometry', 
                    self.main_window.saveGeometry()
                )
                
                # 保存窗口状态
                self.settings_manager.set_setting(
                    'window_state', 
                    self.main_window.saveState()
                )
                
            self.logger.info("窗口状态保存完成")
            
        except Exception as e:
            self.logger.warning(f"窗口状态保存失败: {e}")
            
    def _on_main_window_close(self, event) -> None:
        """主窗口关闭事件处理"""
        try:
            self.logger.info("应用程序正在关闭...")
            
            # 保存窗口状态
            self._save_window_state()
            
            # 保存设置
            if self.settings_manager:
                self.settings_manager.save_settings()
                
            # 接受关闭事件
            event.accept()
            
        except Exception as e:
            self.logger.error(f"关闭应用程序时出错: {e}")
            event.accept()  # 即使出错也要关闭
            
    def _show_error(self, message: str) -> None:
        """显示错误消息"""
        if self.app:
            QMessageBox.critical(None, "错误", message)
        else:
            print(f"错误: {message}")
            
    def run(self) -> int:
        """运行应用程序
        
        Returns:
            int: 应用程序退出代码
        """
        if not self.initialize():
            return 1
            
        try:
            # 显示主窗口
            self.main_window.show()
            
            # 启动事件循环
            return self.app.exec()
            
        except Exception as e:
            self.logger.error(f"应用程序运行时出错: {e}")
            return 1


def main() -> int:
    """应用程序主入口点"""
    app = QApplication(sys.argv)
    try:
        medimager_app = MedImagerApplication(app)
        if medimager_app.initialize():
            return medimager_app.run()
        return 1
    except Exception as e:
        # 最后的防线，捕获任何未处理的异常
        print(f"发生致命错误: {e}")
        # 此时可能无法显示QMessageBox，但尝试一下
        try:
            QMessageBox.critical(None, "致命错误", f"应用程序遇到无法恢复的错误:\n\n{e}")
        except:
            pass
        return 1


if __name__ == "__main__":
    # 跨平台支持和特殊配置
    if sys.platform.startswith('win'):
        # Windows 特定配置
        try:
            import ctypes
            # 设置AppUserModelID以在Windows任务栏上正确显示图标
            myappid = 'medimager.dicom_viewer.1.0'  # 更具体的应用程序ID
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            
            # 设置Windows DPI感知
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception as e:
            print(f"Windows配置失败: {e}")
            
    elif sys.platform.startswith('darwin'):
        # macOS 特定配置
        try:
            # 设置macOS应用程序名称
            import Foundation
            bundle = Foundation.NSBundle.mainBundle()
            if bundle:
                info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
                if info:
                    info['CFBundleName'] = 'MedImager'
                    info['CFBundleDisplayName'] = 'MedImager'
                    
            # 设置macOS应用程序图标
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import QApplication
            icon_path = Path("medimager/icons/logo.png")
            if icon_path.exists():
                # 在应用程序创建之前设置图标
                QApplication.setOrganizationName("MedImager")
                QApplication.setOrganizationDomain("medimager.org")
                QApplication.setApplicationName("MedImager")
                
        except Exception as e:
            print(f"macOS配置失败: {e}")
            
    elif sys.platform.startswith('linux'):
        # Linux 特定配置
        try:
            # 设置Linux桌面环境变量
            os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
            
            # 设置应用程序元数据
            from PySide6.QtWidgets import QApplication
            QApplication.setOrganizationName("MedImager")
            QApplication.setOrganizationDomain("medimager.org")
            QApplication.setApplicationName("MedImager")
            QApplication.setApplicationVersion("1.0")
            
            # 设置Linux下的高DPI支持
            os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
            os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
            
        except Exception as e:
            print(f"Linux配置失败: {e}")
    
    # 通用配置
    try:
        # 启用高DPI支持
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # 设置样式
        QApplication.setStyle('Fusion')
        
    except Exception as e:
        print(f"通用配置失败: {e}")

    sys.exit(main()) 