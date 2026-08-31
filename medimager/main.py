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
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

# 兼容直接 python main.py 运行
if __name__ == "__main__" and __package__ is None:
    sys.path.append(str(Path(__file__).parent.parent.resolve()))
    __package__ = "medimager"

# 导入项目模块
from medimager.utils.logger import setup_logger, get_logger
from medimager.utils.settings import get_settings_manager
from medimager.core.settings_registry import DEFAULT_SETTINGS_REGISTRY
from medimager.utils.i18n import get_translation_manager
from medimager.app_info import APP_NAME, get_version

from medimager.ui.main_window import MainWindow


@dataclass(frozen=True)
class StartupRequest:
    """Non-sensitive startup intent parsed before the Qt event loop starts."""

    paths: tuple[str, ...] = ()
    demo: str | None = None


def parse_startup_arguments(argv: Sequence[str]) -> StartupRequest:
    """Parse MedImager arguments while leaving Qt/platform switches alone."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--demo",
        "--example",
        choices=("ct_multiphase", "mr_brain", "geometry_lab"),
    )
    namespace, remaining = parser.parse_known_args(tuple(argv)[1:])
    # Qt keeps its own command-line switches in ``remaining``. A startup
    # source must exist before it can be indexed, which cleanly separates it
    # from option values such as ``--style Fusion`` without duplicating Qt's
    # platform-option parser.
    paths = tuple(
        str(Path(value).expanduser())
        for value in remaining
        if not str(value).startswith("-") and Path(value).expanduser().exists()
    )
    return StartupRequest(
        paths=paths,
        demo=namespace.demo,
    )


def qt_application_arguments(
    argv: Sequence[str],
    request: StartupRequest,
) -> list[str]:
    """Remove MedImager-owned switches before Qt parses platform options."""

    values = list(argv)
    if not values:
        return ["medimager"]
    result = [values[0]]
    skip_demo_value = False
    source_values = set(request.paths)
    for raw in values[1:]:
        value = str(raw)
        if skip_demo_value:
            skip_demo_value = False
            continue
        if value in {"--demo", "--example"}:
            skip_demo_value = True
            continue
        if value.startswith("--demo=") or value.startswith("--example="):
            continue
        expanded = str(Path(value).expanduser())
        if expanded in source_values:
            continue
        result.append(value)
    return result


class MedImagerApplication:
    """MedImager应用程序类
    
    负责应用程序的完整初始化和生命周期管理
    """
    
    def __init__(
        self,
        app: QApplication,
        startup_request: StartupRequest | None = None,
    ) -> None:
        self.app = app
        self.main_window: Optional[MainWindow] = None
        self.startup_request = startup_request or StartupRequest()

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
            # A packaged install may live below Program Files and must never
            # write beside the executable.  The smoke override is restricted
            # to release automation; normal runs use Qt's per-user writable
            # application-data location.
            smoke_root = os.environ.get("MEDIMAGER_SMOKE_APP_DATA_ROOT", "").strip()
            app_data = smoke_root or QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
            if not app_data:
                raise OSError("no writable application-data location")
            log_dir = Path(app_data) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            
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
            self.settings_manager = get_settings_manager()

            # 设置默认值
            default_settings = {
                spec.key: spec.default
                for spec in DEFAULT_SETTINGS_REGISTRY.specs()
                if spec.category != "internal"
            }
            default_settings.update({
                "window_geometry": None,
                "window_state": None,
                "recent_files": [],
                "max_recent_files": 10,
                "auto_save_interval": 300,
                "log_level": "INFO",
            })

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
            from medimager.utils.resource_path import get_icon_path, verify_resource_exists
            
            icon_path = get_icon_path("logo.png")
            if verify_resource_exists(icon_path):
                icon = QIcon(icon_path)
                self.app.setWindowIcon(icon)
                self.logger.info(f"应用程序图标设置完成: {icon_path}")
            else:
                self.logger.warning(f"未找到应用程序图标文件: {icon_path}")
                
        except Exception as e:
            self.logger.warning(f"设置应用程序图标失败: {e}")
            
    def _setup_translations(self) -> bool:
        """设置多语言支持"""
        try:
            self.translation_manager = get_translation_manager()

            language = self.settings_manager.get_setting('language', 'en_US')
            if self.translation_manager.load_translation(language):
                self.logger.info(f"Translation catalog loaded: {language}")
            else:
                self.logger.warning(f"Translation catalog failed, using default language: {language}")

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

            # 使用 aboutToQuit 信号代替 monkey-patch closeEvent
            # 这样不会绕过 PySide6 的 C++ 虚函数分发
            self.app.aboutToQuit.connect(self._on_app_about_to_quit)

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
            
    def _on_app_about_to_quit(self) -> None:
        """应用程序即将退出时的处理"""
        try:
            self.logger.info("应用程序正在关闭...")

            # 保存窗口状态
            self._save_window_state()

            # 保存设置并关闭性能管理器（线程池 + 缓存）
            if self.settings_manager:
                self.settings_manager.save_settings()
                self.settings_manager.shutdown()

        except Exception as e:
            self.logger.error(f"关闭应用程序时出错: {e}")
            
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
            QTimer.singleShot(0, self._dispatch_startup_request)
            
            # 启动事件循环
            return self.app.exec()
            
        except Exception as e:
            self.logger.error(f"应用程序运行时出错: {e}")
            return 1

    def _dispatch_startup_request(self) -> None:
        """Enter the same asynchronous local/demo pipelines used by the UI."""

        if self.main_window is None:
            return
        if self.startup_request.paths:
            self.main_window._open_dropped_paths(self.startup_request.paths)
            return
        if self.startup_request.demo:
            self.main_window._request_demo_study(self.startup_request.demo)


def main() -> int:
    """应用程序主入口点"""
    startup_request = parse_startup_arguments(sys.argv)
    app = QApplication(qt_application_arguments(sys.argv, startup_request))
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(get_version())
    try:
        medimager_app = MedImagerApplication(app, startup_request)
        return medimager_app.run()

    except Exception as e:
        # 最后的防线，捕获任何未处理的异常
        print(f"发生致命错误: {e}")
        # 此时可能无法显示QMessageBox，但尝试一下
        try:
            QMessageBox.critical(None, "致命错误", f"应用程序遇到无法恢复的错误:\n\n{e}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    # 跨平台支持和特殊配置
    if sys.platform.startswith('win'):
        # Windows 特定配置
        try:
            import ctypes
            # 设置AppUserModelID以在Windows任务栏上正确显示图标
            myappid = 'medimager.dicom_viewer.2.6'  # 更具体的应用程序ID
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
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
            from PySide6.QtWidgets import QApplication
            from medimager.utils.resource_path import get_icon_path, verify_resource_exists
            
            icon_path = get_icon_path("logo.png")
            if verify_resource_exists(icon_path):
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
            QApplication.setApplicationVersion(get_version())
            
            # 设置Linux下的高DPI支持
            os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
            os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
            
        except Exception as e:
            print(f"Linux配置失败: {e}")
    
    # 通用配置
    try:
        # AA_EnableHighDpiScaling 和 AA_UseHighDpiPixmaps 在 Qt 6 中已弃用且为 no-op
        # Qt 6 默认启用高DPI支持，无需手动设置

        # 设置样式
        QApplication.setStyle('Fusion')

    except Exception as e:
        print(f"通用配置失败: {e}")

    sys.exit(main())
