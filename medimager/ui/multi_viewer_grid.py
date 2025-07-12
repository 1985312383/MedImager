"""
多视图网格组件

该模块提供动态的多视图网格布局，支持1x1到3x3的布局切换，
每个视图可以独立显示不同的DICOM序列。
"""

from typing import Dict, List, Optional, Tuple, Set, Union
from PySide6.QtWidgets import (QWidget, QGridLayout, QFrame, QVBoxLayout, 
                              QHBoxLayout, QLabel, QPushButton, QSplitter,
                              QSizePolicy, QProgressBar)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QTimer, QSize
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPixmap

from medimager.ui.image_viewer import ImageViewer
from medimager.core.multi_series_manager import MultiSeriesManager, ViewPosition, ViewBinding
from medimager.core.image_data_model import ImageDataModel
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


class ViewFrame(QFrame):
    """单个视图框架
    
    包装ImageViewer并提供视觉边框、标题栏、状态指示等功能。
    
    Signals:
        view_activated (str): 视图被激活时发出，参数为视图ID
        view_clicked (str): 视图被点击时发出，参数为视图ID
        drop_requested (str, str): 请求拖拽绑定时发出，参数为(view_id, series_id)
    """
    
    view_activated = Signal(str)
    view_clicked = Signal(str)
    drop_requested = Signal(str, str)
    
    def __init__(self, view_id: str, position: ViewPosition, parent: Optional[QWidget] = None) -> None:
        """初始化视图框架
        
        Args:
            view_id: 视图ID
            position: 视图位置
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug(f"[ViewFrame.__init__] 初始化视图框架: {view_id}")
        
        self._view_id = view_id
        self._position = position
        self._is_active = False
        self._series_id: Optional[str] = None
        self._image_model: Optional[ImageDataModel] = None
        
        # 启用拖拽接收
        self.setAcceptDrops(True)
        
        self._setup_ui()
        self._setup_style()
        
        logger.debug(f"[ViewFrame.__init__] 视图框架初始化完成: {view_id}")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug(f"[ViewFrame._setup_ui] 设置视图框架UI: {self._view_id}")
        
        # 主布局
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(2, 2, 2, 2)
        self._main_layout.setSpacing(1)
        
        # 标题栏
        self._title_bar = self._create_title_bar()
        self._main_layout.addWidget(self._title_bar)
        
        # 图像查看器
        self._image_viewer = ImageViewer(self)
        self._main_layout.addWidget(self._image_viewer, 1)
        
        # 连接图像查看器的信号以显示坐标和像素值
        self._image_viewer.pixel_value_changed.connect(self._update_pixel_info)
        self._image_viewer.cursor_left_image.connect(self._clear_pixel_info)
        
        # 状态栏
        self._status_bar = self._create_status_bar()
        self._main_layout.addWidget(self._status_bar)
        
        logger.debug(f"[ViewFrame._setup_ui] UI设置完成: {self._view_id}")
    
    def _create_title_bar(self) -> QWidget:
        """创建标题栏"""
        title_bar = QWidget()
        title_bar.setFixedHeight(24)
        title_bar.setObjectName("viewTitleBar")
        
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)
        
        # 位置标签
        pos_text = f"{self._position.value[0]+1}-{self._position.value[1]+1}"
        self._position_label = QLabel(pos_text)
        self._position_label.setObjectName("positionLabel")
        layout.addWidget(self._position_label)
        
        # 序列信息标签
        self._series_label = QLabel(self.tr("无序列"))
        self._series_label.setObjectName("seriesLabel")
        layout.addWidget(self._series_label, 1)
        
        # 活动指示器
        self._active_indicator = QFrame()
        self._active_indicator.setFixedSize(8, 8)
        self._active_indicator.setObjectName("activeIndicator")
        layout.addWidget(self._active_indicator)
        
        return title_bar
    
    def _create_status_bar(self) -> QWidget:
        """创建状态栏"""
        status_bar = QWidget()
        status_bar.setFixedHeight(20)
        status_bar.setObjectName("viewStatusBar")
        
        layout = QHBoxLayout(status_bar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)
        
        # 切片信息
        self._slice_label = QLabel("")
        self._slice_label.setObjectName("sliceLabel")
        layout.addWidget(self._slice_label)
        
        layout.addStretch()
        
        # 坐标信息
        self._coordinate_label = QLabel("")
        self._coordinate_label.setObjectName("coordinateLabel")
        layout.addWidget(self._coordinate_label)
        
        # 像素值信息
        self._pixel_value_label = QLabel("")
        self._pixel_value_label.setObjectName("pixelValueLabel")
        layout.addWidget(self._pixel_value_label)
        
        # 窗宽窗位信息
        self._wl_label = QLabel("")
        self._wl_label.setObjectName("wlLabel")
        layout.addWidget(self._wl_label)
        
        return status_bar
    
    def _setup_style(self) -> None:
        """设置样式"""
        self.setObjectName("viewFrame")
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(2)
        self._update_border_style()
    
    def _update_border_style(self) -> None:
        """更新边框样式"""
        if self._is_active:
            self.setStyleSheet("""
                ViewFrame[objectName="viewFrame"] {
                    border: 2px solid #0078d4;
                    background-color: rgba(0, 120, 212, 10);
                }
            """)
        else:
            self.setStyleSheet("""
                ViewFrame[objectName="viewFrame"] {
                    border: 1px solid #cccccc;
                    background-color: transparent;
                }
            """)
    
    def mousePressEvent(self, event) -> None:
        """处理鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            logger.debug(f"[ViewFrame.mousePressEvent] 视图框架被点击: {self._view_id}")
            self.view_clicked.emit(self._view_id)
            
            # 如果不是活动视图，则激活
            if not self._is_active:
                self.view_activated.emit(self._view_id)
        
        super().mousePressEvent(event)
    
    def dragEnterEvent(self, event):
        """处理拖拽进入事件"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            logger.debug(f"[ViewFrame.dragEnterEvent] 拖拽进入视图框架: {self._view_id}")
            event.acceptProposedAction()
            # 设置拖拽接受状态的视觉反馈
            self._set_drag_accept_style(True)
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """处理拖拽移动事件"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """处理拖拽离开事件"""
        logger.debug(f"[ViewFrame.dragLeaveEvent] 拖拽离开视图框架: {self._view_id}")
        # 恢复原始样式
        self._set_drag_accept_style(False)
    
    def dropEvent(self, event):
        """处理拖拽放下事件"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            series_data = event.mimeData().data("application/x-medimager-series")
            series_id = series_data.data().decode()
            
            logger.debug(f"[ViewFrame.dropEvent] 序列拖拽到视图框架: view_id={self._view_id}, series_id={series_id}")
            
            # 恢复原始样式
            self._set_drag_accept_style(False)
            
            # 发出拖拽请求信号
            self.drop_requested.emit(self._view_id, series_id)
            
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def _set_drag_accept_style(self, accepting: bool) -> None:
        """设置拖拽接受状态的样式"""
        if accepting:
            # 拖拽接受状态：蓝色虚线边框 + 半透明蓝色背景
            self.setStyleSheet(f"""
                ViewFrame {{
                    border: 3px dashed #0078d4;
                    background-color: rgba(0, 120, 212, 0.1);
                }}
                QLabel {{
                    color: #0078d4;
                    font-weight: bold;
                }}
            """)
        else:
            # 恢复原始样式
            self._update_border_style()
    
    def set_active(self, active: bool) -> None:
        """设置激活状态
        
        Args:
            active: 是否激活
        """
        logger.debug(f"[ViewFrame.set_active] 设置激活状态: view_id={self._view_id}, active={active}")
        
        if self._is_active != active:
            self._is_active = active
            self._update_border_style()
            self._active_indicator.setVisible(active)
            
            if active:
                logger.info(f"[ViewFrame.set_active] 视图激活: {self._view_id}")
    
    def bind_series(self, series_id: str, image_model: ImageDataModel, series_info: str) -> None:
        """绑定序列到视图
        
        Args:
            series_id: 序列ID
            image_model: 图像数据模型
            series_info: 序列描述信息
        """
        logger.debug(f"[ViewFrame.bind_series] 绑定序列: view_id={self._view_id}, "
                    f"series_id={series_id}")
        
        try:
            self._series_id = series_id
            self._image_model = image_model # 存储图像模型
            
            # 更新UI显示
            self._series_label.setText(series_info)
            
            # 绑定图像数据
            self._image_viewer.set_model(image_model)
            
            # 连接信号以更新状态信息和图像显示
            image_model.data_changed.connect(self._update_status_info)
            image_model.data_changed.connect(self._update_image_display)
            image_model.slice_changed.connect(self._update_slice_info)
            image_model.slice_changed.connect(self._update_image_display)
            
            # 初始化状态显示和图像显示
            self._update_status_info()
            self._update_slice_info()
            self._update_image_display()
            
            # 首次绑定时自适应窗格大小
            self._image_viewer.fit_to_window()
            
            logger.info(f"[ViewFrame.bind_series] 序列绑定成功: {self._view_id} -> {series_id}")
            
        except Exception as e:
            logger.error(f"[ViewFrame.bind_series] 绑定序列失败: {e}", exc_info=True)
    
    def unbind_series(self) -> None:
        """解除序列绑定"""
        logger.debug(f"[ViewFrame.unbind_series] 解除序列绑定: view_id={self._view_id}")
        
        try:
            if self._series_id:
                old_series_id = self._series_id
                
                # 清除数据
                self._series_id = None
                self._image_model = None # 清除图像模型
                
                # 清除图像数据
                self._image_viewer.display_qimage(None)
                
                # 更新UI
                self._series_label.setText(self.tr("无序列"))
                self._slice_label.setText("")
                self._wl_label.setText("")
                self._coordinate_label.setText("")
                self._pixel_value_label.setText("")
                
                logger.info(f"[ViewFrame.unbind_series] 序列解绑成功: {self._view_id} <- {old_series_id}")
            
        except Exception as e:
            logger.error(f"[ViewFrame.unbind_series] 解除序列绑定失败: {e}", exc_info=True)
    
    def _update_status_info(self) -> None:
        """更新状态信息"""
        try:
            if self._image_model:
                model = self._image_model
                ww = model.window_width
                wl = model.window_level
                self._wl_label.setText(f"W:{ww} L:{wl}")
        except Exception as e:
            logger.debug(f"[ViewFrame._update_status_info] 更新状态信息失败: {e}")
    
    def _update_slice_info(self) -> None:
        """更新切片信息"""
        try:
            if self._image_model:
                model = self._image_model
                current = model.current_slice_index + 1
                total = model.slice_count
                self._slice_label.setText(f"{current}/{total}")
        except Exception as e:
            logger.debug(f"[ViewFrame._update_slice_info] 更新切片信息失败: {e}")
    
    def _update_image_display(self) -> None:
        """更新图像显示"""
        try:
            if self._image_model:
                model = self._image_model
                
                # 获取当前切片数据
                original_slice = model.get_current_slice_data()
                
                if original_slice is not None:
                    # 应用窗宽窗位设置
                    display_slice = model.apply_window_level(original_slice)
                    
                    # 转换为QImage
                    from PySide6.QtGui import QImage
                    height, width = display_slice.shape
                    bytes_per_line = width
                    
                    # 创建QImage
                    q_image = QImage(display_slice.copy().data, width, height, bytes_per_line, QImage.Format_Grayscale8)
                    
                    # 显示图像
                    self._image_viewer.display_qimage(q_image)
                    
                    logger.debug(f"[ViewFrame._update_image_display] 图像显示更新完成: {self._view_id}")
                else:
                    # 清空显示
                    self._image_viewer.display_qimage(None)
                    
        except Exception as e:
            logger.error(f"[ViewFrame._update_image_display] 更新图像显示失败: {e}", exc_info=True)
    
    def _update_pixel_info(self, x: int, y: int, value: float) -> None:
        """更新像素信息显示"""
        try:
            self._coordinate_label.setText(f"({x}, {y})")
            self._pixel_value_label.setText(f"值: {value:.0f}")
        except Exception as e:
            logger.debug(f"[ViewFrame._update_pixel_info] 更新像素信息失败: {e}")
    
    def _clear_pixel_info(self) -> None:
        """清除像素信息显示"""
        try:
            self._coordinate_label.setText("")
            self._pixel_value_label.setText("")
        except Exception as e:
            logger.debug(f"[ViewFrame._clear_pixel_info] 清除像素信息失败: {e}")
    
    # 属性访问器
    @property
    def view_id(self) -> str:
        return self._view_id
    
    @property
    def position(self) -> ViewPosition:
        return self._position
    
    @property
    def is_active(self) -> bool:
        return self._is_active
    
    @property
    def series_id(self) -> Optional[str]:
        return self._series_id
    
    @property
    def image_viewer(self) -> ImageViewer:
        return self._image_viewer


class MultiViewerGrid(QWidget):
    """多视图网格组件
    
    管理多个视图的动态网格布局，支持1x1到3x3的布局切换。
    
    Signals:
        layout_changed (tuple): 布局变更时发出，参数为(rows, cols)
        view_activated (str): 视图激活时发出，参数为视图ID
        binding_requested (str, str): 请求绑定时发出，参数为(view_id, series_id)
    """
    
    layout_changed = Signal(tuple)
    view_activated = Signal(str)
    binding_requested = Signal(str, str)
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QWidget] = None) -> None:
        """初始化多视图网格
        
        Args:
            series_manager: 多序列管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[MultiViewerGrid.__init__] 开始初始化多视图网格")
        
        self._series_manager = series_manager
        self._current_layout = (1, 1)
        self._view_frames: Dict[str, ViewFrame] = {}
        
        self._setup_ui()
        self._connect_signals()
        
        # 注意：初始布局将由主窗口在所有组件初始化完成后设置
        
        logger.info("[MultiViewerGrid.__init__] 多视图网格初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[MultiViewerGrid._setup_ui] 设置多视图网格UI")
        
        # 主布局
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(4, 4, 4, 4)
        self._main_layout.setSpacing(4)
        
        # 网格容器
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(2)
        
        self._main_layout.addWidget(self._grid_container)
        
        logger.debug("[MultiViewerGrid._setup_ui] UI设置完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[MultiViewerGrid._connect_signals] 连接信号槽")
        
        self._series_manager.layout_changed.connect(self._on_layout_changed)
        self._series_manager.binding_changed.connect(self._on_binding_changed)
        self._series_manager.active_view_changed.connect(self._on_active_view_changed)
    
    def set_layout(self, rows: int, cols: int) -> bool:
        """设置网格布局
        
        Args:
            rows: 行数
            cols: 列数
            
        Returns:
            是否成功设置
        """
        logger.debug(f"[MultiViewerGrid.set_layout] 设置网格布局: {rows}x{cols}")
        
        try:
            if rows < 1 or rows > 3 or cols < 1 or cols > 3:
                logger.error(f"[MultiViewerGrid.set_layout] 无效的布局参数: {rows}x{cols}")
                return False
            
            old_layout = self._current_layout
            self._current_layout = (rows, cols)
            
            # 清除现有视图
            self._clear_grid()
            
            # 创建新的视图框架
            self._create_view_frames(rows, cols)
            
            # 通知序列管理器布局变更
            self._series_manager.set_layout(rows, cols)
            
            logger.info(f"[MultiViewerGrid.set_layout] 网格布局设置成功: "
                       f"{old_layout} -> {self._current_layout}")
            self.layout_changed.emit(self._current_layout)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiViewerGrid.set_layout] 设置网格布局失败: {e}", exc_info=True)
            return False
    
    def _clear_grid(self) -> None:
        """清空网格"""
        logger.debug("[MultiViewerGrid._clear_grid] 清空网格")
        
        # 移除所有视图框架
        for view_frame in self._view_frames.values():
            self._grid_layout.removeWidget(view_frame)
            view_frame.deleteLater()
        
        self._view_frames.clear()
        
        logger.debug("[MultiViewerGrid._clear_grid] 网格清空完成")
    
    def _create_view_frames(self, rows: int, cols: int) -> None:
        """创建视图框架
        
        Args:
            rows: 行数
            cols: 列数
        """
        logger.debug(f"[MultiViewerGrid._create_view_frames] 创建视图框架: {rows}x{cols}")
        
        view_count = 0
        for row in range(rows):
            for col in range(cols):
                position = ViewPosition((row, col))
                
                # 从序列管理器获取视图ID
                view_ids = self._series_manager.get_all_view_ids()
                if view_count < len(view_ids):
                    view_id = view_ids[view_count]
                else:
                    # 如果视图ID不够，创建一个临时ID
                    view_id = f"view_{row}_{col}"
                
                # 创建视图框架
                view_frame = ViewFrame(view_id, position, self)
                
                # 连接信号
                view_frame.view_activated.connect(self._on_view_frame_activated)
                view_frame.view_clicked.connect(self._on_view_frame_clicked)
                view_frame.drop_requested.connect(self._on_view_frame_drop_requested) # 连接拖拽信号
                
                # 添加到网格
                self._grid_layout.addWidget(view_frame, row, col)
                self._view_frames[view_id] = view_frame
                
                # 获取绑定信息并设置状态
                binding = self._series_manager.get_view_binding(view_id)
                if binding:
                    # 设置活动状态
                    view_frame.set_active(binding.is_active)
                    
                    # 如果有绑定的序列，加载数据
                    if binding.series_id:
                        self._bind_series_to_view_frame(view_frame, binding.series_id)
                else:
                    # 如果是第一个视图，设置为活动状态
                    if view_count == 0:
                        view_frame.set_active(True)
                        # 通知序列管理器设置活动视图
                        self._series_manager.set_active_view(view_id)
                
                view_count += 1
                
                logger.debug(f"[MultiViewerGrid._create_view_frames] "
                           f"创建视图框架: {view_id} at ({row}, {col})")
        
        logger.debug(f"[MultiViewerGrid._create_view_frames] "
                    f"视图框架创建完成: {len(self._view_frames)}个")
    
    def _bind_series_to_view_frame(self, view_frame: ViewFrame, series_id: str) -> None:
        """将序列绑定到视图框架
        
        Args:
            view_frame: 视图框架
            series_id: 序列ID
        """
        logger.debug(f"[MultiViewerGrid._bind_series_to_view_frame] "
                    f"绑定序列到视图框架: view_id={view_frame.view_id}, series_id={series_id}")
        
        try:
            # 获取序列信息和数据模型
            series_info = self._series_manager.get_series_info(series_id)
            image_model = self._series_manager.get_series_model(series_id)
            
            if series_info and image_model:
                # 创建序列描述
                series_desc = self._format_series_description(series_info)
                
                # 绑定到视图框架
                view_frame.bind_series(series_id, image_model, series_desc)
                
                logger.debug(f"[MultiViewerGrid._bind_series_to_view_frame] "
                           f"绑定成功: {view_frame.view_id} -> {series_id}")
            else:
                logger.warning(f"[MultiViewerGrid._bind_series_to_view_frame] "
                             f"序列信息或数据模型不存在: series_id={series_id}")
                
        except Exception as e:
            logger.error(f"[MultiViewerGrid._bind_series_to_view_frame] "
                        f"绑定失败: {e}", exc_info=True)
    
    def _format_series_description(self, series_info) -> str:
        """格式化序列描述"""
        if series_info.series_description:
            return f"{series_info.series_description} ({series_info.modality})"
        elif series_info.patient_name:
            return f"{series_info.patient_name} - {series_info.modality}"
        else:
            return f"序列 {series_info.series_number}"
    
    def _on_layout_changed(self, layout: Tuple[int, int]) -> None:
        """处理布局变更事件"""
        logger.debug(f"[MultiViewerGrid._on_layout_changed] 处理布局变更: {layout}")
        
        # 布局变更由外部触发时，重新创建网格
        rows, cols = layout
        if self._current_layout != layout:
            self._current_layout = layout
            self._clear_grid()
            self._create_view_frames(rows, cols)
            
            # 布局变更后，为所有有绑定序列的视图自适应窗格大小
            self._fit_all_bound_views_to_window()
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[MultiViewerGrid._on_binding_changed] "
                    f"处理绑定变更: view_id={view_id}, series_id={series_id}")
        
        view_frame = self._view_frames.get(view_id)
        if view_frame:
            if series_id:
                self._bind_series_to_view_frame(view_frame, series_id)
            else:
                view_frame.unbind_series()
    
    def _on_active_view_changed(self, view_id: str) -> None:
        """处理活动视图变更事件"""
        logger.debug(f"[MultiViewerGrid._on_active_view_changed] "
                    f"处理活动视图变更: {view_id}")
        
        # 更新所有视图框架的活动状态
        for frame_id, view_frame in self._view_frames.items():
            view_frame.set_active(frame_id == view_id)
    
    def _on_view_frame_activated(self, view_id: str) -> None:
        """处理视图框架激活事件"""
        logger.debug(f"[MultiViewerGrid._on_view_frame_activated] 视图框架激活: {view_id}")
        
        # 通知序列管理器设置活动视图
        self._series_manager.set_active_view(view_id)
        self.view_activated.emit(view_id)
    
    def _on_view_frame_clicked(self, view_id: str) -> None:
        """处理视图框架点击事件"""
        logger.debug(f"[MultiViewerGrid._on_view_frame_clicked] 视图框架点击: {view_id}")
        
        # 可以在这里添加右键菜单等交互逻辑
        pass

    def _on_view_frame_drop_requested(self, view_id: str, series_id: str) -> None:
        """处理视图框架的拖拽请求"""
        logger.debug(f"[MultiViewerGrid._on_view_frame_drop_requested] 视图框架拖拽请求: view_id={view_id}, series_id={series_id}")
        self.binding_requested.emit(view_id, series_id)
    
    # 查询方法
    
    def get_current_layout(self) -> Tuple[int, int]:
        """获取当前布局"""
        return self._current_layout
    
    def get_view_frame(self, view_id: str) -> Optional[ViewFrame]:
        """获取指定的视图框架"""
        return self._view_frames.get(view_id)
    
    def get_all_view_frames(self) -> Dict[str, ViewFrame]:
        """获取所有视图框架"""
        return self._view_frames.copy()
    
    def get_active_view_frame(self) -> Optional[ViewFrame]:
        """获取当前活动的视图框架"""
        for view_frame in self._view_frames.values():
            if view_frame.is_active:
                return view_frame
        return None
    
    def _fit_all_bound_views_to_window(self) -> None:
        """为所有绑定了序列的视图自适应窗格大小"""
        logger.debug("[MultiViewerGrid._fit_all_bound_views_to_window] 为所有绑定视图自适应窗格大小")
        
        try:
            for view_frame in self._view_frames.values():
                if view_frame and view_frame.series_id and view_frame.image_viewer:
                    view_frame.image_viewer.fit_to_window()
                    logger.debug(f"[MultiViewerGrid._fit_all_bound_views_to_window] 自适应完成: {view_frame.view_id}")
                    
        except Exception as e:
            logger.error(f"[MultiViewerGrid._fit_all_bound_views_to_window] 自适应失败: {e}", exc_info=True) 