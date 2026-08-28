"""Three-plane orthogonal MPR workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Optional, Sequence
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from medimager.core.annotation_coordinates import (
    patient_to_pixel_on_slice,
    patient_to_target_pixel,
)
from medimager.core.image_data_model import AngleMeasurementData, MeasurementData
from medimager.core.render_pipeline import RenderRequest, render_frame
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI
from medimager.core.view_presentation_state import InterpolationMode, ViewPresentationState
from medimager.core.volume_geometry import (
    GeometryStatus,
    MprPlane,
    OrthogonalMprResampler,
    PlaneGeometry,
    ResampledPlane,
    VolumeBuildResult,
    VolumeBuilder,
)
from medimager.ui.qt_image_utils import qimage_from_display_data
from medimager.utils.i18n import t
from medimager.utils.logger import get_logger
from medimager.utils.settings import get_performance_manager


logger = get_logger(__name__)


@dataclass
class MprState:
    cursor_lps: np.ndarray
    plane_indices: dict[MprPlane, int] = field(default_factory=dict)
    views: dict[MprPlane, ViewPresentationState] = field(default_factory=dict)

    def copy_cursor(self) -> tuple[float, float, float]:
        return tuple(float(value) for value in self.cursor_lps)


class MprViewport(QGraphicsView):
    cursor_requested = Signal(object)
    scroll_requested = Signal(object, int)
    activated = Signal(object)
    maximize_requested = Signal(object)
    annotation_requested = Signal(str, object, object)
    annotation_edit_requested = Signal(str, str, object)

    def __init__(self, plane: MprPlane, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.plane = plane
        self.presentation_state = ViewPresentationState()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._plane_geometry: Optional[PlaneGeometry] = None
        self._current_pixels: Optional[np.ndarray] = None
        self._cursor_lps: Optional[tuple[float, float, float]] = None
        self._dragging_cursor = False
        self._interaction_mode = "default"
        self._annotation_tool = "default"
        self._annotation_start = None
        self._editing_control: Optional[tuple[str, str]] = None
        self._angle_points: list[np.ndarray] = []
        self._annotation_overlays: list[
            tuple[str, str, dict[str, list[float]], str]
        ] = []
        self._last_drag_position = None
        self._wl_drag_origin = None
        self._fit_mode = True
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#080b10"))
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(t(f"mpr.{plane.value}"))

    def set_reconstruction(
        self,
        reconstruction: ResampledPlane,
        cursor_lps: Sequence[float],
    ) -> None:
        self._plane_geometry = reconstruction.geometry
        self._current_pixels = reconstruction.pixels
        self._cursor_lps = tuple(float(value) for value in cursor_lps[:3])
        state = self.presentation_state
        rendered = render_frame(
            RenderRequest(
                pixels=reconstruction.pixels,
                window_width=state.window_width,
                window_level=state.window_level,
                inverted=state.inverted,
            )
        )
        image = qimage_from_display_data(rendered.pixels_uint8)
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(QRectF(image.rect()))
        mode = InterpolationMode.coerce(state.interpolation)
        smooth = mode is InterpolationMode.SMOOTH or (
            mode is InterpolationMode.ADAPTIVE and self.transform().m11() < 1.0
        )
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        self._pixmap_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation
            if smooth
            else Qt.TransformationMode.FastTransformation
        )
        if self._fit_mode:
            self.fit_to_window()
        self.viewport().update()

    def set_view_window(self, width: float, level: float) -> None:
        self.presentation_state.window_width = max(1.0, float(width))
        self.presentation_state.window_level = float(level)
        parent = self.parentWidget()
        workspace = parent
        while workspace is not None and not isinstance(workspace, MprWorkspace):
            workspace = workspace.parentWidget()
        if isinstance(workspace, MprWorkspace):
            workspace.refresh()

    def set_annotation_tool(self, tool: str) -> None:
        self._annotation_tool = tool
        self._annotation_start = None
        self._angle_points.clear()

    def set_annotation_overlays(
        self, overlays: list[tuple[str, str, dict[str, list[float]], str]]
    ) -> None:
        self._annotation_overlays = overlays
        self.viewport().update()

    def set_interaction_mode(self, mode: str) -> None:
        if mode in {"default", "pan", "zoom", "window_level"}:
            self._interaction_mode = mode
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if mode == "pan"
                else Qt.CursorShape.ArrowCursor
            )

    def fit_to_window(self) -> None:
        if not self._scene.sceneRect().isEmpty():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_mode = True
        self.presentation_state.fit_mode = True

    def actual_size(self) -> None:
        self.resetTransform()
        self._fit_mode = False
        self.presentation_state.fit_mode = False

    def reset_view(self) -> None:
        self.presentation_state.inverted = False
        self.fit_to_window()

    def invert(self) -> None:
        self.presentation_state.inverted = not self.presentation_state.inverted
        self.set_view_window(
            self.presentation_state.window_width,
            self.presentation_state.window_level,
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_to_window()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.activated.emit(self.plane)
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._last_drag_position = event.position()
        annotation_point = self._patient_at(event.position())
        if self._annotation_tool == "default":
            control = self._hit_annotation_control(event.position())
            if control is not None:
                self._editing_control = control
                event.accept()
                return
        if self._annotation_tool == "angle" and annotation_point is not None:
            self._angle_points.append(annotation_point)
            if len(self._angle_points) == 3:
                self.annotation_requested.emit(
                    "angle", self.plane, list(self._angle_points)
                )
                self._angle_points.clear()
            event.accept()
            return
        if (
            self._annotation_tool
            in {"measurement", "rectangle_roi", "circle_roi", "ellipse_roi"}
            and annotation_point is not None
        ):
            self._annotation_start = annotation_point
            event.accept()
            return
        if self._interaction_mode == "default" and self._plane_geometry is not None:
            self._dragging_cursor = True
            self._request_cursor(event.position())
        elif self._interaction_mode == "window_level":
            self._wl_drag_origin = (
                event.position(),
                self.presentation_state.window_width,
                self.presentation_state.window_level,
            )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if self._editing_control is not None:
            patient = self._patient_at(event.position())
            if patient is not None:
                annotation_id, point_key = self._editing_control
                self.annotation_edit_requested.emit(annotation_id, point_key, patient)
        elif self._dragging_cursor:
            self._request_cursor(event.position())
        elif self._interaction_mode == "pan" and self._last_drag_position is not None:
            delta = event.position() - self._last_drag_position
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            self._fit_mode = False
            self.presentation_state.fit_mode = False
            self.presentation_state.pan_center = self.mapToScene(
                self.viewport().rect().center()
            )
        elif self._interaction_mode == "zoom" and self._last_drag_position is not None:
            factor = float(np.exp((self._last_drag_position.y() - event.position().y()) / 120.0))
            target = np.clip(
                self.presentation_state.zoom * factor,
                ViewPresentationState.MIN_ZOOM,
                ViewPresentationState.MAX_ZOOM,
            )
            actual = float(target / self.presentation_state.zoom)
            self.scale(actual, actual)
            self.presentation_state.zoom = float(target)
            self._fit_mode = False
            self.presentation_state.fit_mode = False
        elif self._interaction_mode == "window_level" and self._wl_drag_origin is not None:
            origin, start_width, start_level = self._wl_drag_origin
            delta = event.position() - origin
            self.set_view_window(
                max(1.0, start_width + delta.x() * 2.0),
                start_level - delta.y() * 2.0,
            )
        self._last_drag_position = event.position()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._annotation_start is not None:
                end = self._patient_at(event.position())
                if end is not None and not np.allclose(end, self._annotation_start):
                    self.annotation_requested.emit(
                        self._annotation_tool,
                        self.plane,
                        [self._annotation_start, end],
                    )
                self._annotation_start = None
            self._dragging_cursor = False
            self._editing_control = None
            self._last_drag_position = None
            self._wl_drag_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.maximize_requested.emit(self.plane)
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = int(event.angleDelta().y() / 120)
        if steps:
            self.scroll_requested.emit(self.plane, steps)
            event.accept()
            return
        super().wheelEvent(event)

    def _patient_at(self, viewport_position) -> Optional[np.ndarray]:
        if self._plane_geometry is None:
            return None
        scene_point = self.mapToScene(viewport_position.toPoint())
        x = min(max(scene_point.x(), 0.0), self._plane_geometry.shape_hw[1] - 1)
        y = min(max(scene_point.y(), 0.0), self._plane_geometry.shape_hw[0] - 1)
        return self._plane_geometry.pixel_to_patient(x, y)

    def _request_cursor(self, viewport_position) -> None:
        patient = self._patient_at(viewport_position)
        if patient is not None:
            self.cursor_requested.emit(patient)

    def _hit_annotation_control(self, viewport_position) -> Optional[tuple[str, str]]:
        geometry = self._plane_geometry
        if geometry is None:
            return None
        scene_point = self.mapToScene(viewport_position.toPoint())
        scale = max(abs(self.transform().m11()), 1e-6)
        tolerance = 10.0 / scale
        closest = None
        closest_distance = tolerance
        for annotation_id, _kind, points_lps, _label in self._annotation_overlays:
            for point_key, point_lps in points_lps.items():
                candidate = QPointF(*geometry.patient_to_pixel(point_lps))
                distance = float(np.hypot(
                    candidate.x() - scene_point.x(), candidate.y() - scene_point.y()
                ))
                if distance <= closest_distance:
                    closest_distance = distance
                    closest = (annotation_id, point_key)
        return closest

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        geometry = self._plane_geometry
        cursor = self._cursor_lps
        if geometry is None or cursor is None:
            return
        x, y = geometry.patient_to_pixel(cursor)
        bounds = self._scene.sceneRect()
        colors = {
            MprPlane.AXIAL: QColor("#4aa3ff"),
            MprPlane.CORONAL: QColor("#56d364"),
            MprPlane.SAGITTAL: QColor("#ff6b6b"),
        }
        other_planes = [candidate for candidate in MprPlane if candidate is not self.plane]
        painter.save()
        painter.setPen(QPen(colors[other_planes[0]], 0))
        painter.drawLine(QPointF(bounds.left(), y), QPointF(bounds.right(), y))
        painter.setPen(QPen(colors[other_planes[1]], 0))
        painter.drawLine(QPointF(x, bounds.top()), QPointF(x, bounds.bottom()))
        painter.setPen(QPen(QColor("#f0f3f6"), 0))
        inset = bounds.adjusted(8, 8, -8, -8)
        position_axis = {
            MprPlane.AXIAL: 2,
            MprPlane.CORONAL: 1,
            MprPlane.SAGITTAL: 0,
        }[self.plane]
        title = f"{t(f'mpr.{self.plane.value}')}  {cursor[position_axis]:.1f} mm"
        painter.drawText(
            inset, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, title
        )
        markers = {
            MprPlane.AXIAL: ("R", "L", "A", "P"),
            MprPlane.CORONAL: ("R", "L", "S", "I"),
            MprPlane.SAGITTAL: ("A", "P", "S", "I"),
        }[self.plane]
        left, right, top, bottom = markers
        painter.drawText(inset, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, left)
        painter.drawText(inset, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right)
        painter.drawText(inset, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, top)
        painter.drawText(inset, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, bottom)
        self._draw_annotation_overlays(painter, geometry)
        painter.restore()

    def _draw_annotation_overlays(
        self, painter: QPainter, geometry: PlaneGeometry
    ) -> None:
        painter.setPen(QPen(QColor("#ffd43b"), 0))
        for _annotation_id, kind, points_lps, label in self._annotation_overlays:
            points = {
                key: QPointF(*geometry.patient_to_pixel(value))
                for key, value in points_lps.items()
            }
            if kind == "measurement":
                painter.drawLine(points["start"], points["end"])
                painter.drawText(points["end"] + QPointF(5, -5), label)
            elif kind == "angle":
                painter.drawLine(points["vertex"], points["point1"])
                painter.drawLine(points["vertex"], points["point3"])
                painter.drawText(points["vertex"] + QPointF(5, -5), label)
            elif kind == "rectangle_roi":
                painter.drawRect(QRectF(points["top_left"], points["bottom_right"]).normalized())
                painter.drawText(
                    points["bottom_right"] + QPointF(5, -5),
                    self._roi_stats_label(kind, points),
                )
            elif kind == "circle_roi":
                radius = np.hypot(
                    points["radius_edge"].x() - points["center"].x(),
                    points["radius_edge"].y() - points["center"].y(),
                )
                painter.drawEllipse(points["center"], radius, radius)
                painter.drawText(
                    points["radius_edge"] + QPointF(5, -5),
                    self._roi_stats_label(kind, points),
                )
            elif kind == "ellipse_roi":
                rx = np.hypot(
                    points["radius_x_edge"].x() - points["center"].x(),
                    points["radius_x_edge"].y() - points["center"].y(),
                )
                ry = np.hypot(
                    points["radius_y_edge"].x() - points["center"].x(),
                    points["radius_y_edge"].y() - points["center"].y(),
                )
                painter.drawEllipse(points["center"], rx, ry)
                painter.drawText(
                    points["radius_x_edge"] + QPointF(5, -5),
                    self._roi_stats_label(kind, points),
                )

    def _roi_stats_label(self, kind: str, points: dict[str, QPointF]) -> str:
        pixels = self._current_pixels
        if pixels is None or pixels.size == 0:
            return ""
        height, width = pixels.shape
        yy, xx = np.ogrid[:height, :width]
        if kind == "rectangle_roi":
            first, second = points["top_left"], points["bottom_right"]
            x0, x1 = sorted((first.x(), second.x()))
            y0, y1 = sorted((first.y(), second.y()))
            mask = (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)
        else:
            center = points["center"]
            if kind == "circle_roi":
                edge = points["radius_edge"]
                rx = ry = max(1e-6, float(np.hypot(edge.x() - center.x(), edge.y() - center.y())))
            else:
                x_edge, y_edge = points["radius_x_edge"], points["radius_y_edge"]
                rx = max(1e-6, float(np.hypot(x_edge.x() - center.x(), x_edge.y() - center.y())))
                ry = max(1e-6, float(np.hypot(y_edge.x() - center.x(), y_edge.y() - center.y())))
            mask = ((xx - center.x()) / rx) ** 2 + ((yy - center.y()) / ry) ** 2 <= 1.0
        values = np.asarray(pixels)[mask]
        values = values[np.isfinite(values)]
        if values.size == 0:
            return ""
        return f"μ {float(np.mean(values)):.1f}  σ {float(np.std(values)):.1f}"


class MprWorkspace(QWidget):
    build_finished = Signal(object)
    build_progress = Signal(int, int)
    active_plane_changed = Signal(object)
    request_return_to_2d = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._model = None
        self._series_id: Optional[str] = None
        self._resampler: Optional[OrthogonalMprResampler] = None
        self._state: Optional[MprState] = None
        self._cancel_event = Event()
        self._future = None
        self._build_generation = 0
        self._active_plane = MprPlane.AXIAL
        self._maximized_plane: Optional[MprPlane] = None
        self._pending_cursor: Optional[np.ndarray] = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(16)
        self._refresh_timer.timeout.connect(self._apply_pending_cursor)
        self._setup_ui()
        self.build_finished.connect(self._on_build_finished)
        self.build_progress.connect(self._on_build_progress)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        header = QFrame(self)
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel(t("mpr.ready"), header)
        self._progress = QProgressBar(header)
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        self._cancel_button = QPushButton(t("mpr.cancel"), header)
        self._cancel_button.setVisible(False)
        self._cancel_button.clicked.connect(self.cancel_build)
        self._back_button = QPushButton(t("mpr.return_to_2d"), header)
        self._back_button.clicked.connect(self.request_return_to_2d)
        header_layout.addWidget(self._status, 0, 0)
        header_layout.addWidget(self._progress, 0, 1)
        header_layout.addWidget(self._cancel_button, 0, 2)
        header_layout.addWidget(self._back_button, 0, 3)
        header_layout.setColumnStretch(0, 1)
        root.addWidget(header)

        self._viewport_container = QWidget(self)
        self._grid = QGridLayout(self._viewport_container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(3)
        self.viewports: dict[MprPlane, MprViewport] = {}
        for column, plane in enumerate(MprPlane):
            viewport = MprViewport(plane, self._viewport_container)
            viewport.cursor_requested.connect(self.set_cursor)
            viewport.scroll_requested.connect(self.scroll_plane)
            viewport.activated.connect(self.set_active_plane)
            viewport.maximize_requested.connect(self.toggle_maximize)
            viewport.annotation_requested.connect(self._create_annotation)
            viewport.annotation_edit_requested.connect(self._edit_annotation)
            self._grid.addWidget(viewport, 0, column)
            self._grid.setColumnStretch(column, 1)
            self.viewports[plane] = viewport
        root.addWidget(self._viewport_container, 1)

    @property
    def is_ready(self) -> bool:
        return self._resampler is not None and self._state is not None

    @property
    def active_viewer(self) -> MprViewport:
        return self.viewports[self._active_plane]

    def start_build(self, model, series_id: str, memory_budget_bytes: int) -> None:
        self.cancel_build()
        self._build_generation += 1
        generation = self._build_generation
        self._model = model
        self._series_id = series_id
        self._resampler = None
        self._state = None
        self._cancel_event = Event()
        self._status.setText(t("mpr.building"))
        self._progress.setRange(0, max(1, model.get_slice_count()))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._cancel_button.setVisible(True)

        def report(done: int, total: int) -> None:
            self.build_progress.emit(done, total)

        future = get_performance_manager().get_thread_pool().submit(
            VolumeBuilder.build,
            model,
            cancel_event=self._cancel_event,
            progress=report,
            memory_budget_bytes=memory_budget_bytes,
        )
        self._future = future

        def completed(done_future) -> None:
            try:
                result = done_future.result()
            except Exception as error:
                logger.exception("MPR volume build failed")
                result = VolumeBuildResult(GeometryStatus.DECODE_ERROR, detail=str(error))
            self.build_finished.emit((generation, result))

        future.add_done_callback(completed)

    def cancel_build(self) -> None:
        self._cancel_event.set()
        future = self._future
        if future is not None:
            future.cancel()
        self._future = None

    def clear(self) -> None:
        self.cancel_build()
        self._model = None
        self._series_id = None
        self._resampler = None
        self._state = None

    def _on_build_progress(self, done: int, total: int) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)

    def _on_build_finished(self, payload) -> None:
        generation, result = payload
        if generation != self._build_generation:
            return
        self._future = None
        self._progress.setVisible(False)
        self._cancel_button.setVisible(False)
        if not result.compatible or result.volume is None:
            self._status.setText(t(result.detail) if result.detail.startswith("mpr.") else result.detail)
            return
        try:
            self._resampler = OrthogonalMprResampler(result.volume)
        except RuntimeError as error:
            self._status.setText(t(str(error)))
            return
        model = self._model
        views = {
            plane: ViewPresentationState(
                series_id=self._series_id,
                window_width=float(getattr(model, "window_width", 400.0)),
                window_level=float(getattr(model, "window_level", 40.0)),
            )
            for plane in MprPlane
        }
        self._state = MprState(
            cursor_lps=np.asarray(result.volume.geometry.center_lps, dtype=np.float64),
            views=views,
        )
        self._update_plane_indices()
        for plane, state in views.items():
            self.viewports[plane].presentation_state = state
        self._status.setText(t("mpr.ready"))
        self.refresh()

    def refresh(self) -> None:
        if not self.is_ready:
            return
        assert self._resampler is not None and self._state is not None
        cursor = self._state.cursor_lps
        for plane, viewport in self.viewports.items():
            if self._maximized_plane is not None and plane is not self._maximized_plane:
                continue
            viewport.set_reconstruction(self._resampler.reconstruct(plane, cursor), cursor)
            viewport.set_annotation_overlays(self._annotation_overlays())

    def set_cursor(self, point_lps) -> None:
        if not self.is_ready:
            return
        self._pending_cursor = np.asarray(point_lps, dtype=np.float64)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _apply_pending_cursor(self) -> None:
        if self._pending_cursor is None or not self.is_ready:
            return
        assert self._resampler is not None and self._state is not None
        bounds = self._resampler.volume.geometry.patient_bounds
        self._state.cursor_lps = np.asarray(
            [np.clip(self._pending_cursor[axis], *bounds[axis]) for axis in range(3)],
            dtype=np.float64,
        )
        self._pending_cursor = None
        self._update_plane_indices()
        self.refresh()

    def _update_plane_indices(self) -> None:
        if not self.is_ready:
            return
        assert self._resampler is not None and self._state is not None
        bounds = self._resampler.volume.geometry.patient_bounds
        cursor = self._state.cursor_lps
        spacing = self._resampler.sampling_mm
        self._state.plane_indices = {
            MprPlane.SAGITTAL: int(round((cursor[0] - bounds[0][0]) / spacing)),
            MprPlane.CORONAL: int(round((cursor[1] - bounds[1][0]) / spacing)),
            MprPlane.AXIAL: int(round((cursor[2] - bounds[2][0]) / spacing)),
        }

    def scroll_plane(self, plane: MprPlane, steps: int) -> None:
        if not self.is_ready:
            return
        assert self._resampler is not None and self._state is not None
        geometry = self._resampler.plane_geometry(plane, self._state.cursor_lps)
        increment = np.asarray(geometry.normal_lps) * self._resampler.sampling_mm * int(steps)
        self.set_cursor(self._state.cursor_lps + increment)

    def set_interaction_mode(self, mode: str) -> None:
        for viewport in self.viewports.values():
            viewport.set_interaction_mode(mode)

    def set_annotation_tool(self, tool: str) -> None:
        for viewport in self.viewports.values():
            viewport.set_annotation_tool(tool)

    def _creation_plane(self, plane: MprPlane) -> dict[str, list[float]]:
        geometry = self.viewports[plane]._plane_geometry
        if geometry is None:
            raise RuntimeError("MPR plane is not ready")
        return {
            "origin_lps": list(geometry.origin_lps),
            "column_axis_lps": list(geometry.u_axis_lps),
            "row_axis_lps": list(geometry.v_axis_lps),
            "normal_lps": list(geometry.normal_lps),
            "pixel_spacing_rc": [geometry.spacing_uv[1], geometry.spacing_uv[0]],
        }

    def _create_annotation(self, tool: str, plane: MprPlane, raw_points) -> None:
        if self._model is None or not self.is_ready:
            return
        points = [np.asarray(point, dtype=np.float64) for point in raw_points]
        creation_plane = self._creation_plane(plane)
        index, _ = patient_to_target_pixel(self._model, points[0])
        projected = [patient_to_pixel_on_slice(self._model, point, index) for point in points]
        if tool == "measurement":
            item = MeasurementData(
                str(uuid4()), index, QPointF(*projected[0]), QPointF(*projected[1]),
                float(np.linalg.norm(points[1] - points[0])), "mm",
            )
            item.points_lps = {"start": points[0].tolist(), "end": points[1].tolist()}
            item.creation_plane = creation_plane
            self._model.add_measurement(item)
        elif tool == "angle" and len(points) == 3:
            first = points[0] - points[1]
            second = points[2] - points[1]
            denominator = np.linalg.norm(first) * np.linalg.norm(second)
            if denominator <= 1e-8:
                return
            angle = float(
                np.degrees(
                    np.arccos(np.clip(np.dot(first, second) / denominator, -1, 1))
                )
            )
            item = AngleMeasurementData(
                str(uuid4()), index, QPointF(*projected[0]), QPointF(*projected[1]),
                QPointF(*projected[2]), angle,
            )
            item.points_lps = {
                "point1": points[0].tolist(), "vertex": points[1].tolist(),
                "point3": points[2].tolist(),
            }
            item.creation_plane = creation_plane
            self._model.add_angle_measurement(item)
        elif tool in {"rectangle_roi", "circle_roi", "ellipse_roi"}:
            if tool == "rectangle_roi":
                item = RectangleROI(
                    (round(projected[0][1]), round(projected[0][0])),
                    (round(projected[1][1]), round(projected[1][0])), index,
                )
                stored = {"top_left": points[0].tolist(), "bottom_right": points[1].tolist()}
            elif tool == "circle_roi":
                radius = max(1, round(np.hypot(
                    projected[1][0] - projected[0][0], projected[1][1] - projected[0][1]
                )))
                item = CircleROI(
                    (round(projected[0][1]), round(projected[0][0])), radius, index
                )
                stored = {"center": points[0].tolist(), "radius_edge": points[1].tolist()}
            else:
                viewport_geometry = self.viewports[plane]._plane_geometry
                assert viewport_geometry is not None
                first_uv = np.asarray(viewport_geometry.patient_to_pixel(points[0]))
                second_uv = np.asarray(viewport_geometry.patient_to_pixel(points[1]))
                center_uv = (first_uv + second_uv) / 2
                center = viewport_geometry.pixel_to_patient(*center_uv)
                x_edge = viewport_geometry.pixel_to_patient(second_uv[0], center_uv[1])
                y_edge = viewport_geometry.pixel_to_patient(center_uv[0], second_uv[1])
                center_px = patient_to_pixel_on_slice(self._model, center, index)
                x_px = patient_to_pixel_on_slice(self._model, x_edge, index)
                y_px = patient_to_pixel_on_slice(self._model, y_edge, index)
                item = EllipseROI(
                    (round(center_px[1]), round(center_px[0])),
                    max(1, round(np.hypot(x_px[0] - center_px[0], x_px[1] - center_px[1]))),
                    max(1, round(np.hypot(y_px[0] - center_px[0], y_px[1] - center_px[1]))),
                    index,
                )
                stored = {
                    "center": center.tolist(), "radius_x_edge": x_edge.tolist(),
                    "radius_y_edge": y_edge.tolist(),
                }
            item.points_lps = stored
            item.creation_plane = creation_plane
            self._model.add_roi(item)
        self.refresh()

    def _edit_annotation(self, annotation_id: str, point_key: str, point_lps) -> None:
        if self._model is None:
            return
        collections = (
            getattr(self._model, "measurements", []),
            getattr(self._model, "angle_measurements", []),
            getattr(self._model, "rois", []),
        )
        item = next(
            (candidate for items in collections for candidate in items
             if candidate.id == annotation_id),
            None,
        )
        points = getattr(item, "points_lps", None) if item is not None else None
        if not isinstance(points, dict) or point_key not in points:
            return
        points[point_key] = np.asarray(point_lps, dtype=np.float64).tolist()
        if isinstance(item, MeasurementData):
            item.distance = float(np.linalg.norm(
                np.asarray(points["end"]) - np.asarray(points["start"])
            ))
        elif isinstance(item, AngleMeasurementData):
            first = np.asarray(points["point1"]) - np.asarray(points["vertex"])
            second = np.asarray(points["point3"]) - np.asarray(points["vertex"])
            denominator = np.linalg.norm(first) * np.linalg.norm(second)
            if denominator > 1e-8:
                item.angle_degrees = float(np.degrees(np.arccos(
                    np.clip(np.dot(first, second) / denominator, -1, 1)
                )))
        marker = getattr(self._model, "mark_annotations_dirty", None)
        if callable(marker):
            marker()
        self.refresh()

    def _annotation_overlays(
        self,
    ) -> list[tuple[str, str, dict[str, list[float]], str]]:
        if self._model is None:
            return []
        result = []
        for item in getattr(self._model, "measurements", []):
            points = getattr(item, "points_lps", None)
            if points:
                result.append((item.id, "measurement", points, f"{item.distance:.1f} {item.unit}"))
        for item in getattr(self._model, "angle_measurements", []):
            points = getattr(item, "points_lps", None)
            if points:
                result.append((item.id, "angle", points, f"{item.angle_degrees:.1f}°"))
        for item in getattr(self._model, "rois", []):
            points = getattr(item, "points_lps", None)
            if points:
                kind = {
                    "Rectangle": "rectangle_roi", "Circle": "circle_roi",
                    "Ellipse": "ellipse_roi",
                }.get(item.shape.value)
                if kind:
                    result.append((item.id, kind, points, ""))
        return result

    def set_active_plane(self, plane: MprPlane) -> None:
        self._active_plane = plane
        self.active_plane_changed.emit(plane)

    def toggle_maximize(self, plane: MprPlane) -> None:
        self._maximized_plane = None if self._maximized_plane is plane else plane
        for candidate, viewport in self.viewports.items():
            viewport.setVisible(
                self._maximized_plane is None or candidate is self._maximized_plane
            )
        self.refresh()

