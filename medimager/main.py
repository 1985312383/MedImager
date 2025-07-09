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
from medimager.utils.hot_reload import enable_directory_hot_reload
from medimager.ui.main_window import MainWindow


class MedImagerApplication:
    """MedImager应用程序类
    
    负责应用程序的完整初始化和生命周期管理
    """
    
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.main_window: Optional[MainWindow] = None
        self.hot_reloader = None
        self.logger = None
        self.settings_manager = None
        self.translation_manager = None
        
    def initialize(self) -> bool:
        """初始化应用程序"""
        try:
            # 1. 初始化日志系统 (必须最先)
            if not self._setup_logging():
                return False

            # 2. 初始化热重载
            self._init_hot_reload()
            
            # 3. 加载应用程序设置
            if not self._load_settings():
                return False

            # 4. 设置应用程序图标
            self._setup_application_icon()

            # 5. 加载国际化翻译文件
            if not self._setup_translations():
                return False
            
            # 6. 创建主窗口
            if not self._create_main_window():
                return False
            
            self.logger.info("应用程序初始化完成")
            return True

        except Exception as e:
            # 使用 print 因为此时 logger 可能还不可用
            print(f"应用程序初始化过程中发生严重错误: {e}")
            self._show_error(f"应用程序初始化失败: {e}")
            return False
            
    def _get_ui_modules(self) -> List[str]:
        """获取所有 medimager.ui 包下的模块列表"""
        import pkgutil
        import medimager.ui
        
        ui_modules = []
        package = medimager.ui
        
        for importer, modname, ispkg in pkgutil.walk_packages(
            package.__path__,
            package.__name__ + '.'
        ):
            ui_modules.append(modname)
            
        return ui_modules

    def _init_hot_reload(self):
        """初始化热重载功能，并处理UI模块的特殊重载"""
        try:
            self.hot_reloader = enable_directory_hot_reload(
                package_name="medimager",
                excluded_modules=["medimager.utils.hot_reload"],
                ui_modules=self._get_ui_modules(),
                parent=self.app
            )
            if self.hot_reloader:
                self.hot_reloader.ui_module_reloaded.connect(self._handle_ui_reload)
                self.logger.info("UI热重载处理程序已连接")
        except Exception as e:
            self.logger.error(f"初始化热重载失败: {e}")

    def _handle_ui_reload(self, module_name: str):
        """处理UI模块的热重载，通过重建主窗口实现"""
        self.logger.info(f"UI 模块 '{module_name}' 已更新，正在重建主窗口...")

        # 1. 保存旧窗口的状态
        if self.main_window:
            old_geometry = self.main_window.saveGeometry()
            old_state = self.main_window.saveState()
            old_image_data_model = self.main_window.image_data_model
            # 关闭并删除旧窗口
            self.main_window.close()
        else: # 如果窗口不存在，则为空状态
            old_geometry = None
            old_state = None
            old_image_data_model = None

        # 2. 重新导入主窗口模块并创建新窗口
        # 必须重新导入，因为它的子模块(如panel)可能也已更新
        from importlib import reload
        from medimager.ui import main_window as main_window_module
        reload(main_window_module)
        
        self.main_window = main_window_module.MainWindow()
        
        # 3. 恢复状态
        if old_image_data_model:
            self.main_window.image_data_model = old_image_data_model
        if old_geometry:
            self.main_window.restoreGeometry(old_geometry)
        if old_state:
            self.main_window.restoreState(old_state)
            
        self.main_window.show()
        
        self.logger.info("主窗口热重载完成！")

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
    # 在某些平台上，确保脚本在主线程中运行
    if sys.platform.startswith('win'):
        # 设置AppUserModelID以在Windows任务栏上正确显示图标
        try:
            import ctypes
            myappid = 'mycompany.myproduct.subproduct.version' # 可随意设置
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass

    sys.exit(main()) 