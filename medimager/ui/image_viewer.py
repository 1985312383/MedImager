#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像查看器控件
核心的 2D 图像显示控件，基于 QGraphicsView 实现
"""

from typing import Dict, Optional, TYPE_CHECKING
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QWidget, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, QPointF, QRect, QRectF, QPoint
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QWheelEvent, QMouseEvent, QCursor,
    QColor, QPen, QFont, QFontMetrics, QTransform,
)
import math
from medimager.utils.logger import get_logger
from medimager.core.image_data_model import ImageDataModel
from medimager.ui.tools.base_tool import BaseTool
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI
from medimager.core.analysis import calculate_roi_statistics
from medimager.core.view_presentation_state import (
    InterpolationMode,
    ViewPresentationState,
    pixel_value_for_view,
)
from medimager.ui.widgets.roi_stats_box import draw_stats_box, _get_stats_box_settings
from medimager.utils.theme_colors import qcolor_from_theme
from medimager.utils.theme_manager import MEDICAL_CANVAS_COLOR, normalize_ui_theme
from medimager.utils.i18n import t
from ..utils.settings import get_settings_manager

if TYPE_CHECKING:
    from medimager.core.image_data_model import ImageDataModel
    from medimager.ui.tools.base_tool import BaseTool

from medimager.ui.widgets.magnifier import MagnifierWidget
from medimager.ui.tools.default_tool import DefaultTool


class ImageViewer(QGraphicsView):
    """图像查看器控件
    
    基于 QGraphicsView 的图像显示控件，职责是显示由 ImageDataModel 处理好的图像。
    它不包含任何图像处理逻辑（如窗宽窗位），只负责显示和用户交互。
    """
    
    # 信号定义
    pixel_value_changed = Signal(int, int, object)  # 灰度 float 或 RGB(A) 元组
    cursor_left_image = Signal() # 当光标离开图像区域时发出
    zoom_changed = Signal(float)  # 缩放比例变化信号
    cursor_position_changed = Signal(QPointF)  # 原始图像坐标，用于交叉参考同步
    interaction_started = Signal()  # 任意会改变当前视图状态的用户交互
    series_drop_requested = Signal(str)
    series_drag_active = Signal(bool)
    presentation_changed = Signal(object)
    slice_changed = Signal(int)
    window_changed = Signal(float, float)
    maximize_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.model: Optional[ImageDataModel] = None
        self.current_tool: Optional[BaseTool] = None
        self.presentation_state = ViewPresentationState()

        # 几何变换只作用于 QGraphicsView。图像和场景标注因而共享同一
        # 坐标系，旋转/翻转后鼠标命中、像素读取和绘制不会发生偏移。
        self._flip_h = False
        self._flip_v = False
        self._rotation = 0  # 0, 90, 180, 270
        self._inverted = False
        self._view_zoom = 1.0
        self.zoom_factor = 1.0  # 向后兼容现有调用
        self._pixel_aspect_x = 1.0
        self._pixel_aspect_y = 1.0

        # 同步相关：由 ViewFrame 设置
        self._view_id: Optional[str] = None
        self._sync_manager = None  # SyncManager 实例

        self.image_item: Optional[QGraphicsPixmapItem] = None
        self._init_scene()
        self._init_viewer_settings()

        self._panning = False
        self._pan_start_pos = QPoint()
        
        # 缓存的QImage，避免每次鼠标移动都调用pixmap.toImage()
        self._cached_qimage: Optional[QImage] = None

        # 延迟自适应标志：布局切换后在下次 resizeEvent 中执行 fit_to_window
        self._fit_pending = False
        
        # 自定义光标
        self.cross_cursor = self._create_cross_cursor()
        
        # 放大镜
        self.magnifier = MagnifierWidget(self)
        self.magnifier.hide()
        self._magnifier_key_held = False
        
        # 设置视图属性
        self._setup_view()
        
        # 启用拖拽接收
        self.setAcceptDrops(True)
        
        # 设置默认工具
        self.set_tool(DefaultTool(self))
        
        # 状态：用于跟踪悬停的ROI和鼠标位置，以显示统计信息
        self.hovered_roi_index: Optional[int] = None
        self.last_mouse_scene_pos: QPointF = QPointF()
        # 混合表示：QRectF 左上角为 scene 坐标，宽高为固定 viewport 像素。
        # scene 锚点必须保留小数，否则高倍率下逐像素拖动会被反复取整吞掉。
        self.stats_box_positions: dict[str, QRectF] = {}
        self.annotation_label_offsets: Dict[str, QPointF] = {}
        self._annotation_label_rects: Dict[str, tuple[str, QRect]] = {}
        self._roi_stats_cache: dict[str, tuple[object, object]] = {}
        self._corner_overlay_info: Dict[str, str] = {}
        self._orientation_override: Optional[Dict[str, str]] = None
        
        # 测量线状态：用于在工具切换后保持测量线显示
        self.measurement_start_point: Optional[QPointF] = None
        self.measurement_end_point: Optional[QPointF] = None
        self.measurement_distance: Optional[float] = None
        self.measurement_unit: str = "mm"
        
        # 测量线拖拽状态
        self._measurement_dragging = False
        self._measurement_drag_start_pos = QPointF()
        self._measurement_drag_offset = QPointF()
        
        # 交叉参考线状态
        self._cross_reference_enabled = False
        self._cross_reference_pos = QPointF(-1, -1)  # 无效位置表示不显示
        self._cross_reference_color = qcolor_from_theme(
            normalize_ui_theme({})["reference_line_color"]
        )

        # 缓存的测量线主题设置，避免每次绘制都从文件加载
        self._measurement_theme_cache = None
        
        # 初始化设置管理器
        self._init_settings()
        self._apply_interpolation_setting()
        
        # 主题管理器注册
        self._theme_manager = None
        self._register_to_theme_manager()

    def _init_settings(self):
        """初始化设置管理器"""
        try:
            self.settings_manager = get_settings_manager()
        except Exception as e:
            self.logger.warning(f"初始化设置管理器失败: {e}")
            self.settings_manager = None
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                self._theme_manager = main_window.theme_manager
                self._theme_manager.register_component(self)
                self.logger.debug("[ImageViewer._register_to_theme_manager] 成功注册到主题管理器")
                
                # 立即应用当前主题
                current_theme = self._theme_manager.get_current_theme()
                self.update_theme(current_theme)
            else:
                self.logger.debug("[ImageViewer._register_to_theme_manager] 未找到主题管理器")
        except Exception as e:
            self.logger.error(f"[ImageViewer._register_to_theme_manager] 注册主题管理器失败: {e}", exc_info=True)
    
    def update_theme(self, theme_name: str) -> None:
        """Apply semantic UI tokens while keeping the imaging canvas neutral."""
        self.logger.info(
            "[ImageViewer.update_theme] 开始更新主题: %s (ID: %s)",
            theme_name,
            id(self),
        )
        try:
            tokens = (
                self._theme_manager.get_theme_tokens(theme_name)
                if self._theme_manager is not None
                else normalize_ui_theme({})
            )
            canvas_color = str(tokens.get("canvas_color", MEDICAL_CANVAS_COLOR))
            self.setStyleSheet(
                f"QGraphicsView {{ background-color: {canvas_color}; border: none; }}"
            )
            self._cross_reference_color = qcolor_from_theme(
                str(tokens.get("reference_line_color", "#E757FF"))
            )
            self.logger.info(
                "[ImageViewer.update_theme] 设置医学画布/参考线颜色: %s / %s",
                canvas_color,
                tokens.get("reference_line_color"),
            )
            if hasattr(self, "magnifier") and self.magnifier:
                if hasattr(self.magnifier, "update_theme"):
                    self.magnifier.update_theme(theme_name)
            self._measurement_theme_cache = None
            self.viewport().update()
            self.logger.info("[ImageViewer.update_theme] 主题更新完成: %s", theme_name)
        except Exception as error:
            self.logger.error(
                "[ImageViewer.update_theme] 主题更新失败: %s", error, exc_info=True
            )

    def _setup_view(self) -> None:
        """设置视图属性"""
        self.setDragMode(QGraphicsView.NoDrag) # 拖拽模式由工具类控制
        self.setRenderHint(QPainter.Antialiasing, False)
        self._apply_interpolation_setting()
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(
            f"QGraphicsView {{ background-color: {MEDICAL_CANVAS_COLOR}; border: none; }}"
        )
        self.setFrameShape(QFrame.NoFrame)

    def _apply_interpolation_setting(self) -> None:
        """按设置应用图像缩放插值策略。"""
        try:
            settings = getattr(self, "settings_manager", None)
            mode = settings.get_setting("display.interpolation_mode", None) if settings else None
            if mode is None:
                smooth = settings.get_setting("display.smooth_interpolation", True) if settings else True
                if isinstance(smooth, str):
                    smooth = smooth.lower() in ("1", "true", "yes", "on")
                mode = InterpolationMode.ADAPTIVE if smooth else InterpolationMode.PIXEL_EXACT
            self.set_interpolation_mode(mode, emit=False)
        except Exception:
            self.set_interpolation_mode(InterpolationMode.ADAPTIVE, emit=False)

    def set_interpolation_mode(self, mode: object, *, emit: bool = True) -> None:
        """Set adaptive, smooth, or pixel-exact image sampling."""
        self.presentation_state.interpolation = InterpolationMode.coerce(mode)
        self._apply_item_interpolation()
        if emit:
            self.presentation_changed.emit(self.presentation_state)

    def _apply_item_interpolation(self) -> None:
        mode = self.presentation_state.interpolation
        smooth = mode == InterpolationMode.SMOOTH or (
            mode == InterpolationMode.ADAPTIVE and self._view_zoom < 1.0
        )
        self.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
        if self.image_item is not None:
            self.image_item.setTransformationMode(
                Qt.SmoothTransformation if smooth else Qt.FastTransformation
            )
            self.image_item.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)

    def _configure_image_item(self) -> None:
        if self.image_item is None:
            return
        self.image_item.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self._apply_item_interpolation()

    def apply_runtime_settings(self) -> None:
        """重新应用设置面板中可即时生效的查看器设置。"""
        self._apply_interpolation_setting()
        self._apply_viewport_backend()
        self.viewport().update()

    def _apply_viewport_backend(self) -> None:
        """Optionally use OpenGL; keep the stable QWidget backend by default."""
        settings = getattr(self, "settings_manager", None)
        value = settings.get_setting("display.use_opengl_viewport", False) if settings else False
        if isinstance(value, str):
            value = value.lower() in ("1", "true", "yes", "on")
        requested = bool(value)
        current_is_gl = self.viewport().__class__.__name__ == "QOpenGLWidget"
        try:
            if requested and not current_is_gl:
                from PySide6.QtOpenGLWidgets import QOpenGLWidget
                self.setViewport(QOpenGLWidget(self))
                current_is_gl = True
            elif not requested and current_is_gl:
                self.setViewport(QWidget(self))
                current_is_gl = False
        except Exception as error:
            self.logger.warning(f"OpenGL viewport unavailable; using QWidget: {error}")
            if self.viewport().__class__.__name__ == "QOpenGLWidget":
                self.setViewport(QWidget(self))
            current_is_gl = False
        self.setViewportUpdateMode(
            QGraphicsView.FullViewportUpdate
            if current_is_gl
            else QGraphicsView.BoundingRectViewportUpdate
        )
        
    def _create_cross_cursor(self) -> QCursor:
        """创建一个洋红色的十字光标"""
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        pen = QPen(QColor("magenta"))
        pen.setWidth(1)
        painter.setPen(pen)
        
        # 绘制十字
        center = size // 2
        painter.drawLine(center, 0, center, size)
        painter.drawLine(0, center, size, center)
        
        painter.end()
        
        return QCursor(pixmap, hotX=center, hotY=center)

    def _init_scene(self) -> None:
        """初始化场景"""
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.image_item = None

    def _init_viewer_settings(self) -> None:
        """初始化视图设置"""
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)

    def set_tool(self, tool: Optional[BaseTool]):
        """设置并激活当前工具"""
        self.logger.info(f"[ImageViewer.set_tool] 设置工具: {type(tool).__name__ if tool else 'None'}")
        
        if self.current_tool:
            self.current_tool.deactivate()
            self.logger.info(f"[ImageViewer.set_tool] 停用旧工具: {type(self.current_tool).__name__}")

        # 选择属于当前交互工具；切换工具时统一清除三类标注选择，
        # 避免不可见的残留选择在另一工具中被 Delete 误删。
        if self.model:
            self.model.clear_annotation_selection()
            
        self.current_tool = tool
        
        if self.current_tool:
            self.current_tool.activate()
            self.logger.info(f"[ImageViewer.set_tool] 激活新工具: {type(self.current_tool).__name__}")
        
        self.logger.info(f"[ImageViewer.set_tool] 工具设置完成: {type(tool).__name__ if tool else 'None'}")

    def set_model(
        self,
        model: Optional[ImageDataModel],
        *,
        initialize_state: bool = True,
    ) -> None:
        """设置数据模型并更新视图"""
        previous_model = self.model
        self.model = model
        self._roi_stats_cache.clear()
        if model is not None and initialize_state and model is not previous_model:
            state = ViewPresentationState.from_model(
                model,
                interpolation=self.presentation_state.interpolation,
            )
            self.set_presentation_state(state)
        if model is not None and self._update_pixel_aspect_from_model():
            self._rebuild_view_transform()

    @property
    def current_slice_index(self) -> int:
        return int(self.presentation_state.slice_index)

    @property
    def window_width(self) -> float:
        return float(self.presentation_state.window_width)

    @property
    def window_level(self) -> float:
        return float(self.presentation_state.window_level)

    def set_presentation_state(self, state: ViewPresentationState) -> None:
        """Attach persistent per-view state and restore its geometry."""
        self.presentation_state = state
        count = self.model.get_slice_count() if self.model is not None else None
        state.clamp(count)
        saved_pan_center = QPointF(state.pan_center)
        self._flip_h = state.flip_horizontal
        self._flip_v = state.flip_vertical
        self._rotation = state.rotation
        self._inverted = state.inverted
        self._view_zoom = state.zoom
        self.zoom_factor = state.zoom
        self._apply_item_interpolation()
        self._rebuild_view_transform(state.zoom, emit=False)
        if not state.fit_mode and not saved_pan_center.isNull():
            self.centerOn(saved_pan_center)
            state.pan_center = saved_pan_center
        self.viewport().update()

    def set_view_slice(self, slice_index: int, *, emit: bool = True) -> bool:
        if self.model is None or self.model.get_slice_count() <= 0:
            return False
        clamped = max(0, min(int(slice_index), self.model.get_slice_count() - 1))
        if clamped == self.presentation_state.slice_index:
            return True
        self.presentation_state.slice_index = clamped
        self._roi_stats_cache.clear()
        if self._update_pixel_aspect_from_model():
            self._rebuild_view_transform(emit=False)
        if emit:
            self.slice_changed.emit(clamped)
            self.presentation_changed.emit(self.presentation_state)
        return True

    def set_view_window(
        self, window_width: float, window_level: float, *, emit: bool = True
    ) -> None:
        width = max(1.0, float(window_width))
        level = float(window_level)
        changed = (
            not math.isclose(width, self.presentation_state.window_width)
            or not math.isclose(level, self.presentation_state.window_level)
            or self.presentation_state.use_dicom_voi_lut
        )
        self.presentation_state.window_width = width
        self.presentation_state.window_level = level
        self.presentation_state.use_dicom_voi_lut = False
        self.presentation_state.voi_lut_index = None
        if changed and emit:
            self.window_changed.emit(width, level)
            self.presentation_changed.emit(self.presentation_state)

    def set_view_voi_lut(
        self, enabled: bool, index: Optional[int] = None, *, emit: bool = True
    ) -> None:
        self.presentation_state.use_dicom_voi_lut = bool(enabled)
        self.presentation_state.voi_lut_index = index if enabled else None
        if emit:
            self.presentation_changed.emit(self.presentation_state)

    def set_corner_overlay_info(self, **values: object) -> None:
        for key, value in values.items():
            key = str(key)
            if value in (None, ""):
                self._corner_overlay_info.pop(key, None)
            else:
                self._corner_overlay_info[key] = str(value)
        self.viewport().update()

    def set_orientation_markers(self, markers: Optional[Dict[str, str]]) -> None:
        self._orientation_override = dict(markers) if markers else None
        self.viewport().update()

    def set_magnifier_enabled(self, enabled: bool) -> None:
        self.presentation_state.magnifier_enabled = bool(enabled)
        if not enabled and not self._magnifier_key_held:
            self.magnifier.hide()
        elif self.underMouse():
            self.magnifier.show()

    def annotation_label_offset(self, annotation_id: str) -> QPointF:
        return QPointF(self.annotation_label_offsets.get(annotation_id, QPointF()))

    def set_annotation_label_offset(self, annotation_id: str, offset: QPointF) -> None:
        self.annotation_label_offsets[str(annotation_id)] = QPointF(offset)
        self.viewport().update()

    def clear_annotation_label_offset(self, annotation_id: str) -> None:
        self.annotation_label_offsets.pop(str(annotation_id), None)
        self.viewport().update()

    def hit_test_annotation_label(self, viewport_pos: QPoint) -> Optional[tuple[str, str]]:
        """Return the top-most persistent annotation label under a viewport point."""
        point = QPoint(viewport_pos)
        for annotation_id, (kind, rect) in reversed(
            tuple(self._annotation_label_rects.items())
        ):
            if rect.contains(point):
                return kind, annotation_id
        return None

    def move_annotation_label(self, annotation_id: str, delta: QPoint) -> None:
        """Move a label in device pixels so its offset is zoom-independent."""
        key = str(annotation_id)
        self.annotation_label_offsets[key] = (
            self.annotation_label_offsets.get(key, QPointF()) + QPointF(delta)
        )
        self.viewport().update()

    @property
    def view_id(self) -> Optional[str]:
        """获取关联的视图ID"""
        return self._view_id

    @view_id.setter
    def view_id(self, value: str) -> None:
        self._view_id = value

    @property
    def sync_manager(self):
        """获取同步管理器"""
        return self._sync_manager

    @sync_manager.setter
    def sync_manager(self, value) -> None:
        self._sync_manager = value

    def display_qimage(self, q_image: Optional[QImage]) -> None:
        """显示 QImage

        此方法是该控件的核心入口，由外部（如MainWindow）调用，
        传入已经经过窗宽窗位等处理的 QImage。

        Args:
            q_image: 要显示的 QImage 对象，如果为 None，则清空视图。
        """
        if q_image is None or q_image.isNull():
            if self.image_item:
                self.scene.removeItem(self.image_item)
                self.image_item = None
            self.scene.setSceneRect(QRectF())
            self._cached_qimage = None
            self.magnifier.hide()
            return

        aspect_changed = self._update_pixel_aspect_from_model()
        q_image = self._apply_view_transforms(q_image)
        pixmap = QPixmap.fromImage(q_image)
        if self.image_item is None:
            self.image_item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(self.image_item)
            self._configure_image_item()
        else:
            self.image_item.setPixmap(pixmap)

        self._cached_qimage = None  # 使缓存失效，下次鼠标移动时重建
        self.scene.setSceneRect(pixmap.rect())
        if aspect_changed:
            self._rebuild_view_transform()

    def _apply_view_transforms(self, q_image: QImage) -> QImage:
        """应用像素级反色；几何变换由视图矩阵统一处理。"""
        if self._inverted:
            q_image = q_image.copy()
            q_image.invertPixels()
        return q_image

    def _read_pixel_spacing(self) -> Optional[tuple[float, float]]:
        """读取当前帧的 (row, column) PixelSpacing，非法值返回 None。"""
        if not self.model:
            return None
        spacing = None
        getter = getattr(self.model, "get_pixel_spacing", None)
        if callable(getter):
            try:
                spacing = getter(self.current_slice_index)
            except TypeError:
                spacing = getter()
            except Exception:
                spacing = None
        if spacing is None:
            metadata = getattr(self.model, "metadata", {}) or {}
            spacing = metadata.get("PixelSpacing") or metadata.get("Pixel Spacing")
        try:
            row, column = float(spacing[0]), float(spacing[1])
            if math.isfinite(row) and math.isfinite(column) and row > 0 and column > 0:
                return row, column
        except (TypeError, ValueError, IndexError):
            pass
        return None

    def _update_pixel_aspect_from_model(self) -> bool:
        """将物理像素比例归一化到视图矩阵，返回比例是否发生变化。"""
        spacing = self._read_pixel_spacing()
        if spacing:
            row, column = spacing
            base = min(row, column)
            new_x, new_y = column / base, row / base
        else:
            new_x = new_y = 1.0
        changed = (
            not math.isclose(new_x, self._pixel_aspect_x, rel_tol=1e-6)
            or not math.isclose(new_y, self._pixel_aspect_y, rel_tol=1e-6)
        )
        self._pixel_aspect_x, self._pixel_aspect_y = new_x, new_y
        return changed

    def _orientation_transform(self, zoom: float) -> QTransform:
        """Build the absolute rotation, flip, zoom and optional physical aspect."""
        transform = QTransform()
        if self._rotation:
            transform.rotate(self._rotation)
        aspect_x = (
            self._pixel_aspect_x
            if self.presentation_state.use_physical_pixel_aspect
            else 1.0
        )
        aspect_y = (
            self._pixel_aspect_y
            if self.presentation_state.use_physical_pixel_aspect
            else 1.0
        )
        transform.scale(
            (-1.0 if self._flip_h else 1.0) * zoom * aspect_x,
            (-1.0 if self._flip_v else 1.0) * zoom * aspect_y,
        )
        return transform

    def _update_zoom_from_transform(self) -> float:
        """Recover user zoom independently from orientation and pixel aspect."""
        transform = self.transform()
        aspect_x = self._pixel_aspect_x if self.presentation_state.use_physical_pixel_aspect else 1.0
        aspect_y = self._pixel_aspect_y if self.presentation_state.use_physical_pixel_aspect else 1.0
        x_scale = math.hypot(transform.m11(), transform.m12()) / max(aspect_x, 1e-12)
        y_scale = math.hypot(transform.m21(), transform.m22()) / max(aspect_y, 1e-12)
        self._view_zoom = self._clamp_zoom(
            math.sqrt(max(x_scale, 1e-12) * max(y_scale, 1e-12))
        )
        self.zoom_factor = self._view_zoom
        self.presentation_state.zoom = self._view_zoom
        self.presentation_state.pan_center = self.mapToScene(self.viewport().rect().center())
        self._apply_item_interpolation()
        return self._view_zoom


    @staticmethod
    def _clamp_zoom(zoom: float) -> float:
        return max(ViewPresentationState.MIN_ZOOM, min(ViewPresentationState.MAX_ZOOM, float(zoom)))
    def effective_scale(self) -> float:
        """返回屏幕上每个场景像素的最小缩放，始终为正数。"""
        transform = self.transform()
        x_scale = math.hypot(transform.m11(), transform.m12())
        y_scale = math.hypot(transform.m21(), transform.m22())
        return max(1e-6, min(x_scale, y_scale))

    def get_view_zoom(self) -> float:
        """获取不受旋转、翻转和 PixelSpacing 影响的用户缩放值。"""
        return self._view_zoom

    def _rebuild_view_transform(self, zoom: Optional[float] = None, emit: bool = True) -> None:
        """重建绝对矩阵，同时保持当前场景中心。"""
        if zoom is None:
            zoom = self._view_zoom
        zoom = self._clamp_zoom(zoom)
        center = self.mapToScene(self.viewport().rect().center())
        self.setTransform(self._orientation_transform(zoom))
        self.centerOn(center)
        self._view_zoom = zoom
        self.zoom_factor = zoom
        self.presentation_state.zoom = zoom
        self.presentation_state.pan_center = QPointF(center)
        self._apply_item_interpolation()
        if emit:
            self.zoom_changed.emit(zoom)
        self.viewport().update()


    def set_view_zoom(self, zoom: float, *, emit: bool = True) -> None:
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform(self._clamp_zoom(zoom), emit=emit)

    def set_synced_view_state(
        self,
        zoom_factor: float,
        center_scene: Optional[QPointF] = None,
        sync_zoom: bool = True,
        sync_pan: bool = True,
    ) -> None:
        """应用同步状态，但保留目标视图自己的旋转、翻转和物理比例。"""
        if sync_zoom:
            self.set_view_zoom(zoom_factor, emit=True)
        if sync_pan and center_scene is not None:
            self.centerOn(center_scene)
            self.presentation_state.pan_center = QPointF(center_scene)
            self.presentation_state.fit_mode = False
        self.viewport().update()

    def flip_horizontal(self):
        """水平翻转"""
        self._flip_h = not self._flip_h
        self.presentation_state.flip_horizontal = self._flip_h
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform()

    def flip_vertical(self):
        """垂直翻转"""
        self._flip_v = not self._flip_v
        self.presentation_state.flip_vertical = self._flip_v
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform()

    def rotate_left(self):
        """左旋90°"""
        self._rotation = (self._rotation - 90) % 360
        self.presentation_state.rotation = self._rotation
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform()

    def rotate_right(self):
        """右旋90°"""
        self._rotation = (self._rotation + 90) % 360
        self.presentation_state.rotation = self._rotation
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform()

    def toggle_invert(self):
        """切换反色"""
        self._inverted = not self._inverted
        self.presentation_state.inverted = self._inverted
        self._refresh_display()

    def reset_transforms(self):
        """重置所有视图变换"""
        was_inverted = self._inverted
        self.presentation_state.use_physical_pixel_aspect = True
        self._flip_h = False
        self._flip_v = False
        self._rotation = 0
        self._inverted = False
        self.presentation_state.rotation = 0
        self.presentation_state.flip_horizontal = False
        self.presentation_state.flip_vertical = False
        self.presentation_state.inverted = False
        self._rebuild_view_transform()
        if was_inverted:
            self._refresh_display()

    def _refresh_display(self):
        """重新触发当前图像的显示以应用变换"""
        if self.model:
            self.presentation_changed.emit(self.presentation_state)

    def fit_to_window(self) -> None:
        """自适应窗口大小"""
        if not self.image_item or self.image_item.pixmap().isNull():
            return
        self.presentation_state.use_physical_pixel_aspect = True
        self.setTransform(self._orientation_transform(1.0))
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_zoom_from_transform()
        self._rebuild_view_transform(self._view_zoom, emit=False)
        self.centerOn(self.scene.sceneRect().center())
        self.presentation_state.fit_mode = True
        self.presentation_state.pan_center = self.scene.sceneRect().center()
        self.zoom_changed.emit(self._view_zoom)
        self.viewport().update()

    def actual_size(self) -> None:
        """Display one source pixel per logical viewport pixel."""
        self.presentation_state.use_physical_pixel_aspect = False
        self.presentation_state.fit_mode = False
        self._rebuild_view_transform(1.0)

    def reset_view(self) -> None:
        """Reset geometry/inversion and fit the image to the viewport."""
        self.reset_transforms()
        self.fit_to_window()

    def enterEvent(self, event) -> None:
        """鼠标进入事件"""
        # 光标由当前工具管理
        # self.setCursor(self.cross_cursor)
        if self.presentation_state.magnifier_enabled or self._magnifier_key_held:
            self.magnifier.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开事件"""
        self.unsetCursor()
        self.magnifier.hide()
        self._clear_synced_cross_reference()
        self.cursor_left_image.emit()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """重写鼠标滚轮事件，委托给当前工具"""
        # 多视图中，滚轮可能直接发生在非活动视图上。先激活该视图，
        # 让主窗口在模型切片变化前完成信号重连和同步源切换。
        if event.angleDelta().y() != 0 or event.pixelDelta().y() != 0:
            self.interaction_started.emit()
        if self.current_tool:
            self.current_tool.wheel_event(event)
        else:
            super().wheelEvent(event)
            
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """重写鼠标按下事件，委托给当前工具或处理测量线拖拽"""
        self.interaction_started.emit()

        # 先让工具处理事件
        if self.current_tool:
            self.current_tool.mouse_press_event(event)
        else:
            super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """重写鼠标移动事件，委托给当前工具或处理测量线拖拽"""
        if self.current_tool:
            self.current_tool.mouse_move_event(event)
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """重写鼠标释放事件，委托给当前工具或处理测量线拖拽"""
        if self.current_tool:
            self.current_tool.mouse_release_event(event)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Ask the grid to maximize or restore this viewport."""
        if event.button() == Qt.LeftButton:
            self.interaction_started.emit()
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        """处理键盘按下事件，先委托给当前工具，然后处理ROI删除等。"""
        if event.key() == Qt.Key_Alt and not event.isAutoRepeat():
            self._magnifier_key_held = True
            self._update_pixel_info(self.last_mouse_scene_pos)
            event.accept()
            return
        # 先委托给当前工具处理
        if self.current_tool:
            self.current_tool.key_press_event(event)
            if event.isAccepted():
                return
        
        # 如果工具没有处理，则由视图处理
        if event.key() == Qt.Key_Delete and self.model:
            # 删除模型中的ROI
            deleted_ids = self.model.delete_selected_rois()
            
            # 从视图中移除对应的信息板
            for roi_id in deleted_ids:
                if roi_id in self.stats_box_positions:
                    del self.stats_box_positions[roi_id]
            
            # 不需要手动更新视图，因为 model 的 clear_selection 会发出 data_changed 信号
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Alt and not event.isAutoRepeat():
            self._magnifier_key_held = False
            if not self.presentation_state.magnifier_enabled:
                self.magnifier.hide()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        """直接处理影像视口中的序列拖入，不依赖中间布局父级。"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            self.series_drag_active.emit(True)
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """处理影像视口中的序列拖拽移动。"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """清除影像视口拖拽反馈。"""
        self.series_drag_active.emit(False)
        event.accept()
    
    def dropEvent(self, event):
        """在影像视口放下序列并发出显式绑定请求。"""
        if event.mimeData().hasFormat("application/x-medimager-series"):
            series_data = event.mimeData().data("application/x-medimager-series")
            series_id = series_data.data().decode()
            self.series_drag_active.emit(False)
            self.series_drop_requested.emit(series_id)
            event.acceptProposedAction()
        else:
            event.ignore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """在前景中绘制内容，如ROI、锚点、统计信息和临时形状。"""
        super().drawForeground(painter, rect)

        if not self.model or not self.model.has_image():
            return

        painter.setRenderHint(QPainter.Antialiasing, True)
        current_slice_index = self.current_slice_index
        self._annotation_label_rects.clear()

        stats_box_settings = _get_stats_box_settings()
        auto_hide_stats = bool(stats_box_settings.get("auto_hide", False))
        visible_roi_ids: set[str] = set()

        for idx, roi in enumerate(self.model.rois):
            if roi.slice_index != current_slice_index:
                continue
            visible_roi_ids.add(str(roi.id))
            roi.draw(painter, self.transform())

            should_draw_stats = (
                roi.id in self.stats_box_positions
                and roi.show_stats
                and (
                    not auto_hide_stats
                    or roi.selected
                    or self.hovered_roi_index == idx
                )
            )
            if should_draw_stats:
                stats = self._statistics_for_roi(roi)
                if stats:
                    painter.save()
                    painter.resetTransform()
                    draw_stats_box(
                        painter,
                        stats,
                        self.get_stats_box_viewport_rect(roi.id),
                        selected=roi.selected,
                    )
                    painter.restore()

        for roi_id in set(self._roi_stats_cache) - visible_roi_ids:
            self._roi_stats_cache.pop(roi_id, None)

        # Draw measurement tool if it is active and has points
        if self.current_tool and hasattr(self.current_tool, 'draw_temporary_shape'):
            self.current_tool.draw_temporary_shape(painter)
        
        # --- 始终绘制所有测量线（独立于当前工具）---
        self._draw_all_measurements(painter)
        self._draw_all_angle_measurements(painter)
            
        # --- 绘制交叉参考线 ---
        if self._cross_reference_enabled and self._cross_reference_pos.x() >= 0 and self._cross_reference_pos.y() >= 0:
            self._draw_cross_reference_lines(painter)
            
        self._draw_medical_overlay(painter)

    def _draw_medical_overlay(self, painter: QPainter) -> None:
        """Draw orientation, acquisition warnings, transforms, zoom and scale."""
        try:
            metadata_getter = getattr(self.model, "get_slice_metadata", None)
            metadata = (
                metadata_getter(self.current_slice_index)
                if callable(metadata_getter)
                else getattr(self.model, "metadata", {}) or {}
            )
            bounds = QRect(self.viewport().rect()).adjusted(8, 6, -8, -6)
            if bounds.isEmpty():
                return
            painter.save()
            painter.resetTransform()
            font = QFont()
            font.setPixelSize(12)
            painter.setFont(font)
            line_height = QFontMetrics(font).height() + 2

            left_lines = [
                self._corner_overlay_info.get("title", ""),
                self._corner_overlay_info.get("slice", ""),
                self._corner_overlay_info.get("window", ""),
            ]
            laterality = str(
                metadata.get("ImageLaterality") or metadata.get("Laterality") or ""
            ).strip()
            right_lines = [f"LAT {laterality}" if laterality else ""]
            lossy_getter = getattr(self.model, "get_lossy_compression_info", None)
            lossy = lossy_getter(self.current_slice_index) if callable(lossy_getter) else None
            if lossy:
                detail = " ".join(
                    value for value in (lossy.get("method"), lossy.get("ratio")) if value
                )
                right_lines.append(f"LOSSY {detail}".rstrip())

            transform_flags = []
            state = self.presentation_state
            if state.rotation:
                transform_flags.append(f"R{state.rotation}")
            if state.flip_horizontal:
                transform_flags.append("FLIP-H")
            if state.flip_vertical:
                transform_flags.append("FLIP-V")
            if state.inverted:
                transform_flags.append("INV")

            for index, text in enumerate(filter(None, left_lines)):
                self._draw_contrast_text(
                    painter,
                    QRect(bounds.left(), bounds.top() + index * line_height, bounds.width(), line_height),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    text,
                )
            for index, text in enumerate(filter(None, right_lines)):
                self._draw_contrast_text(
                    painter,
                    QRect(bounds.left(), bounds.top() + index * line_height, bounds.width(), line_height),
                    Qt.AlignRight | Qt.AlignVCenter,
                    text,
                )
            bottom_rect = QRect(
                bounds.left(), bounds.bottom() - line_height, bounds.width(), line_height
            )
            if transform_flags:
                self._draw_contrast_text(
                    painter, bottom_rect, Qt.AlignLeft | Qt.AlignVCenter,
                    "  ".join(transform_flags),
                )
            self._draw_contrast_text(
                painter, bottom_rect, Qt.AlignRight | Qt.AlignVCenter,
                f"{state.zoom * 100:.0f}%",
            )

            markers = self._orientation_markers(metadata)
            marker_rects = {
                "top": (QRect(bounds.left(), bounds.top(), bounds.width(), line_height), Qt.AlignHCenter | Qt.AlignTop),
                "bottom": (QRect(bounds.left(), bounds.bottom() - line_height, bounds.width(), line_height), Qt.AlignHCenter | Qt.AlignBottom),
                "left": (QRect(bounds.left(), bounds.top(), 32, bounds.height()), Qt.AlignLeft | Qt.AlignVCenter),
                "right": (QRect(bounds.right() - 31, bounds.top(), 32, bounds.height()), Qt.AlignRight | Qt.AlignVCenter),
            }
            for edge, marker in markers.items():
                if marker and edge in marker_rects:
                    marker_rect, alignment = marker_rects[edge]
                    self._draw_contrast_text(painter, marker_rect, alignment, marker)
            self._draw_scale_bar(painter, bounds, line_height)
            painter.restore()
        except Exception as error:
            self.logger.debug(f"绘制医学覆盖层失败: {error}")

    @staticmethod
    def _draw_contrast_text(painter: QPainter, rect: QRect, alignment, text: str) -> None:
        painter.setPen(QColor(0, 0, 0, 230))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(rect.translated(dx, dy), alignment, text)
        painter.setPen(QColor(255, 255, 255, 245))
        painter.drawText(rect, alignment, text)

    @staticmethod
    def _patient_direction_code(vector) -> str:
        labels = (("L", "R"), ("P", "A"), ("H", "F"))
        components = sorted(
            ((abs(float(value)), index, float(value)) for index, value in enumerate(vector)),
            reverse=True,
        )
        if not components or components[0][0] < 1e-6:
            return ""
        threshold = components[0][0] * 0.35
        return "".join(
            labels[index][0 if value >= 0 else 1]
            for magnitude, index, value in components
            if magnitude >= threshold
        )

    def _remap_orientation_override(self, markers: Dict[str, str]) -> Dict[str, str]:
        """Map image-edge labels onto the currently transformed screen edges."""
        transform = self._orientation_transform(1.0)
        origin = transform.map(QPointF())
        directions = {
            "top": QPointF(0.0, -1.0),
            "right": QPointF(1.0, 0.0),
            "bottom": QPointF(0.0, 1.0),
            "left": QPointF(-1.0, 0.0),
        }
        remapped: Dict[str, str] = {}
        for source_edge, direction in directions.items():
            marker = markers.get(source_edge, "")
            point = transform.map(direction)
            dx, dy = point.x() - origin.x(), point.y() - origin.y()
            if abs(dx) >= abs(dy):
                target_edge = "right" if dx >= 0 else "left"
            else:
                target_edge = "bottom" if dy >= 0 else "top"
            remapped[target_edge] = marker
        return remapped

    def _orientation_markers(self, metadata: dict) -> Dict[str, str]:
        if self._orientation_override is not None:
            return self._remap_orientation_override(self._orientation_override)
        iop = metadata.get("ImageOrientationPatient") or metadata.get("Image Orientation Patient")
        if isinstance(iop, str):
            iop = iop.replace(",", "\\").split("\\")
        try:
            values = [float(value) for value in iop]
            if len(values) < 6:
                return {}
            row, column = values[:3], values[3:6]
            inverse, invertible = self.transform().inverted()
            if not invertible:
                return {}
            origin = inverse.map(QPointF())
            right_point = inverse.map(QPointF(1.0, 0.0))
            bottom_point = inverse.map(QPointF(0.0, 1.0))
            def patient_vector(point):
                dx, dy = point.x() - origin.x(), point.y() - origin.y()
                return tuple(dx * row[index] + dy * column[index] for index in range(3))
            right = patient_vector(right_point)
            bottom = patient_vector(bottom_point)
            return {
                "right": self._patient_direction_code(right),
                "left": self._patient_direction_code(tuple(-value for value in right)),
                "bottom": self._patient_direction_code(bottom),
                "top": self._patient_direction_code(tuple(-value for value in bottom)),
            }
        except (TypeError, ValueError):
            return {}

    def _draw_scale_bar(self, painter: QPainter, bounds: QRect, line_height: int) -> None:
        getter = getattr(self.model, "get_pixel_spacing_info", None)
        spacing = getter(self.current_slice_index) if callable(getter) else None
        if spacing is None:
            return
        bar_width = min(100, max(40, bounds.width() // 4))
        x2, x1 = bounds.right(), bounds.right() - bar_width
        y = bounds.bottom() - line_height - 5
        inverse, ok = self.transform().inverted()
        if not ok:
            return
        first = inverse.map(QPointF(float(x1), float(y)))
        second = inverse.map(QPointF(float(x2), float(y)))
        distance = math.hypot(
            (second.x() - first.x()) * spacing.col_spacing,
            (second.y() - first.y()) * spacing.row_spacing,
        )
        if spacing.measurement_calibrated:
            label = f"{distance:.1f} mm"
        else:
            label = t("viewframe.detector_scale_uncalibrated").replace("%1", f"{distance:.1f}")
        painter.setPen(QPen(QColor(0, 0, 0, 230), 4))
        painter.drawLine(x1, y, x2, y)
        painter.setPen(QPen(QColor(255, 255, 255, 245), 2))
        painter.drawLine(x1, y, x2, y)
        self._draw_contrast_text(
            painter,
            QRect(x1 - 140, y - line_height, bar_width + 140, line_height),
            Qt.AlignRight | Qt.AlignVCenter,
            label,
        )

    def _update_pixel_info(self, scene_pos: QPointF) -> None:
        """更新状态栏的像素信息和放大镜"""
        # 首先检查是否有图像
        if self.image_item is None:
            self._clear_synced_cross_reference()
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return
        # 获取图像的实际像素范围
        pixmap = self.image_item.pixmap()
        if pixmap.isNull():
            self._clear_synced_cross_reference()
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return
        image_rect = pixmap.rect()  # 这是实际的图像像素矩形
        # 检查鼠标位置是否在实际图像像素范围内
        if not image_rect.contains(scene_pos.toPoint()):
            self._clear_synced_cross_reference()
            self.cursor_left_image.emit()
            self.magnifier.hide()
            return

        show_magnifier = (
            self.presentation_state.magnifier_enabled or self._magnifier_key_held
        )
        if show_magnifier:
            self.magnifier.show()
            if self._cached_qimage is None:
                self._cached_qimage = pixmap.toImage()
            source_qimage = self._cached_qimage
            source_size = min(8, image_rect.width(), image_rect.height())
            half_size = source_size // 2
            max_left = image_rect.right() - source_size + 1
            max_top = image_rect.bottom() - source_size + 1
            source_left = max(
                image_rect.left(), min(int(round(scene_pos.x())) - half_size, max_left)
            )
            source_top = max(
                image_rect.top(), min(int(round(scene_pos.y())) - half_size, max_top)
            )
            source_rect = QRect(source_left, source_top, source_size, source_size)
            self.magnifier.update_magnifier(source_qimage, source_rect)

            # Keep the lens away from the inspected corner.
            lens_size = self.magnifier.size()
            if self.mapFromScene(scene_pos).x() > self.viewport().width() * 0.6:
                self.magnifier.move(5, 5)
            else:
                self.magnifier.move(
                    self.width() - lens_size.width() - 5, 5
                )
        else:
            self.magnifier.hide()

        # 更新像素值
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        
        # 检查坐标是否在图像范围内并且模型有效
        if self.model and self.model.has_image():
            shape = self.model.get_image_shape()
            if shape and 0 <= x < shape[2] and 0 <= y < shape[1]:
                safe_pos = QPointF(float(x), float(y))
                self.cursor_position_changed.emit(safe_pos)
                if self._sync_manager is not None and self._view_id:
                    self._sync_manager.update_cross_reference(self._view_id, safe_pos)
                # 获取像素值
                pixel_value = pixel_value_for_view(self.model, self.presentation_state, x, y)
                if pixel_value is not None:
                    # 发出像素值变化信号
                    self.pixel_value_changed.emit(x, y, pixel_value)
                    return
        
        # 彩色图像可能没有可表示为 float 的单通道像素值，但患者空间位置仍有效。
        self.cursor_left_image.emit()

    def _clear_synced_cross_reference(self) -> None:
        if self._sync_manager is not None and self._view_id:
            clear = getattr(self._sync_manager, 'clear_cross_reference', None)
            if callable(clear):
                clear(self._view_id)

    def clear_roi_dependent_state(self) -> None:
        """当ROI被清空或加载新图像时，重置与ROI相关的状态"""
        self._roi_stats_cache.clear()
        self.hovered_roi_index = None
        self.stats_box_positions = {}
        self.viewport().update()

    @staticmethod
    def _roi_geometry_signature(roi) -> tuple:
        """Build a stable signature from fields that can affect ROI statistics."""

        def freeze(value):
            if isinstance(value, dict):
                return tuple(
                    sorted((str(key), freeze(item)) for key, item in value.items())
                )
            if isinstance(value, (list, tuple, set)):
                return tuple(freeze(item) for item in value)
            if hasattr(value, "value"):
                return freeze(value.value)
            try:
                hash(value)
            except TypeError:
                return repr(value)
            return value

        ignored = {"id", "selected", "show_stats"}
        return tuple(
            sorted(
                (name, freeze(value))
                for name, value in vars(roi).items()
                if not name.startswith("_") and name not in ignored
            )
        )

    def _statistics_for_roi(self, roi):
        """Calculate ROI statistics once until pixels or ROI geometry change."""
        if self.model is None:
            return None
        signature = (
            id(self.model),
            int(getattr(self.model, "_data_revision", 0)),
            self._roi_geometry_signature(roi),
        )
        cached = self._roi_stats_cache.get(str(roi.id))
        if cached is None or cached[0] != signature:
            cached = (signature, calculate_roi_statistics(self.model, roi))
            self._roi_stats_cache[str(roi.id)] = cached
        return cached[1]

    def get_stats_box_viewport_rect(self, roi_id: str) -> QRect:
        """把场景锚点映射为固定屏幕尺寸矩形，并在可见图像内约束。"""
        scene_rect = self.stats_box_positions.get(roi_id, QRectF())
        anchor = self.mapFromScene(QPointF(scene_rect.left(), scene_rect.top()))
        viewport_rect = QRect(
            anchor.x(),
            anchor.y(),
            int(round(scene_rect.width())),
            int(round(scene_rect.height())),
        )
        return self._clamp_viewport_rect(
            viewport_rect, self.visible_image_viewport_rect()
        )

    def set_stats_box_viewport_rect(self, roi_id: str, rect: QRect) -> None:
        """保存统计框：锚点使用 scene 坐标，尺寸保持 viewport 像素。"""
        clamped = self._clamp_viewport_rect(
            QRect(rect), self.visible_image_viewport_rect()
        )
        scene_anchor = self.mapToScene(clamped.topLeft())
        self.stats_box_positions[roi_id] = QRectF(
            scene_anchor.x(),
            scene_anchor.y(),
            float(clamped.width()),
            float(clamped.height()),
        )

    def visible_image_viewport_rect(self) -> QRect:
        """返回当前 viewport 中实际可用于覆盖层的图像区域。"""
        bounds = QRect(self.viewport().rect())
        if self.image_item and not self.image_item.pixmap().isNull():
            image_bounds = self.mapFromScene(
                self.image_item.sceneBoundingRect()
            ).boundingRect()
            intersection = bounds.intersected(image_bounds)
            if not intersection.isEmpty():
                bounds = intersection
        return bounds

    @staticmethod
    def _clamp_viewport_rect(rect: QRect, bounds: QRect) -> QRect:
        """在统一的 viewport 像素坐标中约束固定尺寸覆盖层。"""
        result = QRect(rect)
        if bounds.isEmpty():
            return result
        if result.width() <= bounds.width():
            result.moveLeft(
                max(bounds.left(), min(result.left(), bounds.right() - result.width() + 1))
            )
        else:
            result.moveLeft(bounds.left())
        if result.height() <= bounds.height():
            result.moveTop(
                max(bounds.top(), min(result.top(), bounds.bottom() - result.height() + 1))
            )
        else:
            result.moveTop(bounds.top())
        return result

    def create_stats_box_viewport_rect(self, roi, size) -> QRect:
        """按 ROI 的屏幕包围框生成固定像素统计框位置。"""
        center_y, center_x = roi.center
        if isinstance(roi, RectangleROI):
            half_width = roi.width / 2.0
            half_height = roi.height / 2.0
        elif isinstance(roi, CircleROI):
            half_width = half_height = roi.radius
        elif isinstance(roi, EllipseROI):
            half_width = roi.radius_x
            half_height = roi.radius_y
        else:
            half_width = half_height = 0.0

        roi_scene_rect = QRectF(
            center_x - half_width,
            center_y - half_height,
            max(1.0, half_width * 2.0),
            max(1.0, half_height * 2.0),
        )
        roi_view_rect = self.mapFromScene(roi_scene_rect).boundingRect()
        bounds = self.visible_image_viewport_rect()
        rect = QRect(
            roi_view_rect.right() + 10,
            roi_view_rect.center().y() - int(size.height() / 2),
            int(size.width()),
            int(size.height()),
        )
        if rect.right() > bounds.right():
            rect.moveRight(roi_view_rect.left() - 10)
        return self._clamp_viewport_rect(rect, bounds)

    def resizeEvent(self, event) -> None:
        """窗口大小改变事件"""
        super().resizeEvent(event)
        # 将放大镜放在右上角
        magnifier_size = self.magnifier.size()
        self.magnifier.move(self.width() - magnifier_size.width() - 5, 5)
        # 布局切换后执行一次自适应
        if self._fit_pending and self.presentation_state.fit_mode:
            self._fit_pending = False
            self.fit_to_window()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if dx or dy:
            self.presentation_state.pan_center = self.mapToScene(
                self.viewport().rect().center()
            )
            self.presentation_state.fit_mode = False

    def _update_view(self):
        """当模型数据变化时，重新渲染视图"""
        if self.model:
            self.model.update_qimage()

    def zoom_in(self, level=1.2):
        """放大"""
        self.set_view_zoom(self._view_zoom * float(level))

    def zoom_out(self, level=1.2):
        """缩小"""
        self.set_view_zoom(self._view_zoom / float(level))

    def _fit_to_bounding_rect(self):
        """图像自适应边界矩形（内部使用）"""
        if not self.image_item or self.image_item.pixmap().isNull():
            return
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        self._update_zoom_from_transform()
        self.zoom_changed.emit(self._view_zoom)

    def is_shift_pressed(self) -> bool:
        """检查Shift键是否被按下"""
        return QApplication.keyboardModifiers() == Qt.ShiftModifier

    def set_measurement_line(self, start_point: QPointF, end_point: QPointF, distance: float, unit: str = "mm"):
        """设置测量线，用于在工具切换后保持显示"""
        self.measurement_start_point = start_point
        self.measurement_end_point = end_point
        self.measurement_distance = distance
        self.measurement_unit = unit
        self.viewport().update()

    def clear_measurement_line(self):
        """清除测量线"""
        self.measurement_start_point = None
        self.measurement_end_point = None
        self.measurement_distance = None
        self.measurement_unit = "mm"
        self.update()

    def show_cross_reference(self, pos: QPointF) -> None:
        """显示交叉参考线
        
        Args:
            pos: 参考线交叉点位置（场景坐标）
        """
        self._cross_reference_enabled = True
        self._cross_reference_pos = QPointF(pos)
        self.update()
    
    def hide_cross_reference(self) -> None:
        """隐藏交叉参考线"""
        self._cross_reference_enabled = False
        self._cross_reference_pos = QPointF(-1, -1)
        self.update()
    
    def set_cross_reference_enabled(self, enabled: bool) -> None:
        """设置交叉参考线是否启用
        
        Args:
            enabled: 是否启用交叉参考线
        """
        self._cross_reference_enabled = enabled
        if not enabled:
            self.hide_cross_reference()

    def _get_measurement_theme(self) -> dict:
        """获取测量线主题设置（带缓存）"""
        if self._measurement_theme_cache is not None:
            return self._measurement_theme_cache
        defaults = {
            'line_color': "#00FF00", 'anchor_color': "#00FF00",
            'selected_color': "#FFD54F",
            'text_color': "#FFFFFF", 'background_color': "#00000080",
            'line_width': 2, 'anchor_size': 8, 'font_size': 14,
        }
        try:
            from medimager.utils.theme_manager import get_theme_settings
            theme_data = get_theme_settings('measurement')
            for k, v in defaults.items():
                defaults[k] = theme_data.get(k, v)
        except Exception:
            pass
        self._measurement_theme_cache = defaults
        return defaults

    def _draw_measurement_line(self, painter):
        """绘制测量线（独立于工具）"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return

        t = self._get_measurement_theme()

        painter.save()

        # 1. 绘制线
        pen = QPen(qcolor_from_theme(t['line_color']), t['line_width'])
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(self.measurement_start_point, self.measurement_end_point)

        # 2. 绘制锚点
        painter.setBrush(qcolor_from_theme(t['anchor_color']))
        painter.setPen(Qt.NoPen)
        pixel_size = 1.0 / self.effective_scale()
        scaled_anchor_size = t['anchor_size'] * pixel_size
        painter.drawEllipse(self.measurement_start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
        painter.drawEllipse(self.measurement_end_point, scaled_anchor_size / 2, scaled_anchor_size / 2)

        # 3. 绘制距离文本
        if self.measurement_distance is not None:
            font = QFont()
            font.setPixelSize(t['font_size'])
            painter.setFont(font)

            text = f"{self.measurement_distance:.2f} {self.measurement_unit}"
            metrics = painter.fontMetrics()
            text_rect = metrics.boundingRect(text).adjusted(-4, -2, 4, 2)

            mid_point = (self.measurement_start_point + self.measurement_end_point) / 2
            text_rect.moveCenter(mid_point.toPoint())

            painter.setBrush(qcolor_from_theme(t['background_color']))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(text_rect, 5, 5)

            painter.setPen(qcolor_from_theme(t['text_color']))
            painter.drawText(text_rect, Qt.AlignCenter, text)

        painter.restore()

    def _check_measurement_line_drag(self, event: QMouseEvent):
        """检查鼠标是否开始拖动测量线或其锚点"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return
            
        # 计算点击位置到测量线的距离
        click_pos = self.mapToScene(event.position().toPoint())
        if self._is_click_on_measurement_line(click_pos):
            self._start_measurement_drag(event)

    def _is_click_on_measurement_line(self, click_pos: QPointF) -> bool:
        """检查点击位置是否在测量线上"""
        if not self.measurement_start_point or not self.measurement_end_point:
            return False
            
        # 计算点击位置到测量线的距离
        line_start = self.measurement_start_point
        line_end = self.measurement_end_point
        
        # 计算线段长度
        line_length = self._calculate_pixel_distance(line_start, line_end)
        if line_length == 0:
            return False
            
        # 计算点击位置到线段的距离
        # 使用点到线段的距离公式
        t = max(0, min(1, ((click_pos.x() - line_start.x()) * (line_end.x() - line_start.x()) + 
                           (click_pos.y() - line_start.y()) * (line_end.y() - line_start.y())) / (line_length * line_length)))
        
        # 计算线段上最近的点
        closest_point = QPointF(
            line_start.x() + t * (line_end.x() - line_start.x()),
            line_start.y() + t * (line_end.y() - line_start.y())
        )
        
        # 计算点击位置到最近点的距离
        distance = self._calculate_pixel_distance(click_pos, closest_point)
        
        # 如果距离小于阈值（5像素），认为点击在线段上
        return distance <= 5

    def _calculate_pixel_distance(self, point1: QPointF, point2: QPointF) -> float:
        """计算两点间的像素距离"""
        import math
        dx = point2.x() - point1.x()
        dy = point2.y() - point1.y()
        return math.sqrt(dx * dx + dy * dy)

    def _start_measurement_drag(self, event: QMouseEvent):
        """开始拖拽测量线"""
        self._measurement_dragging = True
        self._measurement_drag_start_pos = self.mapToScene(event.position().toPoint())
        self._measurement_drag_offset = QPointF(0, 0)
        self.setCursor(Qt.ClosedHandCursor)

    def _update_measurement_drag(self, event: QMouseEvent):
        """更新测量线拖拽"""
        if not hasattr(self, '_measurement_dragging') or not self._measurement_dragging:
            return
            
        # 计算拖拽偏移
        current_pos = self.mapToScene(event.position().toPoint())
        self._measurement_drag_offset = current_pos - self._measurement_drag_start_pos
        
        # 更新测量点位置
        if self.measurement_start_point and self.measurement_end_point:
            self.measurement_start_point += self._measurement_drag_offset
            self.measurement_end_point += self._measurement_drag_offset
            self._measurement_drag_start_pos = current_pos
            
            # 更新视图
            self.viewport().update()

    def _stop_measurement_drag(self):
        """停止测量线拖拽"""
        if hasattr(self, '_measurement_dragging'):
            self._measurement_dragging = False
        self.setCursor(Qt.ArrowCursor)
        if hasattr(self, '_measurement_drag_offset'):
            self._measurement_drag_offset = QPointF(0, 0)

    def _draw_all_measurements(self, painter):
        """绘制所有测量线，包括选中状态"""
        if not self.model:
            return

        t = self._get_measurement_theme()

        painter.save()
        
        # 绘制当前切片的所有测量线
        current_slice_measurements = self.model.get_measurements_for_slice(self.current_slice_index)
        
        for i, measurement in enumerate(current_slice_measurements):
            # 找到对应的全局索引
            global_idx = None
            for idx, global_measurement in enumerate(self.model.measurements):
                if global_measurement.id == measurement.id:
                    global_idx = idx
                    break
            
            # 确定是否选中 - 选中状态优先于编辑状态
            is_selected = global_idx is not None and global_idx in self.model.selected_measurement_indices
            
            # 检查是否正在被编辑（拖拽）- 只有当前工具是MeasurementTool时才考虑编辑状态
            is_being_edited = False
            is_measurement_tool = (self.current_tool and 
                                 self.current_tool.__class__.__name__ == 'MeasurementTool')
            if (is_measurement_tool and 
                hasattr(self.current_tool, 'editing_measurement_id') and 
                self.current_tool.editing_measurement_id):
                is_being_edited = (measurement.id == self.current_tool.editing_measurement_id)
            
            # 颜色优先级：选中状态(红色) > 编辑状态(黄色) > 默认状态(绿色)
            if is_selected:
                current_line_color = "#FF0000"  # 红色 - 选中状态
                current_anchor_color = "#FF0000"
            elif is_being_edited:
                current_line_color = "#FFFF00"  # 黄色 - 编辑状态
                current_anchor_color = "#FFFF00"
            else:
                current_line_color = t['line_color']
                current_anchor_color = t['anchor_color']

            # 绘制线
            pen = QPen(qcolor_from_theme(current_line_color), t['line_width'])
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(measurement.start_point, measurement.end_point)

            # 绘制锚点
            painter.setBrush(qcolor_from_theme(current_anchor_color))
            painter.setPen(Qt.NoPen)
            pixel_size = 1.0 / self.effective_scale()
            scaled_anchor_size = t['anchor_size'] * pixel_size

            painter.drawEllipse(measurement.start_point, scaled_anchor_size / 2, scaled_anchor_size / 2)
            painter.drawEllipse(measurement.end_point, scaled_anchor_size / 2, scaled_anchor_size / 2)

            # 绘制距离文本
            text = f"{measurement.distance:.2f} {measurement.unit}"
            mid_point = (measurement.start_point + measurement.end_point) / 2
            device_mid_point = self.mapFromScene(mid_point)

            painter.save()
            painter.resetTransform()
            font = QFont()
            font.setPixelSize(t['font_size'])
            painter.setFont(font)
            metrics = painter.fontMetrics()
            text_rect = metrics.boundingRect(text).adjusted(-4, -2, 4, 2)
            offset = self.annotation_label_offset(measurement.id)
            text_rect.moveCenter(
                device_mid_point + QPoint(
                    int(round(offset.x())), int(round(offset.y()))
                )
            )
            self._annotation_label_rects[str(measurement.id)] = ("measurement", QRect(text_rect))

            painter.setBrush(qcolor_from_theme(t['background_color']))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(text_rect, 5, 5)

            painter.setPen(qcolor_from_theme(t['text_color']))
            painter.drawText(text_rect, Qt.AlignCenter, text)
            painter.restore()
        
        painter.restore()

    def _draw_all_angle_measurements(self, painter):
        """绘制所有角度测量"""
        if not self.model:
            return
        angle_measurements = self.model.get_angle_measurements_for_slice(self.current_slice_index)
        if not angle_measurements:
            return

        t = self._get_measurement_theme()
        painter.save()

        pixel_size = 1.0 / self.effective_scale()
        scaled_anchor = t['anchor_size'] * pixel_size

        for am in angle_measurements:
            is_selected = am.id in self.model.selected_angle_measurement_ids
            line_color = t['selected_color'] if is_selected else t['line_color']
            # 绘制两条线段
            pen = QPen(qcolor_from_theme(line_color), t['line_width'] + (1 if is_selected else 0))
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(am.point1, am.vertex)
            painter.drawLine(am.vertex, am.point3)

            if is_selected:
                # 明显大于普通实心锚点的高对比外圈，缩放后仍保持设备像素尺寸。
                selected_pen = QPen(qcolor_from_theme(t['selected_color']), 3)
                selected_pen.setCosmetic(True)
                painter.setPen(selected_pen)
                painter.setBrush(Qt.NoBrush)
                selected_radius = (t['anchor_size'] + 8) * pixel_size / 2
                for pt in (am.point1, am.vertex, am.point3):
                    painter.drawEllipse(pt, selected_radius, selected_radius)

            # 绘制锚点
            painter.setBrush(qcolor_from_theme(t['anchor_color']))
            painter.setPen(Qt.NoPen)
            for pt in (am.point1, am.vertex, am.point3):
                painter.drawEllipse(pt, scaled_anchor / 2, scaled_anchor / 2)

            # 绘制弧线和角度文字
            from medimager.ui.tools.angle_tool import AngleTool
            AngleTool._draw_angle_arc_and_text(
                painter, am.point1, am.vertex, am.point3, am.angle_degrees,
                line_color, t['text_color'], t['background_color'],
                t['line_width'], t['font_size'], pixel_size, self,
                self.annotation_label_offset(am.id),
            )
            self._annotation_label_rects[str(am.id)] = (
                "angle",
                self._angle_label_viewport_rect(am, t['font_size'], pixel_size),
            )

        painter.restore()

    def _angle_label_viewport_rect(self, angle, font_size: int, pixel_size: float) -> QRect:
        """Mirror AngleTool's text placement for pointer hit-testing."""
        p1, vertex, p3 = angle.point1, angle.vertex, angle.point3
        angle1 = math.degrees(math.atan2(-(p1.y() - vertex.y()), p1.x() - vertex.x()))
        angle2 = math.degrees(math.atan2(-(p3.y() - vertex.y()), p3.x() - vertex.x()))
        span = angle1 - angle2
        if span > 180:
            span -= 360
        elif span < -180:
            span += 360
        mid_angle = math.radians(angle2 + span / 2.0)
        radius = 25.0 * pixel_size * 1.8
        center = self.mapFromScene(
            QPointF(
                vertex.x() + radius * math.cos(mid_angle),
                vertex.y() - radius * math.sin(mid_angle),
            )
        )
        offset = self.annotation_label_offset(angle.id)
        center += QPoint(int(round(offset.x())), int(round(offset.y())))
        font = QFont()
        font.setPixelSize(int(font_size))
        rect = QFontMetrics(font).boundingRect(f"{angle.angle_degrees:.1f}°")
        rect = rect.adjusted(-4, -2, 4, 2)
        rect.moveCenter(center)
        return rect

    def _draw_cross_reference_lines(self, painter):
        """绘制交叉参考线"""
        if not self._cross_reference_enabled or self._cross_reference_pos.x() < 0 or self._cross_reference_pos.y() < 0:
            return

        painter.save()

        # 设置画笔样式
        pen = QPen(self._cross_reference_color, 2)
        pen.setCosmetic(True)  # 不受视图变换影响
        pen.setStyle(Qt.DashLine)  # 虚线样式
        painter.setPen(pen)

        # 获取视图区域
        view_rect = self.viewport().rect()
        scene_rect = self.mapToScene(view_rect).boundingRect()

        # 绘制水平参考线（横穿整个视图）
        painter.drawLine(
            scene_rect.left(), self._cross_reference_pos.y(),
            scene_rect.right(), self._cross_reference_pos.y()
        )

        # 绘制垂直参考线（横穿整个视图）
        painter.drawLine(
            self._cross_reference_pos.x(), scene_rect.top(),
            self._cross_reference_pos.x(), scene_rect.bottom()
        )

        painter.restore()
