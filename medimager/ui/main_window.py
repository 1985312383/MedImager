#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MedImager 主程序窗口
包含主窗口布局、菜单栏和工具栏
"""
import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QLabel, QStatusBar, QFileDialog, QMessageBox, QDialog
)
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QAction, QImage, QKeySequence, QIcon, QActionGroup
from typing import Optional, List, Tuple
import os
from pathlib import Path

from medimager.ui.image_viewer import ImageViewer
from medimager.core.image_data_model import ImageDataModel
from medimager.ui.panels.series_panel import SeriesPanel
from medimager.ui.panels.dicom_tag_panel import DicomTagPanel
from medimager.ui.dialogs.custom_wl_dialog import CustomWLDialog
from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.utils.logger import get_logger
from medimager.utils.settings import SettingsManager
from medimager.utils.theme_manager import ThemeManager
from medimager.ui.tools.default_tool import DefaultTool
from medimager.ui.tools.roi_tool import EllipseROITool, RectangleROITool, CircleROITool
from medimager.ui.main_toolbar import create_main_toolbar


class MainWindow(QMainWindow):
    """应用程序主窗口"""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化主窗口"""
        super().__init__(parent)
        self.logger = get_logger(__name__)
        
        # 初始化设置管理器和主题管理器
        self.settings_manager = SettingsManager()
        self.theme_manager = ThemeManager(self.settings_manager, self)
        
        # 初始化数据模型
        self.image_data_model = ImageDataModel()
        
        # 初始化UI
        self._init_ui()
        
        # 连接信号和槽
        self._connect_signals()
        
        # 应用当前主题
        self.theme_manager.apply_current_theme()
        
        # 根据初始状态更新UI
        self._update_ui_state()
        
    def _init_ui(self) -> None:
        """初始化用户界面"""
        self.setGeometry(100, 100, 1600, 900)
        self.setWindowTitle(self.tr("MedImager - DICOM 查看器与图像分析工具"))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)

        # 左侧序列面板
        self.series_panel = SeriesPanel()
        self.series_panel.setMinimumWidth(150)
        main_splitter.addWidget(self.series_panel)

        # 中央图像查看器
        self.image_viewer = ImageViewer()
        main_splitter.addWidget(self.image_viewer)

        # 右侧信息面板
        self.dicom_tag_panel = DicomTagPanel()
        self.dicom_tag_panel.setMinimumWidth(200)
        main_splitter.addWidget(self.dicom_tag_panel)
        
        # 默认隐藏右侧面板
        self.dicom_tag_panel.hide()
        
        # 允许子控件被折叠到零尺寸
        main_splitter.setChildrenCollapsible(True)

        # 使用拉伸因子来设置自适应比例
        main_splitter.setStretchFactor(1, 1) # 让中央图像查看器占据主要空间
        
        self._init_menus()
        self._init_toolbars()
        self._init_statusbar()

    def _connect_signals(self) -> None:
        """连接所有信号和槽"""
        # 将模型与视图关联
        self.image_viewer.set_model(self.image_data_model)
        
        # 模型信号
        self.image_data_model.image_loaded.connect(self._on_image_loaded)
        self.image_data_model.image_loaded.connect(self._update_ui_state)
        self.image_data_model.data_changed.connect(self._update_viewer)
        self.image_data_model.data_changed.connect(self._update_ui_state)
        self.image_data_model.slice_changed.connect(self._on_slice_changed)
        self.image_data_model.roi_added.connect(self.image_viewer.scene.update) # ROI 添加后更新场景
        
        # 视图信号
        self.image_viewer.pixel_value_changed.connect(self._update_status_pixel_value)
        self.image_viewer.zoom_changed.connect(self._update_status_zoom)
        self.image_viewer.cursor_left_image.connect(self._clear_pixel_value_status)

        # 面板信号
        self.series_panel.slice_selected.connect(self.image_data_model.set_current_slice)

    def _init_menus(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu(self.tr("文件(&F)"))
        
        # 打开DICOM文件夹
        open_folder_action = QAction(self.tr("打开DICOM文件夹(&D)"), self)
        open_folder_action.setShortcut(QKeySequence.Open)
        open_folder_action.setStatusTip(self.tr("打开包含DICOM序列的文件夹"))
        open_folder_action.triggered.connect(self._open_dicom_folder)
        file_menu.addAction(open_folder_action)
        
        # 打开图像文件
        open_image_action = QAction(self.tr("打开图像文件(&I)"), self)
        open_image_action.setShortcut("Ctrl+O")
        open_image_action.setStatusTip(self.tr("打开单张图像文件 (DICOM, PNG, JPG, BMP, NPY)"))
        open_image_action.triggered.connect(self._open_image_file)
        file_menu.addAction(open_image_action)
        
        file_menu.addSeparator()
        
        # 退出
        exit_action = QAction(self.tr("退出(&X)"), self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setStatusTip(self.tr("退出应用程序"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 查看菜单
        view_menu = menubar.addMenu(self.tr("查看(&V)"))
        
        # 重置视图
        reset_view_action = QAction(self.tr("重置视图(&R)"), self)
        reset_view_action.setShortcut("Ctrl+R")
        reset_view_action.setStatusTip(self.tr("重置图像查看器到默认状态"))
        view_menu.addAction(reset_view_action)
        
        view_menu.addSeparator()
        
        # 显示/隐藏面板
        self.toggle_left_panel_action = QAction(self.tr("显示/隐藏序列面板"), self)
        self.toggle_left_panel_action.setShortcut("F1")
        self.toggle_left_panel_action.setCheckable(True)
        self.toggle_left_panel_action.setChecked(True)
        self.toggle_left_panel_action.toggled.connect(self._toggle_left_panel)
        view_menu.addAction(self.toggle_left_panel_action)
        
        self.toggle_right_panel_action = QAction(self.tr("显示/隐藏信息面板"), self)
        self.toggle_right_panel_action.setShortcut("F2")
        self.toggle_right_panel_action.setCheckable(True)
        self.toggle_right_panel_action.setChecked(False)
        self.toggle_right_panel_action.toggled.connect(self._toggle_right_panel)
        view_menu.addAction(self.toggle_right_panel_action)
        
        # 窗位菜单
        wl_menu = menubar.addMenu(self.tr("窗位(&W)"))
        
        # 定义预设窗位 (描述, (窗宽, 窗位))
        presets: List[Tuple[str, Tuple[int, int]]] = [
            (self.tr("自动"), (-1, -1)), # -1 作为自动窗位的标记
            (self.tr("腹部"), (400, 50)),
            (self.tr("脑窗"), (80, 40)),
            (self.tr("骨窗"), (2000, 600)),
            (self.tr("肺窗"), (1500, -600)),
            (self.tr("纵隔"), (350, 50)),
        ]
        
        for name, (width, level) in presets:
            action = QAction(name, self)
            action.setStatusTip(self.tr(f"设置为 {name}: W:{width} L:{level}"))
            # 使用 lambda 捕获 width 和 level
            action.triggered.connect(
                lambda checked=False, w=width, l=level: self._set_window_level_preset(w, l)
            )
            wl_menu.addAction(action)

        wl_menu.addSeparator()

        custom_wl_action = QAction(self.tr("自定义"), self)
        custom_wl_action.setStatusTip(self.tr("手动设置窗宽和窗位"))
        custom_wl_action.triggered.connect(self._open_custom_wl_dialog)
        wl_menu.addAction(custom_wl_action)

        # 测试菜单
        test_menu = menubar.addMenu(self.tr("测试(&T)"))
        
        # 加载模型子菜单
        load_model_menu = test_menu.addMenu(self.tr("加载模型"))
        
        # 加载水模测试
        load_phantom_action = QAction(self.tr("加载水模"), self)
        load_phantom_action.setStatusTip(self.tr("加载用于测试的NPY格式水模图像"))
        load_phantom_action.triggered.connect(self._load_debug_phantom)
        load_model_menu.addAction(load_phantom_action)

        # 加载Gammex模体
        load_gammex_action = QAction(self.tr("加载Gammex模体"), self)
        load_gammex_action.setStatusTip(self.tr("加载用于测试的DICOM格式Gammex模体"))
        load_gammex_action.triggered.connect(self._load_gammex_phantom)
        load_model_menu.addAction(load_gammex_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu(self.tr("工具(&T)"))
        
        # 测量工具
        measurement_action = QAction(self.tr("测量工具(&M)"), self)
        measurement_action.setShortcut("M")
        measurement_action.setStatusTip(self.tr("激活测量工具"))
        tools_menu.addAction(measurement_action)
        
        # 窗宽窗位工具
        window_level_action = QAction(self.tr("窗宽窗位(&W)"), self)
        window_level_action.setShortcut("W")
        window_level_action.setStatusTip(self.tr("激活窗宽窗位调整工具"))
        tools_menu.addAction(window_level_action)
        
        # 设置菜单
        settings_menu = menubar.addMenu(self.tr("设置(&S)"))
        
        # 首选项
        preferences_action = QAction(self.tr("首选项(&P)"), self)
        preferences_action.setShortcut("Ctrl+,")
        preferences_action.setStatusTip(self.tr("打开设置对话框"))
        preferences_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(preferences_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu(self.tr("帮助(&H)"))
        
        # 关于
        about_action = QAction(self.tr("关于MedImager(&A)"), self)
        about_action.setStatusTip(self.tr("显示关于信息"))
        help_menu.addAction(about_action)
        
    def _init_toolbars(self):
        """初始化工具栏"""
        # 使用新的工具栏创建函数
        main_toolbar = create_main_toolbar(self)
        self.addToolBar(Qt.TopToolBarArea, main_toolbar)
        
        # 初始设置默认工具
        self.image_viewer.set_tool(DefaultTool(self.image_viewer))
        
    def _init_statusbar(self):
        """初始化状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 添加状态信息标签
        self.status_label = QLabel(self.tr("就绪"))
        self.status_bar.addWidget(self.status_label)
        
        # 添加鼠标位置信息（后续实现）
        self.pixel_pos_label = QLabel(self.tr("鼠标位置: (0, 0)"))
        self.status_bar.addPermanentWidget(self.pixel_pos_label)
        
        # 添加像素值信息（后续实现）
        self.pixel_value_label = QLabel(self.tr("像素值: 0.00 HU"))
        self.status_bar.addPermanentWidget(self.pixel_value_label)
        
        # 初始时隐藏像素信息
        self.pixel_pos_label.hide()
        self.pixel_value_label.hide()

        self.zoom_label = QLabel(self.tr("缩放"))
        self.status_bar.addPermanentWidget(self.zoom_label)
        
        # 添加窗宽窗位信息（后续实现）
        self.wl_label = QLabel(self.tr("窗宽: 0 L: 0"))
        self.status_bar.addPermanentWidget(self.wl_label)
        
    def _toggle_left_panel(self, checked: bool):
        """切换左侧面板的可见性"""
        self.series_panel.setVisible(checked)

    def _toggle_right_panel(self, checked: bool):
        """切换右侧面板的可见性"""
        self.dicom_tag_panel.setVisible(checked)
        
    def _update_ui_state(self) -> None:
        """根据程序当前状态（如是否加载图像）更新UI元素（如Action）的状态。"""
        has_image = self.image_data_model is not None and self.image_data_model.pixel_array is not None
        
        # 根据是否有图像来启用/禁用相关的Action
        # 使用新的工具栏系统，通过tool_actions字典访问工具动作
        if hasattr(self, 'tool_actions'):
            for tool_name, action in self.tool_actions.items():
                if tool_name in ["ellipse_roi", "rectangle_roi", "circle_roi", "measurement"]:
                    action.setEnabled(has_image)
        
        # 未来可以添加更多Action的状态管理
        # self.save_action.setEnabled(has_image)
        # self.analysis_action.setEnabled(has_image)
        
    def _on_image_loaded(self) -> None:
        """当新图像加载完成时，更新UI"""
        self.logger.info("图像加载完成信号已接收，正在更新UI...")
        self.image_viewer.clear_roi_dependent_state() # 清除旧的ROI悬停和统计框状态
        self._update_panels_on_load()
        self._update_viewer()  # 关键：更新图像显示
        self.image_viewer.fit_to_window()
        self._update_status_wl()
        # 强制更新缩放值显示
        self._update_status_zoom(self.image_viewer.transform().m11())

    def _update_viewer(self) -> None:
        """当图像数据（如窗宽窗位）变化时，更新所有相关UI元素"""
        # 1. 从模型获取原始的、未处理的显示切片
        original_slice = self.image_data_model.get_current_slice_data()
        
        if original_slice is not None:
            # 2. 应用当前的窗宽窗位设置，得到8位的显示数据
            display_slice = self.image_data_model.apply_window_level(original_slice)
            
            # 3. 将 numpy 数组转换为 QImage
            height, width = display_slice.shape
            bytes_per_line = width
            
            # 创建 QImage。注意：必须复制数据，否则当 display_slice 被垃圾回收时，
            # QImage会指向无效内存，导致崩溃或显示不正确。
            q_image = QImage(display_slice.copy().data, width, height, bytes_per_line, QImage.Format_Grayscale8)
            
            self.image_viewer.display_qimage(q_image)
        else:
            self.image_viewer.display_qimage(None) # 清空视图
            
        self._update_status_wl()

    def _update_status_pixel_value(self, x: int, y: int, value: float) -> None:
        """更新状态栏中的像素值信息"""
        self.pixel_pos_label.setText(self.tr("X: {}, Y: {}").format(x, y))
        self.pixel_value_label.setText(self.tr("像素值: {:.2f} HU").format(value))
        
        # 确保控件可见
        if not self.pixel_pos_label.isVisible():
            self.pixel_pos_label.show()
        if not self.pixel_value_label.isVisible():
            self.pixel_value_label.show()

    def _update_status_zoom(self, zoom_factor: float) -> None:
        """更新状态栏中的缩放信息"""
        self.zoom_label.setText(self.tr("缩放: {:.1%}").format(zoom_factor))
        
    def _clear_pixel_value_status(self) -> None:
        """清空状态栏中的像素位置和值信息"""
        self.pixel_pos_label.hide()
        self.pixel_value_label.hide()

    def _update_status_wl(self) -> None:
        """更新状态栏中的窗宽窗位信息"""
        ww = self.image_data_model.window_width
        wl = self.image_data_model.window_level
        self.wl_label.setText(self.tr("W: {} L: {}").format(ww, wl))

    def _on_slice_changed(self, index: int) -> None:
        """当切片变化时，更新UI"""
        self.series_panel.set_current_slice(index)
        
        # 更新DICOM标签面板以显示当前切片的元数据
        if self.image_data_model.is_dicom():
            current_dicom_file = self.image_data_model.get_dicom_file(index)
            self.dicom_tag_panel.update_tags(current_dicom_file)

    def _set_window_level_preset(self, width: int, level: int) -> None:
        """根据预设值设置窗宽窗位"""
        if self.image_data_model:
            # -1 是自动窗位的标记
            if width == -1 and level == -1:
                self.image_data_model._set_default_window_level()
            else:
                self.image_data_model.set_window(width, level)
        
    def _update_panels_on_load(self) -> None:
        """在新图像加载时，更新所有面板的内容"""
        # 如果是DICOM数据，则更新面板
        if self.image_data_model.is_dicom():
            dicom_files = self.image_data_model.dicom_files
            
            # 更新序列面板
            self.series_panel.update_series(dicom_files)
            
            # 初始显示第一个切片的标签
            if dicom_files:
                self.dicom_tag_panel.update_tags(dicom_files[0])
            else:
                self.dicom_tag_panel.clear()
            
            # 确保面板可见性正确
            if self.toggle_left_panel_action.isChecked():
                self.series_panel.show()
            if self.toggle_right_panel_action.isChecked():
                self.dicom_tag_panel.show()
        else:
            # 如果不是DICOM，则清空并隐藏
            self.series_panel.clear()
            self.dicom_tag_panel.clear()
            self.series_panel.hide()
            self.dicom_tag_panel.hide()

    def _open_dicom_folder(self) -> None:
        """打开包含DICOM文件的文件夹"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择DICOM文件夹"),
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if folder_path:
            try:
                self.logger.info(f"正在扫描DICOM文件夹: {folder_path}")
                
                # 扫描文件夹中的所有.dcm文件
                folder = Path(folder_path)
                dcm_files = []
                
                # 递归搜索所有.dcm文件
                for file_path in folder.rglob("*.dcm"):
                    dcm_files.append(str(file_path))
                
                # 如果没有找到.dcm文件，尝试查找没有扩展名的文件（某些DICOM文件没有扩展名）
                if not dcm_files:
                    self.logger.info("未找到.dcm文件，尝试检测无扩展名的DICOM文件")
                    import pydicom
                    
                    for file_path in folder.iterdir():
                        if file_path.is_file() and not file_path.suffix:
                            try:
                                # 尝试用pydicom读取，如果成功说明是DICOM文件
                                pydicom.dcmread(str(file_path), stop_before_pixels=True)
                                dcm_files.append(str(file_path))
                            except:
                                # 不是DICOM文件，跳过
                                pass
                
                if dcm_files:
                    self.logger.info(f"找到 {len(dcm_files)} 个DICOM文件")
                    self.status_label.setText(self.tr(f"正在加载 {len(dcm_files)} 个DICOM文件..."))
                    
                    # 按文件名排序
                    dcm_files.sort()
                    
                    # 加载DICOM序列
                    if self.image_data_model.load_dicom_series(dcm_files):
                        self.status_label.setText(self.tr(f"成功加载 {len(dcm_files)} 个DICOM文件"))
                    else:
                        self.status_label.setText(self.tr("DICOM加载失败"))
                        QMessageBox.warning(self, self.tr("警告"), self.tr("无法加载DICOM序列"))
                else:
                    self.logger.warning(f"在文件夹中未找到DICOM文件: {folder_path}")
                    QMessageBox.information(
                        self, 
                        self.tr("提示"), 
                        self.tr("在选定的文件夹中未找到DICOM文件")
                    )
                    
            except Exception as e:
                self.logger.error(f"打开DICOM文件夹失败: {e}")
                QMessageBox.critical(
                    self, 
                    self.tr("错误"), 
                    self.tr(f"打开DICOM文件夹时发生错误:\n{str(e)}")
                )

    def _open_image_file(self) -> None:
        """打开单张图像文件（DICOM, PNG, JPG, BMP, TIFF, NPY）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("打开图像文件"),
            "",
            self.tr("所有支持的格式 (*.dcm *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif *.npy);;DICOM文件 (*.dcm);;图像文件 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif);;NumPy数组 (*.npy);;所有文件 (*)")
        )
        
        if file_path:
            try:
                file_path = Path(file_path)
                suffix = file_path.suffix.lower()
                
                if suffix == '.dcm' or not suffix:  # DICOM文件可能没有扩展名
                    # 尝试作为DICOM文件加载
                    self.logger.info(f"正在加载DICOM文件: {file_path}")
                    if self.image_data_model.load_dicom_series([str(file_path)]):
                        self.status_label.setText(self.tr("DICOM文件加载成功"))
                    else:
                        raise Exception("DICOM文件加载失败")
                        
                elif suffix == '.npy':
                    # 加载NumPy数组
                    self.logger.info(f"正在加载NPY文件: {file_path}")
                    image_data = np.load(str(file_path))
                    if self.image_data_model.load_single_image(image_data):
                        self.status_label.setText(self.tr("NPY文件加载成功"))
                    else:
                        raise Exception("NPY文件加载失败")
                        
                elif suffix in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif']:
                    # 加载普通图像文件
                    self.logger.info(f"正在加载图像文件: {file_path}")
                    success = self._load_common_image_file(file_path)
                    if success:
                        self.status_label.setText(self.tr(f"{suffix[1:].upper()}文件加载成功"))
                    else:
                        raise Exception(f"{suffix[1:].upper()}文件加载失败")
                else:
                    raise Exception(f"不支持的文件格式: {suffix}")
                    
            except ImportError:
                self.logger.error("需要安装Pillow库来加载图像文件")
                QMessageBox.critical(
                    self, 
                    self.tr("错误"), 
                    self.tr("需要安装Pillow库来加载图像文件。\n请运行: pip install Pillow")
                )
            except Exception as e:
                self.logger.error(f"加载文件失败: {file_path}. 错误: {e}")
                QMessageBox.critical(self, self.tr("错误"), self.tr(f"无法加载此文件:\n{str(e)}"))

    def _load_common_image_file(self, file_path: Path) -> bool:
        """加载普通图像文件（PNG, JPG, BMP, TIFF等）
        
        Args:
            file_path: 图像文件路径
            
        Returns:
            bool: 是否成功加载
        """
        try:
            from PIL import Image
            
            # 使用PIL加载图像
            pil_image = Image.open(str(file_path))
            
            # 获取原始图像信息
            original_mode = pil_image.mode
            original_size = pil_image.size
            
            self.logger.info(f"图像原始信息: 模式={original_mode}, 尺寸={original_size}")
            
            # 处理不同的图像模式
            image_data = None
            color_interpretation = "MONOCHROME2"  # 默认为灰度
            
            if original_mode in ['L', 'LA']:
                # 灰度图像或带Alpha的灰度图像
                if original_mode == 'LA':
                    # 移除Alpha通道
                    pil_image = pil_image.convert('L')
                image_data = np.array(pil_image, dtype=np.float32)
                color_interpretation = "MONOCHROME2"
                
            elif original_mode in ['RGB', 'RGBA']:
                # 彩色图像
                if original_mode == 'RGBA':
                    # 移除Alpha通道或转换为RGB
                    pil_image = pil_image.convert('RGB')
                
                # 对于医学图像查看器，我们提供两种选择：
                # 1. 转换为灰度（用于医学影像分析）
                # 2. 保持彩色（用于一般图像查看）
                
                # 这里我们先转换为灰度，后续可以添加用户选择
                pil_gray = pil_image.convert('L')
                image_data = np.array(pil_gray, dtype=np.float32)
                color_interpretation = "MONOCHROME2"
                
                self.logger.info("彩色图像已转换为灰度图像")
                
            elif original_mode == 'P':
                # 调色板图像
                pil_image = pil_image.convert('RGB').convert('L')
                image_data = np.array(pil_image, dtype=np.float32)
                color_interpretation = "MONOCHROME2"
                
            elif original_mode in ['1', 'CMYK', 'YCbCr', 'LAB', 'HSV']:
                # 其他格式，统一转换为灰度
                pil_image = pil_image.convert('L')
                image_data = np.array(pil_image, dtype=np.float32)
                color_interpretation = "MONOCHROME2"
                
            else:
                self.logger.warning(f"不支持的图像模式: {original_mode}，尝试转换为灰度")
                pil_image = pil_image.convert('L')
                image_data = np.array(pil_image, dtype=np.float32)
                color_interpretation = "MONOCHROME2"
            
            if image_data is None:
                raise Exception("无法处理图像数据")
            
            # 创建详细的元数据
            metadata = {
                'Filename': file_path.name,
                'ImageType': file_path.suffix[1:].upper(),
                'Rows': image_data.shape[0],
                'Columns': image_data.shape[1],
                'OriginalImageMode': original_mode,
                'OriginalSize': original_size,
                'ColorInterpretation': color_interpretation,
                'PixelSpacing': [1.0, 1.0],  # 默认像素间距
                'SliceThickness': 1.0,
                'StudyDescription': f"Common Image File: {file_path.name}",
                'SeriesDescription': f"{file_path.suffix[1:].upper()} Image",
                'Modality': 'OT',  # Other
                'PatientName': 'N/A',
                'StudyDate': '',
                'SeriesNumber': 1,
                'InstanceNumber': 1,
                'SamplesPerPixel': 1,
                'PhotometricInterpretation': color_interpretation,
                'BitsAllocated': 32,  # 我们使用float32
                'BitsStored': 32,
                'HighBit': 31,
                'PixelRepresentation': 0,  # unsigned
                'RescaleIntercept': 0.0,
                'RescaleSlope': 1.0,
                # 窗宽窗位将由 _set_default_window_level 方法自动计算
            }
            
            self.logger.info(f"图像数据形状: {image_data.shape}")
            self.logger.info(f"像素值范围: [{np.min(image_data):.2f}, {np.max(image_data):.2f}]")
            
            # 加载到数据模型
            return self.image_data_model.load_single_image(image_data, metadata)
            
        except ImportError:
            self.logger.error("需要安装Pillow库来加载图像文件")
            raise
        except Exception as e:
            self.logger.error(f"加载普通图像文件失败: {e}")
            raise

    def _load_phantom_series(self, phantom_name: str, description: str) -> None:
        """
        加载指定名称的模体DICOM序列的通用函数。

        Args:
            phantom_name: 模体文件夹的名称 (e.g., 'water_phantom')。
            description: 用于日志和消息框的模体描述 (e.g., '水模')。
        """
        try:
            phantom_dir = Path("medimager/tests/dcm") / phantom_name
            self.logger.info(f"开始加载 {description} 序列: {phantom_dir}")

            if not phantom_dir.is_dir():
                self.logger.error(f"{description} 目录未找到: {phantom_dir}")
                QMessageBox.warning(self, self.tr("警告"), self.tr(f"{description} 目录 '{phantom_dir}' 未找到。"))
                return

            file_paths = sorted([str(p) for p in phantom_dir.glob("*.dcm")])

            if not file_paths:
                self.logger.error(f"{description} 目录中没有找到DCM文件: {phantom_dir}")
                QMessageBox.warning(self, self.tr("警告"), self.tr(f"在 {description} 目录 '{phantom_dir}' 中没有找到 .dcm 文件。"))
                return
            
            self.image_data_model.load_dicom_series(file_paths)
            self.logger.info(f"{description} 序列加载成功")

        except Exception as e:
            self.logger.error(f"加载 {description} 时出错: {e}")
            QMessageBox.critical(self, self.tr("错误"), self.tr(f"加载 {description} 时发生未知错误。"))

    def _load_debug_phantom(self) -> None:
        """加载调试用的水模DICOM序列"""
        self._load_phantom_series("water_phantom", self.tr("水模"))

    def _load_gammex_phantom(self) -> None:
        """加载 Gammex 模体 DICOM 序列"""
        self._load_phantom_series("gammex_phantom", self.tr("Gammex模体"))

    def _on_module_reloaded(self, module_name: str):
        """当模块被热重载时调用的槽函数"""
        self.logger.info(f"模块 '{module_name}' 已被热重载，正在刷新UI...")
        self.status_label.setText(self.tr(f"模块 '{module_name}' 已更新"))

    def _on_reload_failed(self, module_name: str, error: str):
        """模块热重载失败回调"""
        self.status_label.setText(self.tr(f"模块 '{module_name}' 重载失败!"))
        QMessageBox.critical(
            self,
            self.tr("热重载错误"),
            self.tr(f"模块 {module_name} 重载失败:\n\n{error}")
        )

    def _open_custom_wl_dialog(self) -> None:
        """打开自定义窗宽窗位对话框"""
        if not self.image_data_model:
            return
            
        dialog = CustomWLDialog(
            self.image_data_model.window_width,
            self.image_data_model.window_level,
            self
        )
        if dialog.exec() == QDialog.Accepted:
            width, level = dialog.get_window_level()
            self.image_data_model.set_window(width, level)

    def _open_settings_dialog(self) -> None:
        """打开设置对话框"""
        # 记录当前的语言设置
        current_language = self.settings_manager.get_setting('language', 'zh_CN')
        
        settings_dialog = SettingsDialog(self.settings_manager, self)
        
        # 使用 exec() 来等待对话框关闭
        if settings_dialog.exec():
            # 用户点击了确定按钮
            new_language = self.settings_manager.get_setting('language')
            
            # 应用主题等其他即时生效的设置
            self._apply_new_settings()
            
            # 检查语言是否发生了变化
            if new_language != current_language:
                # 询问用户是否重启应用程序
                reply = QMessageBox.question(
                    self,
                    self.tr("语言设置"),
                    self.tr("语言设置已更改。是否立即重启应用程序以应用新的语言设置？\n\n点击'是'立即重启，点击'否'稍后手动重启。"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    # 用户选择立即重启
                    self._restart_application()
                else:
                    # 用户选择稍后重启，显示提示
                    QMessageBox.information(
                        self,
                        self.tr("设置已保存"),
                        self.tr("语言设置将在下次启动时完全生效。")
                    )
            else:
                # 语言没有变化，只显示保存成功消息
                QMessageBox.information(
                    self,
                    self.tr("设置已保存"),
                    self.tr("设置已成功保存。")
                )

    def _restart_application(self) -> None:
        """重启应用程序"""
        import sys
        import os
        from PySide6.QtWidgets import QApplication
        
        # 保存当前窗口状态
        if self.settings_manager:
            self.settings_manager.set_setting(
                'window_geometry', 
                self.saveGeometry().data().hex()
            )
            self.settings_manager.set_setting(
                'window_state',
                self.saveState().data().hex()
            )
            self.settings_manager.save_settings()
        
        # 重启应用程序
        QApplication.quit()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def _apply_new_settings(self) -> None:
        """应用新的设置，此处主要处理主题等即时生效的内容"""
        self.theme_manager.apply_current_theme()
        # 注意：语言切换不再在这里处理，以避免不完整的UI刷新
        self.logger.info("新设置已应用 (主题等)")

    def _on_tool_selected(self, tool_name: str):
        """当工具栏中的工具被选中时调用"""
        tool_instance = None
        
        if tool_name == "default":
            tool_instance = DefaultTool(self.image_viewer)
        elif tool_name == "ellipse_roi":
            tool_instance = EllipseROITool(self.image_viewer)
        elif tool_name == "rectangle_roi":
            tool_instance = RectangleROITool(self.image_viewer)
        elif tool_name == "circle_roi":
            tool_instance = CircleROITool(self.image_viewer)
        elif tool_name == "measurement":
            from medimager.ui.tools.measurement_tool import MeasurementTool
            tool_instance = MeasurementTool(self.image_viewer)
        
        if tool_instance:
            self.image_viewer.set_tool(tool_instance)
            self.logger.info(f"工具已切换: {type(tool_instance).__name__}")

    def closeEvent(self, event) -> None:
        """重写关闭事件，保存窗口状态"""
        self.settings.setValue("main_window/geometry", self.saveGeometry())