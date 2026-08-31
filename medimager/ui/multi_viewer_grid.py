"""
多视图网格组件

该模块提供动态的多视图网格布局，支持1x1到3x3的布局切换，
每个视图可以独立显示不同的DICOM序列。
"""

from typing import Dict, List, Optional, Tuple
from PySide6.QtWidgets import (QWidget, QGridLayout, QFrame, QVBoxLayout, 
                              QHBoxLayout, QLabel, QSplitter,
                              QApplication,
                              QStackedLayout)
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPointF, QTimer

from medimager.ui.image_viewer import ImageViewer
from medimager.ui.qt_image_utils import qimage_from_display_data
from medimager.core.multi_series_manager import MultiSeriesManager, ViewPosition
from medimager.core.image_data_model import ImageDataModel
from medimager.core.layout_presets import LayoutSpec
from medimager.core.view_presentation_state import (
    ViewPresentationState,
    render_display_slice,
)
from medimager.core.analysis import calculate_roi_statistics
from medimager.ui.widgets.roi_stats_box import (
    _get_stats_box_settings,
    calculate_stats_box_size_rect,
    get_stats_text,
)
from medimager.utils.logger import get_logger
from medimager.utils.settings import get_settings_manager
from medimager.utils.i18n import t

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
    maximize_requested = Signal(str)
    
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
        self._viewer_state_store = getattr(parent, "_viewer_state_store", {})
        self._presentation_state_store = getattr(parent, "_presentation_state_store", {})
        self._presentation_state: Optional[ViewPresentationState] = None
        self._display_cache_key = None
        self._display_cache_qimage = None
        self._series_info = ""
        self._privacy_enabled = False
        self._privacy_alias = ""
        
        # 启用拖拽接收
        self.setAcceptDrops(True)
        
        # 主题管理器相关 - 必须在_setup_style之前初始化
        self._theme_manager = None
        
        self._setup_ui()
        self._setup_style()
        
        # 注册到主题管理器
        self._register_to_theme_manager()
        self.apply_runtime_settings()
        
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
        
        # 图像查看器与空态/加载态覆盖层
        viewer_container = QWidget(self)
        self._viewer_stack = QStackedLayout(viewer_container)
        self._viewer_stack.setContentsMargins(0, 0, 0, 0)
        self._viewer_stack.setStackingMode(QStackedLayout.StackAll)
        self._image_viewer = ImageViewer(self)
        self._image_viewer.view_id = self._view_id
        self._viewer_stack.addWidget(self._image_viewer)
        self._state_overlay = QLabel(t('viewframe.empty_hint'), viewer_container)
        self._state_overlay.setAlignment(Qt.AlignCenter)
        self._state_overlay.setWordWrap(True)
        self._state_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._state_overlay.setStyleSheet(
            "QLabel { color: #f2f2f2; background: rgba(24, 28, 34, 185); "
            "padding: 18px; font-size: 13px; }"
        )
        self._viewer_stack.addWidget(self._state_overlay)
        # StackAll keeps both widgets laid out; the current widget is raised.
        self._viewer_stack.setCurrentWidget(self._state_overlay)
        self._main_layout.addWidget(viewer_container, 1)
        
        # 连接图像查看器的信号以显示坐标和像素值
        self._image_viewer.pixel_value_changed.connect(self._update_pixel_info)
        self._image_viewer.cursor_left_image.connect(self._clear_pixel_info)
        self._image_viewer.interaction_started.connect(self._activate_from_viewer_interaction)
        self._image_viewer.presentation_changed.connect(
            self._on_view_presentation_changed
        )
        self._image_viewer.maximize_requested.connect(self._request_maximize)
        self._image_viewer.series_drag_active.connect(self._set_drag_accept_style)
        self._image_viewer.series_drop_requested.connect(
            lambda series_id: self.drop_requested.emit(self._view_id, series_id)
        )
        
        # 状态栏
        self._status_bar = self._create_status_bar()
        self._main_layout.addWidget(self._status_bar)
        
        logger.debug(f"[ViewFrame._setup_ui] UI设置完成: {self._view_id}")

    def _request_maximize(self) -> None:
        self.maximize_requested.emit(self._view_id)

    def _activate_from_viewer_interaction(self) -> None:
        """在查看器处理交互前激活所属视图。"""
        if not self._is_active:
            self.view_activated.emit(self._view_id)
    
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
        self._series_label = QLabel(t("viewframe.no_serial_number"))
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
        
        # 分割线1
        separator1 = QLabel("|")
        separator1.setStyleSheet("color: #888888;")
        layout.addWidget(separator1)
        
        # 像素值信息
        self._pixel_value_label = QLabel("")
        self._pixel_value_label.setObjectName("pixelValueLabel")
        layout.addWidget(self._pixel_value_label)
        
        # 分割线2
        separator2 = QLabel("|")
        separator2.setStyleSheet("color: #888888;")
        layout.addWidget(separator2)
        
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
        # 使用主题感知的边框样式更新
        if self._theme_manager:
            current_theme = self._theme_manager.get_current_theme()
            self._update_border_style_for_theme(current_theme)
        else:
            # 回退到默认样式（浅色主题）
            self._update_border_style_for_theme('light')
    
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
            self.setStyleSheet("""
                ViewFrame {
                    border: 3px dashed #0078d4;
                    background-color: rgba(0, 120, 212, 0.1);
                }
                QLabel {
                    color: #0078d4;
                    font-weight: bold;
                }
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

    def has_bound_model(self) -> bool:
        """检查是否已绑定了图像数据模型"""
        return self._image_model is not None

    def apply_runtime_settings(self) -> None:
        """应用设置面板中可即时生效的视图显示选项。"""
        try:
            settings = get_settings_manager()
            show_title = self._to_bool(settings.get_setting("display.show_view_title", True))
            show_status = self._to_bool(settings.get_setting("display.show_view_status", True))
            self._title_bar.setVisible(show_title)
            self._status_bar.setVisible(show_status)
            if hasattr(self._image_viewer, "apply_runtime_settings"):
                self._image_viewer.apply_runtime_settings()
            show_pixel_value = self._to_bool(
                settings.get_setting("overlay.show_pixel_value", False)
            )
            self._pixel_value_label.setVisible(show_status and show_pixel_value)
        except Exception as e:
            logger.debug(f"[ViewFrame.apply_runtime_settings] 应用显示设置失败: {e}")

    def set_privacy_mode(self, enabled: bool, alias: str = "") -> None:
        """Replace potentially identifying viewport copy without touching data."""

        self._privacy_enabled = bool(enabled)
        if alias:
            self._privacy_alias = str(alias)
        self._refresh_series_copy()

    def _refresh_series_copy(self) -> None:
        if self._series_id is None:
            text = t("viewframe.no_serial_number")
        elif self._privacy_enabled:
            text = self._privacy_alias or t("multiviewergrid.series")
        else:
            text = self._series_info or t("viewframe.no_serial_number")
        self._series_label.setText(text)
        self._image_viewer.set_corner_overlay_info(title=text)

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

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
            # 先清理旧的工具数据和状态
            self._clear_tool_data()
            
            self._series_id = series_id
            self._image_model = image_model
            self._series_info = str(series_info or "")
            
            # 更新UI显示
            self._refresh_series_copy()
            state_key = (series_id, self._view_id)
            state = self._presentation_state_store.get(state_key)
            if state is None:
                state = ViewPresentationState.from_model(
                    image_model,
                    series_id=series_id,
                    interpolation=self._image_viewer.presentation_state.interpolation,
                )
                self._presentation_state_store[state_key] = state
            self._presentation_state = state

            
            # 绑定图像数据
            self._image_viewer.set_model(image_model, initialize_state=False)
            self._image_viewer.set_presentation_state(state)
            self._viewer_stack.setCurrentWidget(self._image_viewer)
            self._state_overlay.hide()

            # 连接信号以更新状态信息和图像显示
            image_model.data_changed.connect(self._on_model_data_changed)
            image_model.data_changed.connect(self._restore_roi_stats_positions)
            image_model.pixels_changed.connect(self._on_model_pixels_changed)
            image_model.metadata_changed.connect(self._update_status_info)
            image_model.slice_changed.connect(self._on_model_slice_changed)
            image_model.window_level_changed.connect(self._on_model_window_changed)

            
            # 初始化状态显示和图像显示
            self._update_status_info()
            self._update_slice_info()
            self._update_image_display()
            
            if state.fit_mode:
                self._image_viewer.fit_to_window()
            else:
                # Reapply saved pan/zoom after the image item has a scene rect.
                self._image_viewer.set_presentation_state(state)
            QTimer.singleShot(0, self._restore_roi_stats_positions)
            
            logger.info(f"[ViewFrame.bind_series] 序列绑定成功: {self._view_id} -> {series_id}")
            
        except Exception as e:
            logger.error(f"[ViewFrame.bind_series] 绑定序列失败: {e}", exc_info=True)
            self.show_error_state(str(e))

    def _on_view_presentation_changed(self, _state=None) -> None:
        if self._image_model is None:
            return
        self._update_status_info()
        self._update_slice_info()
        self._update_image_display()
        self._restore_roi_stats_positions()

    def _on_model_data_changed(self) -> None:
        """Repaint annotations without rebuilding the unchanged pixel layer."""
        self._image_viewer.viewport().update()

    def _on_model_pixels_changed(self) -> None:
        self._display_cache_key = None
        self._display_cache_qimage = None
        self._image_viewer._roi_stats_cache.clear()
        self._update_image_display()


    def _on_model_slice_changed(self, slice_index: int) -> None:
        """Compatibility path for old callers that target the active model."""
        if self._is_active:
            self._image_viewer.set_view_slice(slice_index)

    def _on_model_window_changed(self, width: int, level: int) -> None:
        """Compatibility path for toolbar actions not yet view-aware."""
        if self._is_active:
            self._image_viewer.set_view_window(width, level)

    def set_compact_mode(self, compact: bool) -> None:
        settings = get_settings_manager()
        show_title = self._to_bool(settings.get_setting("display.show_view_title", True))
        show_status = self._to_bool(settings.get_setting("display.show_view_status", True))
        self._title_bar.setVisible(show_title and not compact)
        self._status_bar.setVisible(show_status and not compact)
        self._image_viewer.viewport().update()


    def show_loading_state(self, series_id: str, series_info: str) -> None:
        """显示已绑定但仍在后台解码的序列状态。"""
        self._series_id = series_id
        self._series_info = str(series_info or "")
        self._refresh_series_copy()
        self._state_overlay.setText(t('viewframe.loading_hint'))
        self._viewer_stack.setCurrentWidget(self._state_overlay)
        self._state_overlay.show()

    def show_error_state(self, detail: str = '') -> None:
        """在视图内部显示解码/显示失败，而不吞掉全局错误详情。"""
        message = t('viewframe.load_failed_hint')
        if detail:
            message += f"\n{detail}"
        self._state_overlay.setText(message)
        self._viewer_stack.setCurrentWidget(self._state_overlay)
        self._state_overlay.show()
    
    def unbind_series(self) -> None:
        """解除序列绑定"""
        logger.debug(f"[ViewFrame.unbind_series] 解除序列绑定: view_id={self._view_id}")
        
        try:
            if self._series_id:
                old_series_id = self._series_id

                # 先断开旧模型并清除当前视图的临时交互状态。持久标注仍归模型所有。
                self._clear_tool_data()

                self._series_id = None
                self._image_model = None
                self._series_info = ""
                self._image_viewer.display_qimage(None)
                
                # 更新UI
                self._series_label.setText(t("viewframe.no_serial_number"))
                self._slice_label.setText("")
                self._wl_label.setText("")
                self._coordinate_label.setText("")
                self._pixel_value_label.setText("")
                self._state_overlay.setText(t('viewframe.empty_hint'))
                self._viewer_stack.setCurrentWidget(self._state_overlay)
                self._state_overlay.show()
                
                logger.info(f"[ViewFrame.unbind_series] 序列解绑成功: {self._view_id} <- {old_series_id}")
            
        except Exception as e:
            logger.error(f"[ViewFrame.unbind_series] 解除序列绑定失败: {e}", exc_info=True)
    
    def _update_status_info(self) -> None:
        """更新状态信息"""
        try:
            if self._image_model:
                ww = self._image_viewer.window_width
                wl = self._image_viewer.window_level
                text = f"WW/WL: {ww:.0f}/{wl:.0f}"
                self._wl_label.setText(text)
                self._image_viewer.set_corner_overlay_info(window=text)
        except Exception as e:
            logger.debug(f"[ViewFrame._update_status_info] 更新状态信息失败: {e}")
    
    def _update_slice_info(self) -> None:
        """更新切片信息"""
        try:
            if self._image_model:
                model = self._image_model
                current = self._image_viewer.current_slice_index + 1
                total = model.get_slice_count()
                text = f"{t('viewframe.slice')}: {current}/{total}"
                self._slice_label.setText(text)
                self._image_viewer.set_corner_overlay_info(slice=text)
        except Exception as e:
            logger.debug(f"[ViewFrame._update_slice_info] 更新切片信息失败: {e}")
    
    def _update_image_display(self) -> None:
        """更新图像显示（使用带缓存的 get_display_slice）"""
        try:
            if self._image_model:
                model = self._image_model
                state = self._image_viewer.presentation_state
                cache_key = (
                    id(model),
                    int(getattr(model, "_data_revision", 0)),
                    int(state.slice_index),
                    float(state.window_width),
                    float(state.window_level),
                    bool(state.use_dicom_voi_lut),
                    state.voi_lut_index,
                )
                q_image = self._display_cache_qimage
                if cache_key != self._display_cache_key or q_image is None:
                    display_slice = render_display_slice(model, state)
                    q_image = (
                        qimage_from_display_data(display_slice)
                        if display_slice is not None
                        else None
                    )
                    self._display_cache_key = cache_key
                    self._display_cache_qimage = q_image

                if q_image is not None and not q_image.isNull():
                    self._image_viewer.display_qimage(q_image)

                    logger.debug(f"[ViewFrame._update_image_display] 图像显示更新完成: {self._view_id}")
                else:
                    # 清空显示
                    self._image_viewer.display_qimage(None)
                    self.show_error_state()

        except Exception as e:
            logger.error(f"[ViewFrame._update_image_display] 更新图像显示失败: {e}", exc_info=True)
    
    def _update_pixel_info(self, x: int, y: int, value) -> None:
        """更新像素信息显示"""
        try:
            self._coordinate_label.setText(f"X:{x} Y:{y}")
            if isinstance(value, (tuple, list)):
                channels = tuple(float(channel) for channel in value)
                prefix = "RGBA" if len(channels) == 4 else "RGB"
                formatted = ", ".join(f"{channel:g}" for channel in channels)
                self._pixel_value_label.setText(f"{prefix}: ({formatted})")
                return

            model = self._image_viewer.model
            dataset = None
            if model and model.is_dicom():
                dataset = model.get_dicom_file(self._image_viewer.current_slice_index)
            modality = str(getattr(dataset, 'Modality', '') or '').upper()
            unit = str(
                getattr(dataset, 'RescaleType', '')
                or getattr(dataset, 'Units', '')
                or ''
            ).strip()
            if modality == 'CT':
                label = t('viewframe.ct_value')
                unit = unit or 'HU'
            else:
                label = modality or t('viewframe.pixel_value')
            suffix = f" {unit}" if unit else ""
            self._pixel_value_label.setText(f"{label}: {float(value):g}{suffix}")
        except Exception as e:
            logger.debug(f"[ViewFrame._update_pixel_info] 更新像素信息失败: {e}")
    
    def _clear_pixel_info(self) -> None:
        """清除像素信息显示"""
        try:
            self._coordinate_label.setText("")
            self._pixel_value_label.setText("")
        except Exception as e:
            logger.debug(f"[ViewFrame._clear_pixel_info] 清除像素信息失败: {e}")
    
    def _clear_tool_data(self) -> None:
        """清除仅属于当前视图的临时工具状态，不修改模型标注。"""
        try:
            old_model = self._image_model
            if old_model is None and getattr(self._image_viewer, "model", None) is not None:
                old_model = self._image_viewer.model

            self._persist_roi_stats_positions(old_model)

            # 先断开旧模型，避免清理临时状态时触发多余重绘。
            if old_model is not None:
                for signal, slot in (
                    (old_model.data_changed, self._on_model_data_changed),
                    (old_model.data_changed, self._restore_roi_stats_positions),
                    (old_model.pixels_changed, self._on_model_pixels_changed),
                    (old_model.metadata_changed, self._update_status_info),
                    (old_model.slice_changed, self._on_model_slice_changed),
                    (old_model.window_level_changed, self._on_model_window_changed),
                ):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass

            # Cancel any in-progress drawing operation while keeping completed data.
            current_tool = getattr(self._image_viewer, "current_tool", None)
            if current_tool is not None:
                try:
                    current_tool.deactivate()
                    reset_measurement = getattr(current_tool, "_reset_measurement", None)
                    if callable(reset_measurement):
                        reset_measurement()
                    current_tool.activate()
                except Exception as error:
                    logger.debug(f"[ViewFrame._clear_tool_data] 重置临时工具状态失败: {error}")

            # 清除ImageViewer中的ROI相关状态
            if hasattr(self._image_viewer, 'clear_roi_dependent_state'):
                self._image_viewer.clear_roi_dependent_state()
            
            # 清除测量线
            if hasattr(self._image_viewer, 'clear_measurement_line'):
                self._image_viewer.clear_measurement_line()
            
            # 清除ImageViewer的模型引用
            if hasattr(self._image_viewer, 'set_model'):
                self._image_viewer.set_model(None)

            self._image_model = None
            
            # 强制重绘视图
            self._image_viewer.viewport().update()
            
            logger.debug(f"[ViewFrame._clear_tool_data] 工具数据清理完成: {self._view_id}")
            self._display_cache_key = None
            self._display_cache_qimage = None
            
        except Exception as e:
            logger.error(f"[ViewFrame._clear_tool_data] 清理工具数据失败: {e}", exc_info=True)

    def _persist_roi_stats_positions(self, model: Optional[ImageDataModel]) -> None:
        """Store per-view ROI label positions outside the persistent data model."""
        if model is None or not self._series_id:
            return
        valid_ids = {roi.id for roi in model.rois}
        positions = {
            roi_id: QRectF(rect)
            for roi_id, rect in self._image_viewer.stats_box_positions.items()
            if roi_id in valid_ids
        }
        self._viewer_state_store[(self._series_id, self._view_id)] = positions

    def _restore_roi_stats_positions(self, *_args) -> None:
        """Restore or safely generate visible label positions for current-slice ROIs."""
        model = self._image_model
        viewer = self._image_viewer
        if model is None or not model.has_image() or viewer.image_item is None:
            return

        valid_ids = {roi.id for roi in model.rois}
        viewer.stats_box_positions = {
            roi_id: rect
            for roi_id, rect in viewer.stats_box_positions.items()
            if roi_id in valid_ids
        }

        saved_positions = self._viewer_state_store.get(
            (self._series_id, self._view_id), {}
        )
        for roi in model.rois:
            if roi.slice_index != viewer.current_slice_index or not roi.show_stats:
                continue
            if roi.id in viewer.stats_box_positions:
                viewer.set_stats_box_viewport_rect(
                    roi.id, viewer.get_stats_box_viewport_rect(roi.id)
                )
                continue
            if roi.id in saved_positions:
                viewer.stats_box_positions[roi.id] = QRectF(saved_positions[roi.id])
                viewer.set_stats_box_viewport_rect(
                    roi.id, viewer.get_stats_box_viewport_rect(roi.id)
                )
                continue

            stats = calculate_roi_statistics(model, roi)
            if not stats:
                continue
            font = viewer.font()
            font.setPointSize(int(_get_stats_box_settings().get("font_size", 10)))
            size = calculate_stats_box_size_rect(get_stats_text(stats), font)
            rect = viewer.create_stats_box_viewport_rect(roi, size.size())
            viewer.set_stats_box_viewport_rect(roi.id, rect)

        viewer.viewport().update()

    @staticmethod
    def _clamp_stats_rect(rect: QRect, bounds: QRect) -> QRect:
        """Keep a stats rectangle inside the currently visible image area."""
        if bounds.isEmpty():
            return rect
        if rect.width() <= bounds.width():
            rect.moveLeft(max(bounds.left(), min(rect.left(), bounds.right() - rect.width() + 1)))
        else:
            rect.moveLeft(bounds.left())
        if rect.height() <= bounds.height():
            rect.moveTop(max(bounds.top(), min(rect.top(), bounds.bottom() - rect.height() + 1)))
        else:
            rect.moveTop(bounds.top())
        return rect
    
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
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                self._theme_manager = main_window.theme_manager
                self._theme_manager.register_component(self)
                logger.debug(f"[ViewFrame._register_to_theme_manager] 成功注册到主题管理器: {self._view_id}")
                
                # 立即应用当前主题
                current_theme = self._theme_manager.get_current_theme()
                self.update_theme(current_theme)
            else:
                logger.debug(f"[ViewFrame._register_to_theme_manager] 未找到主题管理器: {self._view_id}")
        except Exception as e:
            logger.error(f"[ViewFrame._register_to_theme_manager] 注册主题管理器失败: {e}", exc_info=True)
    
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[ViewFrame.update_theme] 开始更新主题: {theme_name}, view_id: {self._view_id} (ID: {id(self)})")
        try:
            # 更新边框样式（根据主题调整颜色）
            logger.info(f"[ViewFrame.update_theme] 更新边框样式, 当前激活状态: {self._is_active}")
            self._update_border_style_for_theme(theme_name)
            
            # 更新标题栏和状态栏的样式
            logger.info("[ViewFrame.update_theme] 更新标题栏主题")
            self._update_title_bar_theme(theme_name)
            
            logger.info("[ViewFrame.update_theme] 更新状态栏主题")
            self._update_status_bar_theme(theme_name)
            
            # 更新内部ImageViewer的主题
            if hasattr(self, '_image_viewer') and self._image_viewer:
                logger.info("[ViewFrame.update_theme] 更新内部ImageViewer主题")
                if hasattr(self._image_viewer, 'update_theme'):
                    self._image_viewer.update_theme(theme_name)
                else:
                    logger.warning("[ViewFrame.update_theme] ImageViewer没有update_theme方法")
            else:
                logger.info("[ViewFrame.update_theme] 没有ImageViewer需要更新")
            
            logger.info(f"[ViewFrame.update_theme] 主题更新完成: {theme_name}, view_id: {self._view_id}")
        except Exception as e:
            logger.error(f"[ViewFrame.update_theme] 主题更新失败: {e}", exc_info=True)
    
    def _update_border_style_for_theme(self, theme_name: str) -> None:
        """根据主题更新边框样式"""
        if self._is_active:
            if theme_name == 'light':
                self.setStyleSheet("""
                    ViewFrame[objectName="viewFrame"] {
                        border: 2px solid #0078d4;
                        background-color: rgba(0, 120, 212, 10);
                    }
                """)
            else:  # dark theme
                self.setStyleSheet("""
                    ViewFrame[objectName="viewFrame"] {
                        border: 2px solid #4cc2ff;
                        background-color: rgba(76, 194, 255, 10);
                    }
                """)
        else:
            if theme_name == 'light':
                self.setStyleSheet("""
                    ViewFrame[objectName="viewFrame"] {
                        border: 1px solid #cccccc;
                        background-color: transparent;
                    }
                """)
            else:  # dark theme
                self.setStyleSheet("""
                    ViewFrame[objectName="viewFrame"] {
                        border: 1px solid #555555;
                        background-color: transparent;
                    }
                """)
    
    def _update_title_bar_theme(self, theme_name: str) -> None:
        """更新标题栏主题"""
        if theme_name == 'light':
            title_style = """
                QWidget[objectName="viewTitleBar"] {
                    background-color: #f8f9fa;
                    color: #333333;
                }
                QLabel {
                    color: #333333;
                }
            """
        else:  # dark theme
            title_style = """
                QWidget[objectName="viewTitleBar"] {
                    background-color: #3c3c3c;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
            """
        
        if hasattr(self, '_title_bar'):
            self._title_bar.setStyleSheet(title_style)
    
    def _update_status_bar_theme(self, theme_name: str) -> None:
        """更新状态栏主题"""
        if theme_name == 'light':
            status_style = """
                QWidget[objectName="viewStatusBar"] {
                    background-color: #f8f9fa;
                    color: #666666;
                }
                QLabel {
                    color: #666666;
                    font-size: 11px;
                }
            """
        else:  # dark theme
            status_style = """
                QWidget[objectName="viewStatusBar"] {
                    background-color: #3c3c3c;
                    color: #cccccc;
                }
                QLabel {
                    color: #cccccc;
                    font-size: 11px;
                }
            """
        
        if hasattr(self, '_status_bar'):
            self._status_bar.setStyleSheet(status_style)


class MultiViewerGrid(QWidget):
    """多视图网格组件
    
    管理多个视图的动态网格布局，支持1x1到3x3的布局切换。
    
    Signals:
        layout_changed (tuple): 布局变更时发出，参数为(rows, cols)
        view_activated (str): 视图激活时发出，参数为视图ID
        binding_requested (str, str): 请求绑定时发出，参数为(view_id, series_id)
    """
    
    layout_changed = Signal(tuple)
    layout_geometry_changed = Signal(object)
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
        self._sync_manager = None  # 将由主窗口设置
        self._current_layout = (1, 1)
        self._current_layout_spec = LayoutSpec()
        self._privacy_enabled = False
        self._privacy_aliases: Dict[str, str] = {}
        self._active_splitters: Dict[str, QSplitter] = {}
        self._layout_geometry_timer = QTimer(self)
        self._layout_geometry_timer.setSingleShot(True)
        self._layout_geometry_timer.setInterval(400)
        self._layout_geometry_timer.timeout.connect(
            self._emit_layout_geometry_changed
        )
        self._view_frames: Dict[str, ViewFrame] = {}
        self._viewer_state_store: Dict[tuple[str, str], Dict[str, QRectF]] = {}
        # Per-pane state is persistent across layout rebuilds and is never stored
        # on the shared ImageDataModel.
        self._presentation_state_store: Dict[tuple[str, str], ViewPresentationState] = {}
        self._maximized_view_id: Optional[str] = None
        self._rebuilding = False  # 防止 set_layout 与信号处理重复重建
        
        self._setup_ui()
        self._connect_signals()
        
        # 主题管理器注册
        self._theme_manager = None
        self._register_to_theme_manager()
        
        # 注意：初始布局将由主窗口在所有组件初始化完成后设置
        
        logger.info("[MultiViewerGrid.__init__] 多视图网格初始化完成")
    
    def set_sync_manager(self, sync_manager) -> None:
        """设置同步管理器
        
        Args:
            sync_manager: 同步管理器实例
        """
        logger.debug("[MultiViewerGrid.set_sync_manager] 设置同步管理器")
        
        self._sync_manager = sync_manager
        
        # 连接同步信号
        self._connect_sync_signals()
        
        # 为所有已存在的视图框架设置同步管理器
        for view_frame in self._view_frames.values():
            if hasattr(view_frame, 'set_sync_manager'):
                view_frame.set_sync_manager(sync_manager)
            # 同时传播到 ImageViewer
            if view_frame.image_viewer:
                view_frame.image_viewer.sync_manager = sync_manager

        logger.debug("[MultiViewerGrid.set_sync_manager] 同步管理器设置完成")

    def set_privacy_mode(self, enabled: bool) -> None:
        """Apply stable session aliases to every visible viewport title."""

        self._privacy_enabled = bool(enabled)
        for frame in self._view_frames.values():
            frame.set_privacy_mode(
                self._privacy_enabled,
                self._privacy_alias_for(frame.series_id),
            )

    def _privacy_alias_for(self, series_id: Optional[str]) -> str:
        if not series_id:
            return ""
        alias = self._privacy_aliases.get(series_id)
        if alias is None:
            alias = f"Series {len(self._privacy_aliases) + 1:02d}"
            self._privacy_aliases[series_id] = alias
        return alias

    def _connect_sync_signals(self) -> None:
        """连接同步管理器信号"""
        if not hasattr(self, '_sync_manager') or not self._sync_manager:
            return
            
        logger.debug("[MultiViewerGrid._connect_sync_signals] 连接同步管理器信号")
        
        # 连接同步管理器的信号到视图处理
        if hasattr(self._sync_manager, 'cross_reference_updated'):
            self._sync_manager.cross_reference_updated.connect(self._on_cross_reference_updated)
        if hasattr(self._sync_manager, 'cross_reference_line_updated'):
            self._sync_manager.cross_reference_line_updated.connect(
                self._on_cross_reference_line_updated
            )
        if hasattr(self._sync_manager, 'patient_cursor_updated'):
            self._sync_manager.patient_cursor_updated.connect(
                self._on_patient_cursor_updated
            )
        if hasattr(self._sync_manager, 'view_synced'):
            self._sync_manager.view_synced.connect(self._on_view_synced)
        
        logger.debug("[MultiViewerGrid._connect_sync_signals] 同步管理器信号连接完成")

    def _on_cross_reference_updated(self, view_id: str, position) -> None:
        """在信号指定的目标视图中更新交叉参考线。"""
        logger.debug(f"[MultiViewerGrid._on_cross_reference_updated] 更新交叉参考线: view_id={view_id}")

        # SyncManager 发出的 view_id 已经是完成患者坐标转换后的目标视图，
        # 不能再次把它当作源视图广播到其余窗口。
        view_frame = self._view_frames.get(view_id)
        if not view_frame or not view_frame.image_viewer:
            return
        try:
            view_frame.image_viewer.show_cross_reference(position)
        except Exception as e:
            logger.warning(f"[MultiViewerGrid._on_cross_reference_updated] 更新交叉参考线失败: {e}")

    def _on_cross_reference_line_updated(
        self, view_id: str, start: QPointF, end: QPointF
    ) -> None:
        view_frame = self._view_frames.get(view_id)
        if view_frame and view_frame.image_viewer:
            view_frame.image_viewer.show_reference_line(start, end)

    def _on_patient_cursor_updated(self, view_id: str, position: QPointF) -> None:
        view_frame = self._view_frames.get(view_id)
        if view_frame and view_frame.image_viewer:
            view_frame.image_viewer.show_patient_cursor(position)

    def _on_view_synced(self, source_view_id: str, target_view_id: str) -> None:
        """处理视图同步事件"""
        logger.debug(f"[MultiViewerGrid._on_view_synced] 视图同步: {source_view_id} -> {target_view_id}")
        # 这里可以添加视图同步后的UI更新逻辑
    
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
        self._series_manager.series_loaded.connect(self._on_series_data_ready)
        self._series_manager.series_removed.connect(self._on_series_removed)

    def _on_series_removed(self, series_id: str) -> None:
        """Discard only ephemeral viewer state after a series is explicitly removed."""
        for store in (
            self._viewer_state_store,
            self._presentation_state_store,
        ):
            stale_keys = [key for key in store if key[0] == series_id]
            for key in stale_keys:
                store.pop(key, None)
    
    def set_layout(self, rows: int, cols: int) -> bool:
        """设置网格布局

        注意：调用方（MainWindow._set_layout）应先调用 series_manager.set_layout()，
        再调用本方法。本方法不再重复调用 series_manager，避免二次清空绑定。

        Args:
            rows: 行数
            cols: 列数

        Returns:
            是否成功设置
        """
        logger.debug(f"[MultiViewerGrid.set_layout] 设置网格布局: {rows}x{cols}")

        try:
            if rows < 1 or rows > 3 or cols < 1 or cols > 4:
                logger.error(f"[MultiViewerGrid.set_layout] 无效的布局参数: {rows}x{cols}")
                return False

            old_layout = self._current_layout

            # 设置标志位，防止 series_manager 的 layout_changed 信号
            # 触发 _on_layout_changed 导致重复重建
            self._rebuilding = True

            self._current_layout = (rows, cols)
            self._current_layout_spec = LayoutSpec(
                kind="grid", rows=rows, columns=cols
            )
            self._active_splitters.clear()

            # 清除现有视图
            self._clear_grid()

            # 创建新的视图框架
            self._create_view_frames(rows, cols)

            self._rebuilding = False

            # 延迟执行自适应，等待布局引擎计算完最终尺寸
            self._fit_all_bound_views_to_window()

            logger.info(f"[MultiViewerGrid.set_layout] 网格布局设置成功: "
                       f"{old_layout} -> {self._current_layout}")
            self.layout_changed.emit(self._current_layout)

            return True

        except Exception as e:
            self._rebuilding = False
            logger.error(f"[MultiViewerGrid.set_layout] 设置网格布局失败: {e}", exc_info=True)
            return False
    
    def set_special_layout(self, layout_config: dict) -> bool:
        """设置特殊布局

        Args:
            layout_config: 特殊布局配置字典

        Returns:
            是否成功设置
        """
        logger.debug(f"[MultiViewerGrid.set_special_layout] 设置特殊布局: {layout_config}")

        # 保持 _rebuilding 为 True，防止内部 set_layout 重置后
        # layout_changed 信号触发 _on_layout_changed 导致重复重建
        saved_rebuilding = self._rebuilding
        self._rebuilding = True

        try:
            layout_type = layout_config.get('type', '')

            positions = self._get_special_view_positions(layout_config)
            if not positions:
                logger.error(f"[MultiViewerGrid.set_special_layout] 特殊布局没有有效视图槽位: {layout_type}")
                return False

            old_layout = self._current_layout
            self._current_layout = dict(layout_config)
            self._current_layout_spec = LayoutSpec.from_legacy(layout_config)
            self._active_splitters.clear()
            self._clear_grid()
            self._create_view_frames_for_positions(positions)

            # 等待视图创建完成
            QApplication.processEvents()

            # 然后重新排列为特殊布局
            success = self._arrange_special_layout(layout_config)

            if success:
                # 特殊布局重新排列了widget，需要再次延迟自适应
                self._fit_all_bound_views_to_window()
                logger.info(f"[MultiViewerGrid.set_special_layout] 特殊布局设置成功: {old_layout} -> {layout_type}")
                self.layout_geometry_changed.emit(self.current_layout_spec())
                return True
            else:
                logger.error(f"[MultiViewerGrid.set_special_layout] 特殊布局排列失败: {layout_type}")
                return False

        except Exception as e:
            logger.error(f"[MultiViewerGrid.set_special_layout] 设置特殊布局失败: {e}", exc_info=True)
            return False
        finally:
            self._rebuilding = saved_rebuilding
    
    def _get_equivalent_layout(self, layout_config: dict) -> Tuple[int, int]:
        """获取特殊布局的等效网格大小"""
        layout_type = layout_config.get('type', '')
        
        if layout_type == 'vertical_split':
            if layout_config.get('bottom_split', False):
                return (2, 2)  # 上+下左+下右
            else:
                return (2, 1)  # 上+下
        elif layout_type == 'horizontal_split':
            if layout_config.get('right_split', False):
                return (2, 2)  # 左+右上+右下
            else:
                return (1, 2)  # 左+右
        elif layout_type == 'triple_column_right_split':
            return (2, 2)  # 左+中+右上+右下
        elif layout_type == 'triple_column_middle_right_split':
            return (2, 3)  # 左+中上+中下+右上+右下
        else:
            return (2, 2)  # 默认

    def _get_special_view_positions(self, layout_config: dict) -> List[ViewPosition]:
        """获取特殊布局实际存在的视图槽位。"""
        layout_type = layout_config.get('type', '')

        if layout_type == 'vertical_split':
            if layout_config.get('bottom_split', False):
                return [ViewPosition.TOP_LEFT, ViewPosition.MIDDLE_LEFT, ViewPosition.MIDDLE_CENTER]
            return [ViewPosition.TOP_LEFT, ViewPosition.MIDDLE_LEFT]
        if layout_type == 'horizontal_split':
            if layout_config.get('right_split', False):
                return [ViewPosition.TOP_LEFT, ViewPosition.TOP_CENTER, ViewPosition.MIDDLE_CENTER]
            return [ViewPosition.TOP_LEFT, ViewPosition.TOP_CENTER]
        if layout_type == 'triple_column_right_split':
            return [ViewPosition.TOP_LEFT, ViewPosition.TOP_CENTER, ViewPosition.TOP_RIGHT, ViewPosition.MIDDLE_RIGHT]
        if layout_type == 'triple_column_middle_right_split':
            return [
                ViewPosition.TOP_LEFT,
                ViewPosition.TOP_CENTER,
                ViewPosition.MIDDLE_CENTER,
                ViewPosition.TOP_RIGHT,
                ViewPosition.MIDDLE_RIGHT,
            ]
        return []
    
    def _arrange_special_layout(self, layout_config: dict) -> bool:
        """排列特殊布局"""
        layout_type = layout_config.get('type', '')
        
        try:
            if layout_type == 'vertical_split':
                return self._arrange_vertical_split_layout(layout_config)
            elif layout_type == 'horizontal_split':
                return self._arrange_horizontal_split_layout(layout_config)
            elif layout_type in ['triple_column_right_split', 'triple_column_middle_right_split']:
                return self._arrange_triple_column_layout(layout_config)
            else:
                logger.warning(f"[MultiViewerGrid._arrange_special_layout] 未知的特殊布局类型: {layout_type}")
                return False
                
        except Exception as e:
            logger.error(f"[MultiViewerGrid._arrange_special_layout] 排列特殊布局失败: {e}", exc_info=True)
            return False
    
    def _arrange_vertical_split_layout(self, layout_config: dict) -> bool:
        """排列上下分割布局"""
        logger.debug("[MultiViewerGrid._arrange_vertical_split_layout] 排列上下分割布局")

        try:
            view_frames = list(self._view_frames.values())

            if len(view_frames) < 2:
                logger.warning("[MultiViewerGrid._arrange_vertical_split_layout] 视图框架数量不足")
                return False

            # 移除现有布局（不会创建新布局）
            self._clear_grid_layout()

            # 创建新布局并添加分割器
            new_layout = QVBoxLayout(self._grid_container)
            new_layout.setContentsMargins(0, 0, 0, 0)

            # 创建垂直分割器
            main_splitter = QSplitter(Qt.Vertical)
            self._register_splitter("main", main_splitter)

            # 设置分割比例
            top_ratio = layout_config.get('top_ratio', 0.6)

            # 添加上半部分
            main_splitter.addWidget(view_frames[0])

            if layout_config.get('bottom_split', False) and len(view_frames) >= 3:
                # 下半部分需要左右分割
                bottom_splitter = QSplitter(Qt.Horizontal)
                self._register_splitter("bottom", bottom_splitter)
                bottom_splitter.addWidget(view_frames[1])
                bottom_splitter.addWidget(view_frames[2])
                bottom_ratio = float(layout_config.get('bottom_ratio', 0.5))
                bottom_splitter.setSizes(
                    [int(1000 * bottom_ratio), int(1000 * (1.0 - bottom_ratio))]
                )

                main_splitter.addWidget(bottom_splitter)
            elif len(view_frames) >= 2:
                # 下半部分整体
                main_splitter.addWidget(view_frames[1])

            # 设置分割比例
            total_height = 1000
            top_height = int(total_height * top_ratio)
            bottom_height = total_height - top_height
            main_splitter.setSizes([top_height, bottom_height])

            new_layout.addWidget(main_splitter)

            logger.info("[MultiViewerGrid._arrange_vertical_split_layout] 上下分割布局排列完成")
            return True

        except Exception as e:
            logger.error(f"[MultiViewerGrid._arrange_vertical_split_layout] 排列上下分割布局失败: {e}", exc_info=True)
            return False
    
    def _arrange_horizontal_split_layout(self, layout_config: dict) -> bool:
        """排列左右分割布局"""
        logger.debug("[MultiViewerGrid._arrange_horizontal_split_layout] 排列左右分割布局")

        try:
            view_frames = list(self._view_frames.values())

            if len(view_frames) < 2:
                logger.warning("[MultiViewerGrid._arrange_horizontal_split_layout] 视图框架数量不足")
                return False

            # 移除现有布局（不会创建新布局）
            self._clear_grid_layout()

            # 创建新布局并添加分割器
            new_layout = QVBoxLayout(self._grid_container)
            new_layout.setContentsMargins(0, 0, 0, 0)

            # 创建水平分割器
            main_splitter = QSplitter(Qt.Horizontal)
            self._register_splitter("main", main_splitter)

            # 设置分割比例
            left_ratio = layout_config.get('left_ratio', 0.6)

            # 添加左半部分
            main_splitter.addWidget(view_frames[0])

            if layout_config.get('right_split', False) and len(view_frames) >= 3:
                # 右半部分需要上下分割
                right_splitter = QSplitter(Qt.Vertical)
                self._register_splitter("right", right_splitter)
                right_splitter.addWidget(view_frames[1])
                right_splitter.addWidget(view_frames[2])
                right_ratio = float(layout_config.get('right_ratio', 0.5))
                right_splitter.setSizes(
                    [int(1000 * right_ratio), int(1000 * (1.0 - right_ratio))]
                )

                main_splitter.addWidget(right_splitter)
            elif len(view_frames) >= 2:
                # 右半部分整体
                main_splitter.addWidget(view_frames[1])

            # 设置分割比例
            total_width = 1000
            left_width = int(total_width * left_ratio)
            right_width = total_width - left_width
            main_splitter.setSizes([left_width, right_width])

            new_layout.addWidget(main_splitter)

            logger.info("[MultiViewerGrid._arrange_horizontal_split_layout] 左右分割布局排列完成")
            return True

        except Exception as e:
            logger.error(f"[MultiViewerGrid._arrange_horizontal_split_layout] 排列左右分割布局失败: {e}", exc_info=True)
            return False
    
    def _arrange_triple_column_layout(self, layout_config: dict) -> bool:
        """排列三列布局"""
        logger.debug("[MultiViewerGrid._arrange_triple_column_layout] 排列三列布局")

        try:
            view_frames = list(self._view_frames.values())

            if len(view_frames) < 4:
                logger.warning("[MultiViewerGrid._arrange_triple_column_layout] 视图框架数量不足")
                return False

            # 移除现有布局（不会创建新布局）
            self._clear_grid_layout()

            # 创建新布局并添加分割器
            new_layout = QVBoxLayout(self._grid_container)
            new_layout.setContentsMargins(0, 0, 0, 0)

            # 创建主水平分割器
            main_splitter = QSplitter(Qt.Horizontal)
            self._register_splitter("main", main_splitter)

            # 设置分割比例
            left_ratio = layout_config.get('left_ratio', 0.33)
            middle_ratio = layout_config.get('middle_ratio', 0.34)
            1.0 - left_ratio - middle_ratio

            # 添加左列
            main_splitter.addWidget(view_frames[0])

            layout_type = layout_config.get('type', '')

            if layout_type == 'triple_column_middle_right_split' and len(view_frames) >= 5:
                # 中间和右边都分割
                # 中列分割
                middle_splitter = QSplitter(Qt.Vertical)
                self._register_splitter("middle", middle_splitter)
                middle_splitter.addWidget(view_frames[1])
                middle_splitter.addWidget(view_frames[2])
                middle_ratio_y = float(
                    layout_config.get('middle_split_ratio', 0.5)
                )
                middle_splitter.setSizes(
                    [
                        int(1000 * middle_ratio_y),
                        int(1000 * (1.0 - middle_ratio_y)),
                    ]
                )
                main_splitter.addWidget(middle_splitter)

                # 右列分割
                right_splitter = QSplitter(Qt.Vertical)
                self._register_splitter("right", right_splitter)
                right_splitter.addWidget(view_frames[3])
                right_splitter.addWidget(view_frames[4])
                right_ratio = float(
                    layout_config.get('right_split_ratio', 0.5)
                )
                right_splitter.setSizes(
                    [int(1000 * right_ratio), int(1000 * (1.0 - right_ratio))]
                )
                main_splitter.addWidget(right_splitter)
            else:
                # 只有右边分割
                # 中列整体
                main_splitter.addWidget(view_frames[1])

                # 右列分割
                if len(view_frames) >= 4:
                    right_splitter = QSplitter(Qt.Vertical)
                    self._register_splitter("right", right_splitter)
                    right_splitter.addWidget(view_frames[2])
                    right_splitter.addWidget(view_frames[3])
                    right_ratio = float(
                        layout_config.get('right_split_ratio', 0.5)
                    )
                    right_splitter.setSizes(
                        [
                            int(1000 * right_ratio),
                            int(1000 * (1.0 - right_ratio)),
                        ]
                    )
                    main_splitter.addWidget(right_splitter)

            # 设置分割比例
            total_width = 1000
            left_width = int(total_width * left_ratio)
            middle_width = int(total_width * middle_ratio)
            right_width = total_width - left_width - middle_width
            main_splitter.setSizes([left_width, middle_width, right_width])

            new_layout.addWidget(main_splitter)

            logger.info("[MultiViewerGrid._arrange_triple_column_layout] 三列布局排列完成")
            return True

        except Exception as e:
            logger.error(f"[MultiViewerGrid._arrange_triple_column_layout] 排列三列布局失败: {e}", exc_info=True)
            return False

    def _register_splitter(self, role: str, splitter: QSplitter) -> None:
        """Track a special-layout splitter without persisting Qt state blobs."""

        splitter.setObjectName(f"ReadingLayoutSplitter_{role}")
        self._active_splitters[role] = splitter
        splitter.splitterMoved.connect(
            lambda _position, _index: self._layout_geometry_timer.start()
        )

    @staticmethod
    def _splitter_ratio(splitter: Optional[QSplitter], index: int = 0) -> float:
        if splitter is None:
            return 0.5
        sizes = splitter.sizes()
        total = sum(max(0, value) for value in sizes)
        if total <= 0 or index >= len(sizes):
            return 0.5
        return max(0.05, min(0.95, float(sizes[index]) / float(total)))

    def _emit_layout_geometry_changed(self) -> None:
        if self._current_layout_spec.kind != "special":
            return
        spec = self.current_layout_spec()
        self._current_layout_spec = spec
        self._current_layout = spec.to_legacy()
        self.layout_geometry_changed.emit(spec)
    
    def _clear_grid_layout(self) -> None:
        """清除网格布局但保留视图框架

        注意：此方法只负责清理，不会创建新布局。
        调用方需要自行在 _grid_container 上创建所需的布局。
        """
        self._active_splitters.clear()
        old_layout = self._grid_container.layout()
        if old_layout:
            # 移除所有视图框架但不删除
            view_frames = list(self._view_frames.values())
            for view_frame in view_frames:
                old_layout.removeWidget(view_frame)
                view_frame.setParent(None)

            # 递归清理布局中残留的 splitter 等子 widget
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()

            # 删除旧布局（转移给临时 widget，随其销毁）
            QWidget().setLayout(old_layout)
    
    def _clear_grid(self) -> None:
        """清空网格

        安全地移除所有视图框架，无论它们是在 QGridLayout 还是 QSplitter 中。
        清理完成后重建 _grid_layout 供后续使用。
        """
        logger.debug("[MultiViewerGrid._clear_grid] 清空网格")

        # 清理所有视图框架的工具数据
        for view_frame in self._view_frames.values():
            if view_frame:
                view_frame._clear_tool_data()

        # 将视图框架从父组件中移除并标记删除
        for view_frame in self._view_frames.values():
            view_frame.setParent(None)
            view_frame.deleteLater()

        self._view_frames.clear()
        self._maximized_view_id = None

        # 销毁 _grid_container 上的旧布局（可能是 QGridLayout 或 QVBoxLayout+QSplitter）
        old_layout = self._grid_container.layout()
        if old_layout:
            # 递归清理布局中残留的 splitter 等子 widget
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
            QWidget().setLayout(old_layout)

        # 重建干净的 QGridLayout
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(2)

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
                view_frame.set_privacy_mode(self._privacy_enabled)

                # 传播同步管理器到 ImageViewer
                if self._sync_manager and view_frame.image_viewer:
                    view_frame.image_viewer.sync_manager = self._sync_manager

                # 连接信号
                view_frame.view_activated.connect(self._on_view_frame_activated)
                view_frame.view_clicked.connect(self._on_view_frame_clicked)
                view_frame.drop_requested.connect(self._on_view_frame_drop_requested) # 连接拖拽信号
                view_frame.maximize_requested.connect(self.toggle_maximize_view)
                view_frame.set_compact_mode(rows * cols > 1)
                
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

    def _create_view_frames_for_positions(self, positions: List[ViewPosition]) -> None:
        """按实际槽位创建视图框架，用于非规则预设布局。"""
        logger.debug(f"[MultiViewerGrid._create_view_frames_for_positions] 创建视图框架: {positions}")

        view_ids = self._series_manager.get_all_view_ids()
        for index, position in enumerate(positions):
            if index < len(view_ids):
                view_id = view_ids[index]
            else:
                view_id = f"view_{position.value[0]}_{position.value[1]}"

            view_frame = ViewFrame(view_id, position, self)
            view_frame.set_privacy_mode(self._privacy_enabled)

            if self._sync_manager and view_frame.image_viewer:
                view_frame.image_viewer.sync_manager = self._sync_manager

            view_frame.view_activated.connect(self._on_view_frame_activated)
            view_frame.view_clicked.connect(self._on_view_frame_clicked)
            view_frame.drop_requested.connect(self._on_view_frame_drop_requested)
            view_frame.maximize_requested.connect(self.toggle_maximize_view)
            view_frame.set_compact_mode(len(positions) > 1)

            self._grid_layout.addWidget(view_frame, position.value[0], position.value[1])
            self._view_frames[view_id] = view_frame

            binding = self._series_manager.get_view_binding(view_id)
            if binding:
                view_frame.set_active(binding.is_active)
                if binding.series_id:
                    self._bind_series_to_view_frame(view_frame, binding.series_id)
            elif index == 0:
                view_frame.set_active(True)
                self._series_manager.set_active_view(view_id)

            logger.debug(f"[MultiViewerGrid._create_view_frames_for_positions] "
                         f"创建视图框架: {view_id} at {position.value}")

        logger.debug(f"[MultiViewerGrid._create_view_frames_for_positions] "
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
                view_frame.set_privacy_mode(
                    self._privacy_enabled,
                    self._privacy_alias_for(series_id),
                )
                
                logger.debug(f"[MultiViewerGrid._bind_series_to_view_frame] "
                           f"绑定成功: {view_frame.view_id} -> {series_id}")
            else:
                if series_info:
                    view_frame.show_loading_state(
                        series_id,
                        self._format_series_description(series_info),
                    )
                    view_frame.set_privacy_mode(
                        self._privacy_enabled,
                        self._privacy_alias_for(series_id),
                    )
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
            return f"{t('multiviewergrid.series')} {series_info.series_number}"
    
    def _on_layout_changed(self, layout: Tuple[int, int]) -> None:
        """处理布局变更事件（由 series_manager.layout_changed 信号触发）

        当 set_layout() 正在执行时（_rebuilding=True），跳过重建，
        因为 set_layout() 自身已经在重建网格了。
        """
        if self._rebuilding:
            return

        logger.debug(f"[MultiViewerGrid._on_layout_changed] 处理布局变更: {layout}")

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
    
    def _on_series_data_ready(self, series_id: str) -> None:
        """当序列数据加载完成后，重新绑定已关联但尚未显示图像的视图"""
        for view_id, view_frame in self._view_frames.items():
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id == series_id:
                image_model = self._series_manager.get_series_model(series_id)
                if image_model and not view_frame.has_bound_model():
                    logger.debug(f"[MultiViewerGrid._on_series_data_ready] "
                                f"数据就绪，重新绑定: view_id={view_id}, series_id={series_id}")
                    self._bind_series_to_view_frame(view_frame, series_id)

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

    @staticmethod
    def _restore_view_geometry(viewer: ImageViewer) -> None:
        """Refit fit-mode panes and preserve explicit pan/zoom panes."""
        if viewer.presentation_state.fit_mode:
            viewer.fit_to_window()
        else:
            viewer.set_presentation_state(viewer.presentation_state)

    def toggle_maximize_view(self, view_id: str) -> None:
        """Double-click a pane to maximize it; double-click again to restore."""
        target = self._view_frames.get(view_id)
        if target is None:
            return
        restoring = self._maximized_view_id == view_id
        self._maximized_view_id = None if restoring else view_id
        compact = len(self._view_frames) > 1
        for frame_id, frame in self._view_frames.items():
            frame.setVisible(restoring or frame_id == view_id)
            frame.set_compact_mode(compact if restoring else False)
        if not restoring:
            self._series_manager.set_active_view(view_id)
        QTimer.singleShot(
            0,
            lambda: self._restore_view_geometry(target.image_viewer)
            if target.image_viewer and target.series_id
            else None,
        )

    def is_view_maximized(self, view_id: Optional[str] = None) -> bool:
        """Return whether any pane, or a specific pane, is maximized."""
        if view_id is None:
            return self._maximized_view_id is not None
        return self._maximized_view_id == view_id

    def _on_view_frame_drop_requested(self, view_id: str, series_id: str) -> None:
        """处理视图框架的拖拽请求"""
        logger.debug(f"[MultiViewerGrid._on_view_frame_drop_requested] 视图框架拖拽请求: view_id={view_id}, series_id={series_id}")
        self._series_manager.set_active_view(view_id)
        self.binding_requested.emit(view_id, series_id)
    
    # 查询方法
    
    def get_current_layout(self) -> object:
        """获取当前布局"""
        return self._current_layout

    def current_layout_spec(self) -> LayoutSpec:
        """Return the current layout including live special splitter ratios."""

        spec = self._current_layout_spec
        if spec.kind == "grid":
            return spec
        main = self._active_splitters.get("main")
        nested_right = self._active_splitters.get("right")
        nested_middle = self._active_splitters.get("middle")
        nested_bottom = self._active_splitters.get("bottom")
        if spec.special_type == "vertical_split":
            ratios = (
                self._splitter_ratio(main),
                self._splitter_ratio(nested_bottom),
            )
        elif spec.special_type == "horizontal_split":
            ratios = (
                self._splitter_ratio(main),
                self._splitter_ratio(nested_right),
            )
        elif spec.special_type == "triple_column_right_split":
            main_sizes = main.sizes() if main is not None else []
            total = sum(main_sizes)
            left = main_sizes[0] / total if total and len(main_sizes) >= 3 else 0.33
            middle = (
                main_sizes[1] / total if total and len(main_sizes) >= 3 else 0.34
            )
            ratios = (
                max(0.05, min(0.95, left)),
                max(0.05, min(0.95, middle)),
                self._splitter_ratio(nested_right),
            )
        else:
            main_sizes = main.sizes() if main is not None else []
            total = sum(main_sizes)
            left = main_sizes[0] / total if total and len(main_sizes) >= 3 else 0.33
            middle = (
                main_sizes[1] / total if total and len(main_sizes) >= 3 else 0.34
            )
            ratios = (
                max(0.05, min(0.95, left)),
                max(0.05, min(0.95, middle)),
                self._splitter_ratio(nested_middle),
                self._splitter_ratio(nested_right),
            )
        return LayoutSpec(
            kind="special",
            special_type=spec.special_type,
            ratios=tuple(float(value) for value in ratios),
        )

    def apply_layout_spec(self, spec: LayoutSpec) -> bool:
        """Apply a stable spec after the caller updates the series manager."""

        if spec.kind == "grid":
            return self.set_layout(spec.rows, spec.columns)
        return self.set_special_layout(spec.to_legacy())
    
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

    def apply_runtime_settings(self) -> None:
        """应用设置面板中可即时生效的多视图显示选项。"""
        for view_frame in self._view_frames.values():
            if hasattr(view_frame, "apply_runtime_settings"):
                view_frame.apply_runtime_settings()
    
    def _fit_all_bound_views_to_window(self) -> None:
        """为所有绑定了序列的视图自适应窗格大小

        使用 QTimer.singleShot(0) 延迟执行，确保 Qt 布局引擎已完成
        几何计算后再调用 fitInView，否则视口尺寸仍是旧值。
        """
        QTimer.singleShot(0, self._do_fit_all_bound_views)

    def _do_fit_all_bound_views(self) -> None:
        """实际执行自适应窗格大小（由 QTimer 延迟调用）"""
        try:
            for view_frame in self._view_frames.values():
                if view_frame and view_frame.series_id and view_frame.image_viewer:
                    viewer = view_frame.image_viewer
                    self._restore_view_geometry(viewer)
                    if viewer.presentation_state.fit_mode:
                        # If the layout is still settling, refit once on resize.
                        viewer._fit_pending = True
                    else:
                        viewer._fit_pending = False
        except Exception as e:
            logger.error(f"[MultiViewerGrid._do_fit_all_bound_views] 自适应失败: {e}", exc_info=True)

    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                self._theme_manager = main_window.theme_manager
                self._theme_manager.register_component(self)
                logger.debug("[MultiViewerGrid._register_to_theme_manager] 成功注册到主题管理器")
                
                # 立即应用当前主题
                current_theme = self._theme_manager.get_current_theme()
                self.update_theme(current_theme)
            else:
                logger.debug("[MultiViewerGrid._register_to_theme_manager] 未找到主题管理器")
        except Exception as e:
            logger.error(f"[MultiViewerGrid._register_to_theme_manager] 注册主题管理器失败: {e}", exc_info=True)
    
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[MultiViewerGrid.update_theme] 开始更新主题: {theme_name} (ID: {id(self)})")
        try:
            # 更新网格容器背景色
            if theme_name == 'light':
                bg_color = "#f0f0f0"
                stylesheet = """
                    QWidget {
                        background-color: #f0f0f0;
                    }
                """
            else:  # dark theme
                bg_color = "#2b2b2b"
                stylesheet = """
                    QWidget {
                        background-color: #2b2b2b;
                    }
                """
            
            logger.info(f"[MultiViewerGrid.update_theme] 设置背景色: {bg_color}")
            self.setStyleSheet(stylesheet)
            
            # 更新所有视图框架的主题
            logger.info(f"[MultiViewerGrid.update_theme] 更新 {len(self._view_frames)} 个视图框架的主题")
            for i, (view_id, view_frame) in enumerate(self._view_frames.items()):
                logger.info(f"[MultiViewerGrid.update_theme] 更新视图框架 {i+1}/{len(self._view_frames)}: {view_id}")
                if hasattr(view_frame, 'update_theme'):
                    view_frame.update_theme(theme_name)
                else:
                    logger.warning(f"[MultiViewerGrid.update_theme] 视图框架 {view_id} 没有update_theme方法")
            
            logger.info(f"[MultiViewerGrid.update_theme] 主题更新完成: {theme_name}")
        except Exception as e:
            logger.error(f"[MultiViewerGrid.update_theme] 主题更新失败: {e}", exc_info=True)
