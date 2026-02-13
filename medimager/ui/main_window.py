"""
主窗口模块

集成多序列管理器、多视图网格和序列面板的主窗口实现。
支持多序列加载、多视图布局和序列绑定管理。
"""

import os
import uuid
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QFileDialog, QMessageBox, QDialog, QToolBar,
    QButtonGroup, QPushButton, QComboBox, QProgressBar, QToolButton
)
from PySide6.QtCore import Qt, QDir, QTimer
from PySide6.QtGui import QAction, QKeySequence, QIcon, QActionGroup
from PySide6.QtWidgets import QApplication # Added for QApplication.processEvents()

from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.series_view_binding import SeriesViewBindingManager, BindingStrategy
from medimager.core.image_data_model import ImageDataModel
from medimager.core.dicom_parser import DicomParser
from medimager.ui.multi_viewer_grid import MultiViewerGrid
from medimager.ui.panels.series_panel import SeriesPanel
from medimager.ui.panels.dicom_tag_panel import DicomTagPanel
from medimager.ui.dialogs.custom_wl_dialog import CustomWLDialog
from medimager.ui.widgets.panel_toggle_strip import PanelToggleStrip
from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.utils.logger import get_logger
from medimager.utils.settings import SettingsManager, get_settings_manager, get_performance_manager
from medimager.utils.theme_manager import ThemeManager
from medimager.ui.tools.default_tool import DefaultTool
from medimager.ui.tools.roi_tool import EllipseROITool, RectangleROITool, CircleROITool
from medimager.ui.tools.measurement_tool import MeasurementTool
from medimager.ui.main_toolbar import create_main_toolbar

logger = get_logger(__name__)


class _SeriesLoadResult:
    """序列加载结果容器"""
    __slots__ = ('series_id', 'image_model', 'success')

    def __init__(self, series_id: str):
        self.series_id = series_id
        self.image_model: Optional[ImageDataModel] = None
        self.success = False


def _load_series_task(file_paths: List[str], series_id: str) -> _SeriesLoadResult:
    """在线程池中执行的序列加载任务（纯函数，不涉及Qt信号）"""
    result = _SeriesLoadResult(series_id)
    try:
        image_model = ImageDataModel()
        success = image_model.load_dicom_series(file_paths)
        if success:
            result.image_model = image_model
            result.success = True
            logger.info(f"[_load_series_task] 序列加载成功: {series_id}")
        else:
            logger.error(f"[_load_series_task] 序列加载失败: {series_id}")
    except Exception as e:
        logger.error(f"[_load_series_task] 序列加载异常: {e}", exc_info=True)
    return result


class MainWindow(QMainWindow):
    """主窗口
    
    支持多序列管理、多视图布局和高级绑定功能的新主窗口。
    """
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化主窗口"""
        super().__init__(parent)
        logger.debug("[MainWindow.__init__] 开始初始化主窗口")
        
        # 布局切换守卫标志（必须在信号连接之前初始化）
        self._setting_layout = False

        # 使用全局单例设置管理器和主题管理器
        self.settings_manager = get_settings_manager()
        self.theme_manager = ThemeManager(self.settings_manager, self)

        # 初始化核心组件
        self._init_core_components()
        
        # 初始化UI
        self._init_ui()
        
        # 连接信号和槽（在UI创建之后）
        self._connect_signals()
        
        # 确保初始布局正确设置
        self._ensure_initial_layout()
        
        # 应用当前主题（在信号连接之后）
        self.theme_manager.apply_current_theme()
        
        # 更新UI状态
        self._update_ui_state()
        
        # 初始工具传播 - 确保所有视图都使用正确的工具
        logger.info("[MainWindow.__init__] 准备进行初始工具传播")
        self._propagate_tool_to_viewers()
        logger.info("[MainWindow.__init__] 初始工具传播完成")

        # 序列加载状态（future 对象由线程池管理）
        self._loading_futures: Dict[str, object] = {}
        
        logger.info("[MainWindow.__init__] 主窗口初始化完成")
    
    def _ensure_initial_layout(self) -> None:
        """确保初始布局正确设置"""
        logger.debug("[MainWindow._ensure_initial_layout] 确保初始布局设置")
        
        # 显式设置1x1布局，确保序列管理器和多视图网格同步
        self.series_manager.set_layout(1, 1)
        self.multi_viewer_grid.set_layout(1, 1)
        
        logger.debug("[MainWindow._ensure_initial_layout] 初始布局设置完成")
    
    def _init_core_components(self) -> None:
        """初始化核心组件"""
        logger.debug("[MainWindow._init_core_components] 初始化核心组件")
        
        # 多序列管理器
        self.series_manager = MultiSeriesManager(self)
        
        # 同步管理器
        from medimager.core.sync_manager import SyncManager, SyncMode
        self.sync_manager = SyncManager(self.series_manager, self)
        
        # 默认启用基本同步模式（窗宽窗位和切片同步）
        self.sync_manager.set_sync_mode(SyncMode.BASIC)
        
        # 序列视图绑定管理器
        self.binding_manager = SeriesViewBindingManager(self.series_manager, self)
        
        # 设置默认绑定策略
        self.binding_manager.set_binding_strategy(BindingStrategy.AUTO_ASSIGN)
        
        # 初始化默认工具
        self._init_default_tool()
        
        logger.debug("[MainWindow._init_core_components] 核心组件初始化完成")
    
    def _init_ui(self) -> None:
        """初始化用户界面"""
        logger.debug("[MainWindow._init_ui] 初始化主窗口UI")
        
        self.setGeometry(100, 100, 1800, 1000)
        self.setWindowTitle(self.tr("MedImager Pro - 多序列DICOM查看器与分析工具"))
        
        # 中央组件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        # 水平容器：序列面板 + 左切换条 + 视图网格 + 右切换条 + 信息面板
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        main_layout.addLayout(content_layout)

        # 左侧序列面板
        self.series_panel = SeriesPanel(
            self.series_manager,
            self.binding_manager,
            self
        )
        self.series_panel.setMinimumWidth(300)
        self.series_panel.setMaximumWidth(500)
        content_layout.addWidget(self.series_panel)

        # 左侧切换条（序列面板默认可见）
        self.left_toggle_strip = PanelToggleStrip(
            side='left', tooltip=self.tr("展开/收起序列面板"), parent=self)
        self.left_toggle_strip.toggled.connect(self._on_left_toggle_strip_clicked)
        content_layout.addWidget(self.left_toggle_strip)

        # 中央多视图网格
        self.multi_viewer_grid = MultiViewerGrid(self.series_manager, self)
        content_layout.addWidget(self.multi_viewer_grid, 1)

        # 右侧切换条（信息面板默认隐藏）
        self.panel_toggle_strip = PanelToggleStrip(
            side='right', tooltip=self.tr("展开/收起信息面板 (F2)"), parent=self)
        self.panel_toggle_strip.toggled.connect(self._on_toggle_strip_clicked)
        content_layout.addWidget(self.panel_toggle_strip)

        # 右侧信息面板
        self.dicom_tag_panel = DicomTagPanel()
        self.dicom_tag_panel.setMinimumWidth(250)
        self.dicom_tag_panel.setMaximumWidth(400)
        content_layout.addWidget(self.dicom_tag_panel)

        # 默认隐藏右侧面板
        self.dicom_tag_panel.hide()
        
        # 初始化菜单、工具栏和状态栏
        self._init_menus()
        self._init_toolbars()
        self._init_statusbar()
        
        # 设置同步管理器到多视图网格
        self.multi_viewer_grid.set_sync_manager(self.sync_manager)

        # 设置视图网格引用到同步管理器，用于缩放平移同步
        self.sync_manager.set_viewer_grid(self.multi_viewer_grid)
        
        logger.debug("[MainWindow._init_ui] 主窗口UI初始化完成")
    
    def _connect_signals(self) -> None:
        """连接所有信号和槽"""
        logger.debug("[MainWindow._connect_signals] 连接主窗口信号槽")
        
        # 核心组件信号
        self.series_manager.series_added.connect(self._on_series_added)
        self.series_manager.series_loaded.connect(self._on_series_loaded)
        self.series_manager.binding_changed.connect(self._on_binding_changed)
        self.series_manager.layout_changed.connect(self._on_layout_changed)
        
        # 绑定管理器信号
        self.binding_manager.auto_assignment_completed.connect(self._on_auto_assignment_completed)
        
        # 序列面板信号
        self.series_panel.series_selected.connect(self._on_series_selected)
        self.series_panel.binding_requested.connect(self._on_binding_requested)
        
        # 监听活动视图变化以连接切片信号
        self.series_manager.active_view_changed.connect(self._on_view_activated)
        
        # 多视图网格信号
        self.multi_viewer_grid.view_activated.connect(self._on_view_activated)
        self.multi_viewer_grid.layout_changed.connect(self._on_grid_layout_changed)
        self.multi_viewer_grid.binding_requested.connect(self._on_binding_requested)
        
        # 同步管理器信号
        self.sync_manager.sync_mode_changed.connect(self._on_sync_mode_changed)
        self.sync_manager.sync_group_changed.connect(self._on_sync_group_changed)
        
        # 主题管理器信号
        self.theme_manager.theme_changed.connect(self._on_theme_changed)
        
        # 连接已加载序列的切片变化信号（合并到现有方法中）
        
        logger.debug("[MainWindow._connect_signals] 主窗口信号槽连接完成")
    
    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变化时刷新工具栏图标"""
        logger.info(f"[MainWindow._on_theme_changed] 收到主题变化信号: {theme_name}")
        
        try:
            # 刷新工具栏图标
            toolbar_count = 0
            button_count = 0
            action_count = 0
            
            for toolbar in self.findChildren(QToolBar):
                toolbar_count += 1
                logger.debug(f"[MainWindow._on_theme_changed] 处理工具栏: {toolbar.objectName()}")
                
                # 刷新工具栏中的QToolButton（如ROI按钮）
                for widget in toolbar.findChildren(QToolButton):
                    button_count += 1
                    if hasattr(widget, 'refresh_icon'):
                        widget.refresh_icon()
                        logger.debug(f"[MainWindow._on_theme_changed] 刷新了QToolButton: {widget.objectName()}")
                    else:
                        logger.debug(f"[MainWindow._on_theme_changed] QToolButton没有refresh_icon方法: {widget.objectName()}")
                
                # 刷新工具栏中的QAction
                for action in toolbar.actions():
                    if action.icon() and not action.icon().isNull():
                        action_count += 1
                        # 重新创建主题化图标
                        icon_path = getattr(action, '_icon_path', None)
                        if icon_path:
                            new_icon = self.theme_manager.create_themed_icon(icon_path)
                            action.setIcon(new_icon)
                            logger.debug(f"[MainWindow._on_theme_changed] 刷新了QAction图标: {icon_path}")
                        else:
                            logger.debug(f"[MainWindow._on_theme_changed] QAction没有_icon_path: {action.text()}")
            
            logger.info(f"[MainWindow._on_theme_changed] 工具栏图标已更新: {theme_name} "
                       f"(工具栏:{toolbar_count}, 按钮:{button_count}, 动作:{action_count})")
            
        except Exception as e:
            logger.error(f"[MainWindow._on_theme_changed] 刷新工具栏失败: {e}", exc_info=True)
    
    def _init_menus(self) -> None:
        """初始化菜单栏"""
        logger.debug("[MainWindow._init_menus] 初始化主窗口菜单")
        
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu(self.tr("文件(&F)"))
        
        # 打开多个DICOM文件夹
        open_multiple_folders_action = QAction(self.tr("打开多个DICOM文件夹(&M)"), self)
        open_multiple_folders_action.setShortcut("Ctrl+Shift+O")
        open_multiple_folders_action.setStatusTip(self.tr("同时打开多个包含DICOM序列的文件夹"))
        open_multiple_folders_action.triggered.connect(self._open_multiple_dicom_folders)
        file_menu.addAction(open_multiple_folders_action)
        
        # 打开DICOM文件夹
        open_folder_action = QAction(self.tr("打开DICOM文件夹(&D)"), self)
        open_folder_action.setShortcut(QKeySequence.Open)
        open_folder_action.setStatusTip(self.tr("打开包含DICOM序列的文件夹"))
        open_folder_action.triggered.connect(self._open_dicom_folder)
        file_menu.addAction(open_folder_action)
        
        # 打开图像文件
        open_image_action = QAction(self.tr("打开图像文件(&I)"), self)
        open_image_action.setShortcut("Ctrl+O")
        open_image_action.setStatusTip(self.tr("打开单张图像文件"))
        open_image_action.triggered.connect(self._open_image_file)
        file_menu.addAction(open_image_action)
        
        file_menu.addSeparator()
        
        # 导入测试数据
        test_menu = file_menu.addMenu(self.tr("测试数据"))
        
        load_test_series_action = QAction(self.tr("加载测试序列"), self)
        load_test_series_action.triggered.connect(self._load_test_series)
        test_menu.addAction(load_test_series_action)
        
        file_menu.addSeparator()
        
        # 退出
        exit_action = QAction(self.tr("退出(&X)"), self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setStatusTip(self.tr("退出应用程序"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 查看菜单
        view_menu = menubar.addMenu(self.tr("查看(&V)"))
        
        # 显示/隐藏面板
        self.toggle_series_panel_action = QAction(self.tr("显示/隐藏序列面板"), self)
        self.toggle_series_panel_action.setShortcut("F1")
        self.toggle_series_panel_action.setCheckable(True)
        self.toggle_series_panel_action.setChecked(True)
        self.toggle_series_panel_action.toggled.connect(self._toggle_series_panel)
        view_menu.addAction(self.toggle_series_panel_action)
        
        self.toggle_info_panel_action = QAction(self.tr("显示/隐藏信息面板"), self)
        self.toggle_info_panel_action.setShortcut("F2")
        self.toggle_info_panel_action.setCheckable(True)
        self.toggle_info_panel_action.setChecked(False)
        self.toggle_info_panel_action.toggled.connect(self._toggle_info_panel)
        view_menu.addAction(self.toggle_info_panel_action)
        
        # 序列菜单
        series_menu = menubar.addMenu(self.tr("序列(&S)"))
        
        # 绑定策略
        binding_strategy_menu = series_menu.addMenu(self.tr("绑定策略"))
        
        self._binding_strategy_group = QActionGroup(self)
        strategy_actions = [
            (self.tr("自动分配"), BindingStrategy.AUTO_ASSIGN),
            (self.tr("保持现有"), BindingStrategy.PRESERVE_EXISTING),
            (self.tr("替换最旧"), BindingStrategy.REPLACE_OLDEST),
            (self.tr("询问用户"), BindingStrategy.ASK_USER)
        ]
        
        for strategy_name, strategy in strategy_actions:
            action = QAction(strategy_name, self)
            action.setCheckable(True)
            if strategy == BindingStrategy.AUTO_ASSIGN:
                action.setChecked(True)
            action.triggered.connect(lambda checked, s=strategy: self._set_binding_strategy(s))
            self._binding_strategy_group.addAction(action)
            binding_strategy_menu.addAction(action)
        
        series_menu.addSeparator()
        
        # 自动分配序列
        auto_assign_action = QAction(self.tr("自动分配所有序列"), self)
        auto_assign_action.setShortcut("Ctrl+A")
        auto_assign_action.triggered.connect(self._auto_assign_all_series)
        series_menu.addAction(auto_assign_action)
        
        # 清除所有绑定
        clear_bindings_action = QAction(self.tr("清除所有绑定"), self)
        clear_bindings_action.triggered.connect(self._clear_all_bindings)
        series_menu.addAction(clear_bindings_action)
        
        # 窗位菜单
        wl_menu = menubar.addMenu(self.tr("窗位(&W)"))
        
        # 预设窗位
        presets: List[Tuple[str, Tuple[int, int]]] = [
            (self.tr("自动"), (-1, -1)),
            (self.tr("腹部"), (400, 50)),
            (self.tr("脑窗"), (80, 40)),
            (self.tr("骨窗"), (2000, 600)),
            (self.tr("肺窗"), (1500, -600)),
            (self.tr("纵隔"), (350, 50)),
        ]
        
        for name, (width, level) in presets:
            action = QAction(name, self)
            action.setStatusTip(self.tr("设置为 %1: W:%2 L:%3").replace("%1", name).replace("%2", str(width)).replace("%3", str(level)))
            action.triggered.connect(
                lambda checked=False, w=width, l=level: self._set_window_level_preset(w, l)
            )
            wl_menu.addAction(action)
        
        wl_menu.addSeparator()
        
        custom_wl_action = QAction(self.tr("自定义"), self)
        custom_wl_action.setStatusTip(self.tr("手动设置窗宽和窗位"))
        custom_wl_action.triggered.connect(self._open_custom_wl_dialog)
        wl_menu.addAction(custom_wl_action)
        

        
        # 工具菜单
        tools_menu = menubar.addMenu(self.tr("工具(&T)"))
        
        # 设置
        settings_action = QAction(self.tr("设置(&S)"), self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.setStatusTip(self.tr("打开设置对话框"))
        settings_action.triggered.connect(self._open_settings_dialog)
        tools_menu.addAction(settings_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu(self.tr("帮助(&H)"))
        
        about_action = QAction(self.tr("关于"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
        logger.debug("[MainWindow._init_menus] 主窗口菜单初始化完成")
    
    def _init_toolbars(self) -> None:
        """初始化工具栏"""
        logger.debug("[MainWindow._init_toolbars] 初始化主窗口工具栏")
        
        # 使用统一的主工具栏创建函数（包含所有工具和按钮）
        from medimager.ui.main_toolbar import create_main_toolbar
        main_toolbar = create_main_toolbar(self)
        self.addToolBar(main_toolbar)
        
        # 获取同步按钮的引用（工具栏创建时已添加）
        for widget in main_toolbar.children():
            if hasattr(widget, 'set_sync_states'):
                self._sync_button = widget
                break
        
        logger.debug("[MainWindow._init_toolbars] 主窗口工具栏初始化完成")
    
    def _init_default_tool(self) -> None:
        """初始化默认工具"""
        logger.debug("[MainWindow._init_default_tool] 初始化默认工具")
        self._current_tool = 'default'
        self.current_tool = DefaultTool(None)  # 稍后会传播到各个视图
        logger.debug("[MainWindow._init_default_tool] 默认工具初始化完成")
    
    def _on_tool_selected(self, tool_name: str) -> None:
        """处理工具选择事件"""
        logger.debug(f"[MainWindow._on_tool_selected] 工具选择: {tool_name}")
        
        # 保存当前工具状态
        self._current_tool = tool_name
        
        # 创建对应的工具实例
        self.current_tool = self._create_tool_instance(tool_name)
        
        # 传播工具到所有视图
        self._propagate_tool_to_viewers()
        
        logger.info(f"[MainWindow._on_tool_selected] 工具切换完成: {tool_name}")
    
    def _propagate_tool_to_viewers(self) -> None:
        """将当前工具传播到所有ImageViewer"""
        logger.info("[MainWindow._propagate_tool_to_viewers] 传播工具到视图")
        
        try:
            # 获取所有视图框架
            view_frames = self.multi_viewer_grid.get_all_view_frames()
            logger.info(f"[MainWindow._propagate_tool_to_viewers] 发现视图框架数量: {len(view_frames)}")
            
            for view_id, view_frame in view_frames.items():
                if view_frame and view_frame.image_viewer:
                    # 为每个ImageViewer创建独立的工具实例
                    tool_copy = self._create_tool_copy(view_frame.image_viewer)
                    if tool_copy:
                        view_frame.image_viewer.set_tool(tool_copy)
                        logger.info(f"[MainWindow._propagate_tool_to_viewers] 工具已传播到视图: {view_id}, 工具类型: {type(tool_copy).__name__}")
                    else:
                        logger.warning(f"[MainWindow._propagate_tool_to_viewers] 工具副本创建失败: {view_id}")
                else:
                    logger.warning(f"[MainWindow._propagate_tool_to_viewers] 视图框架或ImageViewer为空: {view_id}")
            
            logger.info(f"[MainWindow._propagate_tool_to_viewers] 工具传播完成: 影响了{len(view_frames)}个视图")
            
        except Exception as e:
            logger.error(f"[MainWindow._propagate_tool_to_viewers] 工具传播失败: {e}", exc_info=True)
    
    def _create_tool_instance(self, tool_name: str):
        """根据工具名称创建工具实例"""
        from medimager.ui.tools.default_tool import DefaultTool
        from medimager.ui.tools.roi_tool import EllipseROITool, RectangleROITool, CircleROITool
        from medimager.ui.tools.measurement_tool import MeasurementTool
        
        tool_map = {
            'default': DefaultTool,
            'ellipse_roi': EllipseROITool,
            'rectangle_roi': RectangleROITool,
            'circle_roi': CircleROITool,
            'measurement': MeasurementTool
        }
        
        tool_class = tool_map.get(tool_name, DefaultTool)
        return tool_class(None)  # 临时创建，稍后会为每个viewer创建副本
    
    def _create_tool_copy(self, image_viewer) -> Optional:
        """为指定的ImageViewer创建工具副本"""
        try:
            if self.current_tool:
                tool_class = type(self.current_tool)
                return tool_class(image_viewer)
            return None
        except Exception as e:
            logger.error(f"[MainWindow._create_tool_copy] 创建工具副本失败: {e}", exc_info=True)
            return None
    
    def _propagate_tool_to_single_viewer(self, view_id: str) -> None:
        """将当前工具传播到指定的视图"""
        logger.debug(f"[MainWindow._propagate_tool_to_single_viewer] 传播工具到视图: {view_id}")
        
        try:
            view_frame = self.multi_viewer_grid.get_view_frame(view_id)
            if view_frame and view_frame.image_viewer:
                tool_copy = self._create_tool_copy(view_frame.image_viewer)
                if tool_copy:
                    view_frame.image_viewer.set_tool(tool_copy)
                    logger.debug(f"[MainWindow._propagate_tool_to_single_viewer] 工具已传播到视图: {view_id}")
                    
        except Exception as e:
            logger.error(f"[MainWindow._propagate_tool_to_single_viewer] 单个视图工具传播失败: {e}", exc_info=True)
    
    def _init_statusbar(self) -> None:
        """初始化状态栏"""
        logger.debug("[MainWindow._init_statusbar] 初始化主窗口状态栏")
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 序列计数标签
        self.series_count_label = QLabel(self.tr("序列: 0"))
        self.status_bar.addWidget(self.series_count_label)
        
        # 视图信息标签
        self.view_info_label = QLabel(self.tr("布局: 1×1"))
        self.status_bar.addWidget(self.view_info_label)
        
        # 活动视图标签
        self.active_view_label = QLabel(self.tr("活动视图: --"))
        self.status_bar.addWidget(self.active_view_label)
        
        # 加载进度条
        self.loading_progress = QProgressBar()
        self.loading_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.loading_progress)
        
        # 准备状态
        self.status_bar.showMessage(self.tr("准备就绪"))
        
        logger.debug("[MainWindow._init_statusbar] 主窗口状态栏初始化完成")
    
    def _update_ui_state(self) -> None:
        """更新UI状态"""
        series_count = self.series_manager.get_series_count()
        layout = self.series_manager.get_current_layout()
        
        # 更新状态栏
        self.series_count_label.setText(self.tr("序列: %1").replace("%1", str(series_count)))
        self.view_info_label.setText(self.tr("布局: %1×%2").replace("%1", str(layout[0])).replace("%2", str(layout[1])))
        
        # 更新菜单和工具栏状态
        has_series = series_count > 0
        # 可以在这里添加菜单项的启用/禁用逻辑
    
    def _toggle_series_panel(self, checked: bool) -> None:
        """切换序列面板显示状态"""
        logger.debug(f"[MainWindow._toggle_series_panel] 切换序列面板: {checked}")
        self.series_panel.setVisible(checked)
        # 同步左侧切换条箭头方向
        if hasattr(self, 'left_toggle_strip'):
            self.left_toggle_strip.set_panel_visible(checked)

    def _on_left_toggle_strip_clicked(self, visible: bool) -> None:
        """处理左侧切换条点击事件"""
        logger.debug(f"[MainWindow._on_left_toggle_strip_clicked] 左侧切换条点击: {visible}")
        self.series_panel.setVisible(visible)
        # 同步菜单中的勾选状态
        if hasattr(self, 'toggle_series_panel_action'):
            self.toggle_series_panel_action.blockSignals(True)
            self.toggle_series_panel_action.setChecked(visible)
            self.toggle_series_panel_action.blockSignals(False)
    
    def _toggle_info_panel(self, checked: bool) -> None:
        """切换信息面板显示状态"""
        logger.debug(f"[MainWindow._toggle_info_panel] 切换信息面板: {checked}")
        self.dicom_tag_panel.setVisible(checked)
        # 同步切换条箭头方向
        if hasattr(self, 'panel_toggle_strip'):
            self.panel_toggle_strip.set_panel_visible(checked)

    def _on_toggle_strip_clicked(self, visible: bool) -> None:
        """处理切换条点击事件"""
        logger.debug(f"[MainWindow._on_toggle_strip_clicked] 切换条点击: {visible}")
        self.dicom_tag_panel.setVisible(visible)
        # 同步菜单中的勾选状态
        if hasattr(self, 'toggle_info_panel_action'):
            self.toggle_info_panel_action.blockSignals(True)
            self.toggle_info_panel_action.setChecked(visible)
            self.toggle_info_panel_action.blockSignals(False)
    
    def _set_layout(self, layout_config: tuple) -> None:
        """设置视图布局"""
        logger.debug(f"[MainWindow._set_layout] 设置布局: {layout_config}")

        try:
            # 标记正在设置布局，阻止 _on_layout_changed 的干扰
            self._setting_layout = True

            # 检查是否为规则网格布局
            if isinstance(layout_config, tuple) and len(layout_config) == 2:
                rows, cols = layout_config

                # 阻止 MultiViewerGrid._on_layout_changed 的重复重建
                self.multi_viewer_grid._rebuilding = True

                # 设置序列管理器布局（会重新配置视图绑定）
                success = self.series_manager.set_layout(rows, cols)

                if success:
                    # 设置多视图网格布局（会清空并重建视图框架）
                    grid_success = self.multi_viewer_grid.set_layout(rows, cols)
                    if grid_success:
                        logger.info(f"[MainWindow._set_layout] 规则网格布局设置成功: {rows}×{cols}")
                    else:
                        logger.error(f"[MainWindow._set_layout] 多视图网格布局设置失败: {rows}×{cols}")
                else:
                    logger.error(f"[MainWindow._set_layout] 序列管理器布局设置失败: {rows}×{cols}")
            elif isinstance(layout_config, dict):
                # 特殊布局：使用多视图网格的特殊布局功能
                layout_type = layout_config.get('type', '')

                # 阻止信号触发重复重建
                self.multi_viewer_grid._rebuilding = True

                # 先通知序列管理器等效网格大小
                equivalent = self.multi_viewer_grid._get_equivalent_layout(layout_config)
                self.series_manager.set_layout(equivalent[0], equivalent[1])

                # 使用多视图网格的特殊布局功能
                grid_success = self.multi_viewer_grid.set_special_layout(layout_config)
                if grid_success:
                    logger.info(f"[MainWindow._set_layout] 特殊布局设置成功: {layout_type}")
                else:
                    logger.error(f"[MainWindow._set_layout] 特殊布局设置失败: {layout_type}")
                    # 回退到默认布局
                    rows, cols = 2, 2
                    self.series_manager.set_layout(rows, cols)
                    self.multi_viewer_grid.set_layout(rows, cols)
                    logger.info(f"[MainWindow._set_layout] 回退到默认2×2网格布局")
            else:
                # 无效的布局配置
                logger.error(f"[MainWindow._set_layout] 无效的布局配置: {layout_config}")
                return

            # 更新UI状态
            self._update_ui_state()

            # 布局切换完成后传播工具到新视图
            self._propagate_tool_to_viewers()

        except Exception as e:
            logger.error(f"[MainWindow._set_layout] 设置布局失败: {e}", exc_info=True)
        finally:
            self._setting_layout = False
            self.multi_viewer_grid._rebuilding = False
    
    def _set_binding_strategy(self, strategy: BindingStrategy) -> None:
        """设置绑定策略"""
        logger.debug(f"[MainWindow._set_binding_strategy] 设置绑定策略: {strategy}")
        self.binding_manager.set_binding_strategy(strategy)
        logger.info(f"[MainWindow._set_binding_strategy] 绑定策略设置完成: {strategy}")
    
    def _auto_assign_all_series(self) -> None:
        """自动分配所有序列"""
        logger.debug("[MainWindow._auto_assign_all_series] 开始自动分配所有序列")
        
        assigned_count = self.binding_manager.auto_assign_series_to_views()
        
        self.status_bar.showMessage(self.tr("自动分配完成：分配了 %1 个序列").replace("%1", str(assigned_count)), 3000)
        logger.info(f"[MainWindow._auto_assign_all_series] 自动分配完成: {assigned_count}个序列")
    
    def _clear_all_bindings(self) -> None:
        """清除所有绑定"""
        logger.debug("[MainWindow._clear_all_bindings] 清除所有绑定")
        
        view_ids = self.series_manager.get_all_view_ids()
        cleared_count = 0
        
        for view_id in view_ids:
            if self.series_manager.unbind_series_from_view(view_id):
                cleared_count += 1
        
        self.status_bar.showMessage(self.tr("清除绑定完成：清除了 %1 个绑定").replace("%1", str(cleared_count)), 3000)
        logger.info(f"[MainWindow._clear_all_bindings] 清除绑定完成: {cleared_count}个绑定")
    
    def _set_sync_mode(self, mode) -> None:
        """设置同步模式"""
        logger.debug(f"[MainWindow._set_sync_mode] 设置同步模式: {mode}")
        self.sync_manager.set_sync_mode(mode)
        self.status_bar.showMessage(self.tr("同步模式已设置: %1").replace("%1", mode.name), 2000)
        logger.info(f"[MainWindow._set_sync_mode] 同步模式设置完成: {mode}")
    
    def _set_sync_group(self, group) -> None:
        """设置同步分组"""
        logger.debug(f"[MainWindow._set_sync_group] 设置同步分组: {group}")
        self.sync_manager.set_sync_group(group)
        self.statusBar().showMessage(
            self.tr(f"已设置同步分组"), 2000
        )

    def _on_sync_position_changed(self, mode: str) -> None:
        """位置同步模式变化处理"""
        logger.debug(f"[MainWindow._on_sync_position_changed] 位置同步模式变化: {mode}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        # 根据位置同步模式更新同步设置
        if mode == "auto":
            new_mode = current_mode | SyncMode.SLICE
            new_mode = new_mode & ~SyncMode.CROSS_REFERENCE
            status_msg = self.tr("已开启自动位置同步")
        elif mode == "manual":
            new_mode = current_mode | SyncMode.CROSS_REFERENCE
            new_mode = new_mode & ~SyncMode.SLICE
            status_msg = self.tr("已开启手动位置同步")
        else:  # "none"
            new_mode = current_mode & ~(SyncMode.SLICE | SyncMode.CROSS_REFERENCE)
            status_msg = self.tr("已关闭位置同步")
        
        self.sync_manager.set_sync_mode(new_mode)
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_position_changed] 同步模式更新: {new_mode}")

    def _on_sync_pan_changed(self, checked: bool) -> None:
        """平移同步状态变化处理"""
        logger.debug(f"[MainWindow._on_sync_pan_changed] 平移同步状态变化: {checked}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        if checked:
            new_mode = current_mode | SyncMode.ZOOM_PAN
        else:
            new_mode = current_mode & ~SyncMode.ZOOM_PAN
        
        self.sync_manager.set_sync_mode(new_mode)
        status_msg = self.tr("已开启平移同步") if checked else self.tr("已关闭平移同步")
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_pan_changed] 同步模式更新: {new_mode}")

    def _on_sync_zoom_changed(self, checked: bool) -> None:
        """缩放同步状态变化处理"""
        logger.debug(f"[MainWindow._on_sync_zoom_changed] 缩放同步状态变化: {checked}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        if checked:
            new_mode = current_mode | SyncMode.ZOOM_PAN
        else:
            new_mode = current_mode & ~SyncMode.ZOOM_PAN
        
        self.sync_manager.set_sync_mode(new_mode)
        status_msg = self.tr("已开启缩放同步") if checked else self.tr("已关闭缩放同步")
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_zoom_changed] 同步模式更新: {new_mode}")

    def _on_sync_window_level_changed(self, checked: bool) -> None:
        """窗宽窗位同步状态变化处理"""
        logger.debug(f"[MainWindow._on_sync_window_level_changed] 窗宽窗位同步状态变化: {checked}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        if checked:
            new_mode = current_mode | SyncMode.WINDOW_LEVEL
        else:
            new_mode = current_mode & ~SyncMode.WINDOW_LEVEL
        
        self.sync_manager.set_sync_mode(new_mode)
        status_msg = self.tr("已开启窗宽窗位同步") if checked else self.tr("已关闭窗宽窗位同步")
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_window_level_changed] 同步模式更新: {new_mode}")

    def _update_sync_button_states(self) -> None:
        """更新同步按钮状态"""
        logger.debug("[MainWindow._update_sync_button_states] 更新同步按钮状态")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        # 更新同步按钮状态
        if hasattr(self, '_sync_button'):
            # 确定位置同步模式
            position_mode = "none"
            if SyncMode.SLICE in current_mode:
                position_mode = "auto"
            elif SyncMode.CROSS_REFERENCE in current_mode:
                position_mode = "manual"
            
            # 设置同步状态
            self._sync_button.set_sync_states(
                position_mode=position_mode,
                pan=SyncMode.ZOOM_PAN in current_mode,
                zoom=SyncMode.ZOOM_PAN in current_mode,
                window_level=SyncMode.WINDOW_LEVEL in current_mode
            )
        
        logger.debug("[MainWindow._update_sync_button_states] 同步按钮状态更新完成")
    
    def _open_multiple_dicom_folders(self) -> None:
        """打开多个DICOM文件夹"""
        logger.debug("[MainWindow._open_multiple_dicom_folders] 打开多个DICOM文件夹")
        
        # 使用文件对话框选择多个文件夹
        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        
        if dialog.exec_() == QDialog.Accepted:
            folders = dialog.selectedFiles()
            logger.debug(f"[MainWindow._open_multiple_dicom_folders] 选择了{len(folders)}个文件夹")
            
            for folder in folders:
                self._load_dicom_folder_as_series(folder)
    
    def _open_dicom_folder(self) -> None:
        """打开DICOM文件夹"""
        logger.debug("[MainWindow._open_dicom_folder] 打开DICOM文件夹")
        
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择DICOM文件夹"),
            QDir.homePath()
        )
        
        if folder:
            self._load_dicom_folder_as_series(folder)
    
    def _load_dicom_folder_as_series(self, folder_path: str) -> None:
        """将DICOM文件夹加载为序列"""
        logger.debug(f"[MainWindow._load_dicom_folder_as_series] 加载DICOM文件夹: {folder_path}")
        
        try:
            # 扫描文件夹中的DICOM文件
            dicom_files = []
            folder = Path(folder_path)
            
            for file_path in folder.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in ['.dcm', '.dicom', '']:
                    dicom_files.append(str(file_path))
            
            if not dicom_files:
                QMessageBox.warning(self, self.tr("警告"), self.tr("文件夹中没有找到DICOM文件"))
                return
            
            # 使用DicomParser解析文件获取序列信息
            temp_parser = DicomParser()
            series_groups = temp_parser._group_files_by_series(dicom_files)
            
            # 为每个序列创建SeriesInfo并添加到管理器
            for series_uid, files in series_groups.items():
                if not files:
                    continue
                
                # 读取第一个文件获取元数据
                import pydicom
                try:
                    first_ds = pydicom.dcmread(files[0], force=True)
                    
                    series_info = SeriesInfo(
                        series_id=str(uuid.uuid4()),
                        patient_name=getattr(first_ds, 'PatientName', 'Unknown Patient'),
                        patient_id=getattr(first_ds, 'PatientID', ''),
                        study_description=getattr(first_ds, 'StudyDescription', ''),
                        series_description=getattr(first_ds, 'SeriesDescription', ''),
                        modality=getattr(first_ds, 'Modality', ''),
                        acquisition_date=getattr(first_ds, 'AcquisitionDate', ''),
                        acquisition_time=getattr(first_ds, 'AcquisitionTime', ''),
                        slice_count=len(files),
                        series_number=str(getattr(first_ds, 'SeriesNumber', 0)),
                        study_instance_uid=getattr(first_ds, 'StudyInstanceUID', ''),
                        series_instance_uid=series_uid,
                        file_paths=files
                    )
                    
                    # 添加序列到管理器
                    series_id = self.series_manager.add_series(series_info)
                    
                    # 在后台线程中加载序列数据
                    self._load_series_in_background(series_id, files, series_info)
                    
                except Exception as e:
                    logger.error(f"[MainWindow._load_dicom_folder_as_series] 解析DICOM文件失败: {e}")
                    continue
            
            logger.info(f"[MainWindow._load_dicom_folder_as_series] 文件夹加载完成: {folder_path}")
            
        except Exception as e:
            logger.error(f"[MainWindow._load_dicom_folder_as_series] 加载文件夹失败: {e}", exc_info=True)
            QMessageBox.critical(self, self.tr("错误"), self.tr("加载DICOM文件夹失败: %1").replace("%1", str(e)))
    
    def _load_series_in_background(self, series_id: str, file_paths: List[str], series_info: SeriesInfo) -> None:
        """使用性能管理器的线程池在后台加载序列"""
        logger.debug(f"[MainWindow._load_series_in_background] 后台加载序列: {series_id}")

        # 获取性能管理器的线程池
        perf_manager = get_performance_manager()
        thread_pool = perf_manager.get_thread_pool()

        # 提交加载任务到线程池
        future = thread_pool.submit(_load_series_task, file_paths, series_id)
        self._loading_futures[series_id] = future

        # 使用回调 + QTimer 将结果安全地传回主线程
        def _on_done(fut):
            # 此回调在线程池线程中执行，用 QTimer.singleShot 切回主线程
            QTimer.singleShot(0, lambda: self._on_series_loading_finished(series_id, fut))

        future.add_done_callback(_on_done)

        # 显示加载进度
        self.loading_progress.setVisible(True)
        self.status_bar.showMessage(self.tr("正在加载序列: %1").replace("%1", series_info.series_description or series_id))

    def _on_series_loading_finished(self, series_id: str, future) -> None:
        """处理序列加载完成（在主线程中执行）"""
        logger.debug(f"[MainWindow._on_series_loading_finished] 序列加载完成: {series_id}")

        try:
            result: _SeriesLoadResult = future.result()

            if result.success and result.image_model:
                # 将图像模型添加到管理器
                success = self.series_manager.load_series_data(series_id, result.image_model)

                if success:
                    logger.info(f"[MainWindow._on_series_loading_finished] 序列数据加载成功: {series_id}")
                else:
                    logger.error(f"[MainWindow._on_series_loading_finished] 序列数据加载失败: {series_id}")
            else:
                logger.error(f"[MainWindow._on_series_loading_finished] 序列加载失败: {series_id}")

            # 清理 future 引用
            self._loading_futures.pop(series_id, None)

            # 如果没有正在加载的序列，隐藏进度条
            if not self._loading_futures:
                self.loading_progress.setVisible(False)
                self.status_bar.showMessage(self.tr("加载完成"), 2000)

        except Exception as e:
            logger.error(f"[MainWindow._on_series_loading_finished] 处理加载完成失败: {e}", exc_info=True)
            self._loading_futures.pop(series_id, None)
    
    def _open_image_file(self) -> None:
        """打开图像文件"""
        logger.debug("[MainWindow._open_image_file] 打开图像文件")
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("打开图像文件"),
            QDir.homePath(),
            self.tr("所有支持的文件 (*.dcm *.dicom *.png *.jpg *.jpeg *.bmp *.npy);;DICOM文件 (*.dcm *.dicom);;图像文件 (*.png *.jpg *.jpeg *.bmp);;NumPy文件 (*.npy)")
        )
        
        if file_path:
            self._load_single_image_file(file_path)
    
    def _load_single_image_file(self, file_path: str) -> None:
        """加载单个图像文件"""
        logger.debug(f"[MainWindow._load_single_image_file] 加载图像文件: {file_path}")
        
        try:
            # 创建图像数据模型
            image_model = ImageDataModel()
            
            # 根据文件扩展名选择加载方法
            path = Path(file_path)
            if path.suffix.lower() in ['.dcm', '.dicom']:
                success = image_model.load_dicom_series([file_path])
            elif path.suffix.lower() == '.npy':
                # 加载NumPy文件
                data = np.load(file_path)
                success = image_model.load_single_image(data)
            else:
                # 加载其他图像格式（使用PIL或其他库）
                try:
                    from PIL import Image
                    img = Image.open(file_path)
                    data = np.array(img)
                    success = image_model.load_single_image(data)
                except ImportError:
                    logger.error("PIL库未安装，无法加载图像文件")
                    success = False
            
            if success:
                # 创建序列信息
                series_info = SeriesInfo(
                    series_id=str(uuid.uuid4()),
                    patient_name=self.tr("Single Image"),
                    series_description=path.name,
                    modality="IMG",
                    series_number="1",
                    slice_count=1,
                    file_paths=[file_path]
                )
                
                # 添加到管理器
                series_id = self.series_manager.add_series(series_info)
                self.series_manager.load_series_data(series_id, image_model)
                
                logger.info(f"[MainWindow._load_single_image_file] 图像文件加载成功: {file_path}")
            else:
                logger.error(f"[MainWindow._load_single_image_file] 图像文件加载失败: {file_path}")
                QMessageBox.critical(self, self.tr("错误"), self.tr("无法加载图像文件"))
                
        except Exception as e:
            logger.error(f"[MainWindow._load_single_image_file] 加载图像文件异常: {e}", exc_info=True)
            QMessageBox.critical(self, self.tr("错误"), self.tr("加载图像文件失败: %1").replace("%1", str(e)))
    
    def _load_test_series(self) -> None:
        """加载测试序列"""
        logger.debug("[MainWindow._load_test_series] 加载测试序列")
        
        try:
            from medimager.utils.resource_path import get_test_data_path, verify_resource_exists
            
            # 检查测试数据是否存在
            test_data_path = Path(get_test_data_path("dcm"))
            if not verify_resource_exists(str(test_data_path)):
                QMessageBox.information(self, self.tr("信息"), self.tr("测试数据不存在"))
                return
            
            # 加载所有测试序列
            for series_folder in test_data_path.iterdir():
                if series_folder.is_dir():
                    self._load_dicom_folder_as_series(str(series_folder))
            
            logger.info("[MainWindow._load_test_series] 测试序列加载完成")
            
        except Exception as e:
            logger.error(f"[MainWindow._load_test_series] 加载测试序列失败: {e}", exc_info=True)
    
    def _set_window_level_preset(self, width: int, level: int) -> None:
        """设置窗宽窗位预设"""
        logger.debug(f"[MainWindow._set_window_level_preset] 设置窗宽窗位: W:{width} L:{level}")
        
        # 获取活动视图的图像模型
        active_view_id = self.series_manager.get_active_view_id()
        if not active_view_id:
            return
        
        binding = self.series_manager.get_view_binding(active_view_id)
        if not binding or not binding.series_id:
            return
        
        image_model = self.series_manager.get_series_model(binding.series_id)
        if image_model:
            if width == -1 and level == -1:
                # 自动窗位
                image_model._set_default_window_level()
            else:
                image_model.set_window(width, level)
            
            logger.info(f"[MainWindow._set_window_level_preset] 窗宽窗位设置完成: W:{width} L:{level}")
    
    def _open_custom_wl_dialog(self) -> None:
        """打开自定义窗宽窗位对话框"""
        logger.debug("[MainWindow._open_custom_wl_dialog] 打开自定义窗宽窗位对话框")
        
        # 获取当前活动视图的窗宽窗位
        active_view_id = self.series_manager.get_active_view_id()
        current_width, current_level = 400, 40
        
        if active_view_id:
            binding = self.series_manager.get_view_binding(active_view_id)
            if binding and binding.series_id:
                image_model = self.series_manager.get_series_model(binding.series_id)
                if image_model:
                    current_width = image_model.window_width
                    current_level = image_model.window_level
        
        dialog = CustomWLDialog(current_width, current_level, self)
        
        if dialog.exec_() == QDialog.Accepted:
            new_width, new_level = dialog.get_values()
            self._set_window_level_preset(new_width, new_level)
    
    def _open_settings_dialog(self) -> None:
        """打开设置对话框"""
        logger.debug("[MainWindow._open_settings_dialog] 打开设置对话框")

        dialog = SettingsDialog(self.settings_manager, self)

        if dialog.exec_() == QDialog.Accepted:
            # 应用新设置 - 使用set_theme确保发出信号
            current_theme = self.theme_manager.get_current_theme()
            self.theme_manager.set_theme(current_theme)

            # 如果语言发生了变化，提示用户部分界面需要重启才能完全生效
            if getattr(dialog, '_language_changed', False):
                QMessageBox.information(
                    self,
                    self.tr("语言设置"),
                    self.tr("语言已切换。部分界面文本将在重启后完全更新。")
                )

            logger.info("[MainWindow._open_settings_dialog] 设置更新完成")
    
    def _show_about(self) -> None:
        """显示关于对话框"""
        QMessageBox.about(
            self,
            self.tr("关于 MedImager Pro"),
            self.tr("""<h3>MedImager Pro</h3>
            <p>多序列DICOM查看器与图像分析工具</p>
            <p>版本: 2.0.0</p>
            <p>支持多序列加载、多视图布局和高级图像分析功能。</p>
            """)
        )
    
    # 信号处理方法
    
    def _on_series_added(self, series_id: str) -> None:
        """处理序列添加事件"""
        logger.debug(f"[MainWindow._on_series_added] 序列添加: {series_id}")
        self._update_ui_state()
    
    def _on_series_loaded(self, series_id: str) -> None:
        """处理序列加载事件"""
        logger.debug(f"[MainWindow._on_series_loaded] 序列加载: {series_id}")
        # 序列加载完成后可以进行自动分配
        if self.binding_manager.get_binding_strategy() == BindingStrategy.AUTO_ASSIGN:
            self.binding_manager.auto_assign_series_to_views([series_id])
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[MainWindow._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")
        
        # 如果绑定的是活动视图，更新DICOM标签面板
        active_view_id = self.series_manager.get_active_view_id()
        if view_id == active_view_id and series_id:
            image_model = self.series_manager.get_series_model(series_id)
            if image_model and image_model.has_image() and image_model.is_dicom():
                # 获取当前切片的DICOM数据
                dicom_dataset = image_model.get_dicom_file(image_model.current_slice_index)
                self.dicom_tag_panel.update_tags(dicom_dataset)
        
        # 当新视图绑定序列时，传播工具到该视图
        if series_id:  # 绑定了序列
            self._propagate_tool_to_single_viewer(view_id)
    
    def _on_layout_changed(self, layout: tuple) -> None:
        """处理布局变更事件

        当 _setting_layout 为 True 时，说明 _set_layout() 正在主动执行布局切换，
        此处不应再做任何干扰操作（如清除绑定），否则会破坏 _set_layout 的流程。
        """
        if getattr(self, '_setting_layout', False):
            logger.debug(f"[MainWindow._on_layout_changed] _setting_layout=True, 跳过: {layout}")
            return

        logger.debug(f"[MainWindow._on_layout_changed] 布局变更: {layout}")
        self._update_ui_state()
    
    def _on_auto_assignment_completed(self, assigned_count: int) -> None:
        """处理自动分配完成事件"""
        logger.debug(f"[MainWindow._on_auto_assignment_completed] 自动分配完成: {assigned_count}")
        self.status_bar.showMessage(self.tr("自动分配完成：分配了 %1 个序列").replace("%1", str(assigned_count)), 3000)
        
        # 激活第一个有绑定的视图，确保切片信号正确连接
        if assigned_count > 0:
            first_bound_view = self.binding_manager.get_first_bound_view()
            if first_bound_view:
                logger.debug(f"[MainWindow._on_auto_assignment_completed] 激活第一个有绑定的视图: {first_bound_view}")
                # 直接调用激活处理程序，而不是依赖信号链，这在初始设置期间更稳定
                self._on_view_activated(first_bound_view)
    
    def _on_series_selected(self, series_id: str) -> None:
        """处理序列选择事件"""
        logger.debug(f"[MainWindow._on_series_selected] 序列选择: {series_id}")
        
        # 更新DICOM标签面板
        image_model = self.series_manager.get_series_model(series_id)
        if image_model and image_model.has_image() and image_model.is_dicom():
            # 获取第一个DICOM文件的dataset
            dicom_dataset = image_model.get_dicom_file(0)
            self.dicom_tag_panel.update_tags(dicom_dataset)
        else:
            self.dicom_tag_panel.clear()
    
    def _on_binding_requested(self, view_id: str, series_id: str) -> None:
        """处理绑定请求事件"""
        logger.debug(f"[MainWindow._on_binding_requested] 绑定请求: view_id={view_id}, series_id={series_id}")
        
        success = self.series_manager.bind_series_to_view(view_id, series_id)
        if success:
            logger.info(f"[MainWindow._on_binding_requested] 绑定成功: {view_id} -> {series_id}")
        else:
            logger.warning(f"[MainWindow._on_binding_requested] 绑定失败: {view_id} -> {series_id}")
    
    def _on_view_activated(self, view_id: str) -> None:
        """处理视图激活事件（合并了活动视图变化的处理逻辑）"""
        logger.debug(f"[MainWindow._on_view_activated] 视图激活: {view_id}")
        
        # 核心逻辑：确保数据模型中的活动视图ID与当前激活的ID同步
        # 这是为了统一处理来自UI点击和程序化设置的事件
        if self.series_manager.get_active_view_id() != view_id:
            # 更新模型。这将触发 active_view_changed 信号，
            # 该信号会再次调用此方法。上面的检查可防止无限递归。
            self.series_manager.set_active_view(view_id)
            # 必须在此处返回，以避免在第一次进入时执行下面的信号连接逻辑，
            # 真正的连接逻辑将在信号触发的第二次调用中执行。
            return
        
        # 更新状态栏
        binding = self.series_manager.get_view_binding(view_id)
        if binding:
            pos_text = f"{binding.position.value[0]+1}-{binding.position.value[1]+1}"
            self.active_view_label.setText(self.tr("活动视图: %1").replace("%1", pos_text))
        
        # 断开之前的连接（如果有的话）
        if hasattr(self, '_current_active_model'):
            try:
                self._current_active_model.slice_changed.disconnect(self._on_slice_changed)
            except:
                pass  # 忽略断开连接的错误
        
        # 更新DICOM标签面板并连接切片变化信号
        if binding and binding.series_id:
            image_model = self.series_manager.get_series_model(binding.series_id)
            if image_model and image_model.has_image():
                # 连接切片变化信号
                image_model.slice_changed.connect(self._on_slice_changed)
                self._current_active_model = image_model
                
                if image_model.is_dicom():
                    # 获取当前切片的DICOM数据
                    dicom_dataset = image_model.get_dicom_file(image_model.current_slice_index)
                    self.dicom_tag_panel.update_tags(dicom_dataset)
                else:
                    self.dicom_tag_panel.clear()
                
                # 同步序列面板切片选择
                if hasattr(self.series_panel, 'sync_slice_selection'):
                    self.series_panel.sync_slice_selection(binding.series_id, image_model.current_slice_index)
                    
                logger.debug(f"[MainWindow._on_view_activated] 切片信号连接成功: {binding.series_id}")
            else:
                self._current_active_model = None
                self.dicom_tag_panel.clear()
        else:
            self._current_active_model = None
            self.dicom_tag_panel.clear()
    
    def _on_grid_layout_changed(self, layout: tuple) -> None:
        """处理网格布局变更事件"""
        logger.debug(f"[MainWindow._on_grid_layout_changed] 网格布局变更: {layout}")
        # 这个信号来自MultiViewerGrid，通常不需要额外处理
        pass
    
    def _on_sync_mode_changed(self, mode) -> None:
        """处理同步模式变更事件"""
        logger.debug(f"[MainWindow._on_sync_mode_changed] 同步模式变更: {mode}")
        
        # 更新工具栏按钮状态
        self._update_sync_button_states()
        logger.info(f"[MainWindow._on_sync_mode_changed] 同步模式已更新: {mode}")
    
    def _on_sync_group_changed(self, group) -> None:
        """处理同步分组变更事件"""
        logger.debug(f"[MainWindow._on_sync_group_changed] 同步分组变更: {group}")

        # 更新下拉框选择状态（如果存在）
        if hasattr(self, '_sync_group_combo') and self._sync_group_combo:
            for i in range(self._sync_group_combo.count()):
                if self._sync_group_combo.itemData(i) == group:
                    self._sync_group_combo.blockSignals(True)
                    self._sync_group_combo.setCurrentIndex(i)
                    self._sync_group_combo.blockSignals(False)
                    break

        logger.info(f"[MainWindow._on_sync_group_changed] 同步分组已更新: {group}")
    

    
    def _on_slice_changed(self, slice_index: int) -> None:
        """处理切片变化事件（合并了所有切片变化相关的处理逻辑）"""
        logger.debug(f"[MainWindow._on_slice_changed] 切片变化: {slice_index}")
        
        try:
            # 更新DICOM标签面板
            if hasattr(self, '_current_active_model') and self._current_active_model:
                if self._current_active_model.is_dicom():
                    dicom_dataset = self._current_active_model.get_dicom_file(slice_index)
                    self.dicom_tag_panel.update_tags(dicom_dataset)
                    logger.debug(f"[MainWindow._on_slice_changed] DICOM标签面板已更新: 切片{slice_index}")
            
            # 同步序列面板切片选择
            active_view_id = self.series_manager.get_active_view_id()
            if active_view_id:
                binding = self.series_manager.get_view_binding(active_view_id)
                if binding and binding.series_id:
                    # 调用序列面板的同步方法
                    if hasattr(self.series_panel, 'sync_slice_selection'):
                        self.series_panel.sync_slice_selection(binding.series_id, slice_index)
                    
        except Exception as e:
            logger.error(f"[MainWindow._on_slice_changed] 处理切片变化失败: {e}", exc_info=True)
    
    def contextMenuEvent(self, event) -> None:
        """禁用主窗口的右键菜单，特别是工具栏右键菜单"""
        # 完全忽略右键菜单事件，防止显示工具栏的上下文菜单
        event.ignore()
    
    def closeEvent(self, event) -> None:
        """处理窗口关闭事件"""
        logger.debug("[MainWindow.closeEvent] 处理窗口关闭事件")
        
        try:
            # 取消所有正在进行的加载任务
            for future in self._loading_futures.values():
                future.cancel()
            self._loading_futures.clear()
            
            # 保存设置
            self.settings_manager.save_settings()
            
            logger.info("[MainWindow.closeEvent] 应用程序正常关闭")
            event.accept()
            
        except Exception as e:
            logger.error(f"[MainWindow.closeEvent] 关闭时发生错误: {e}", exc_info=True)
            event.accept()  # 即使出错也允许关闭