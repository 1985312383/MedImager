"""Deterministic, real MedImager QWidget surfaces for release visual QA.

The provider intentionally builds the same widgets used by the desktop
application while keeping all input data and settings in memory.  It never
opens a patient study, writes user settings, or relies on generated demo DICOM
files.  Only one surface is kept alive at a time because the visual harness
captures a provider result before requesting the next scenario.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QWidget,
)

from medimager.core.image_data_model import ImageDataModel
from medimager.core.local_source import (
    LocalSourceKind,
    RecentStudyEntry,
)
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.series_view_binding import SeriesViewBindingManager
from medimager.core.settings_registry import (
    DEFAULT_SETTINGS_REGISTRY,
    SettingSpec,
)
from medimager.core.volume_geometry import (
    GeometryStatus,
    VolumeBuildResult,
    VolumeData,
    VolumeGeometry,
)
from medimager.demo.catalog import load_demo_catalog
from medimager.qa.visual_regression import VisualScenario
from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.ui.main_toolbar import ViewerToolbar, create_main_toolbar
from medimager.ui.mpr_workspace import MprWorkspace
from medimager.ui.multi_viewer_grid import MultiViewerGrid
from medimager.ui.panels.series_panel import SeriesPanel
from medimager.ui.start_center import (
    RecentAvailability,
    StartCenter,
    StartCenterSample,
)
from medimager.utils.i18n import get_translation_manager, t
from medimager.utils.settings import PerformanceManager
from medimager.utils.theme_manager import ThemeManager


class _MemorySettingsManager(QObject):
    """SettingsManager-compatible store that cannot persist outside its root."""

    setting_changed = Signal(str, object)
    performance_settings_changed = Signal(str, object)

    def __init__(self, config_root: Path) -> None:
        super().__init__()
        self.registry = DEFAULT_SETTINGS_REGISTRY
        self.use_json = True
        self._config_root = config_root
        self._values = self.registry.defaults()
        self._values.update(
            {
                "language": "en_US",
                "ui_theme": "dark",
                "ui.density": "compact",
                "ui.icon_size": 24,
                "ui.font_scale": 100,
                "display.window_level_strategy": "dicom",
                "display.show_view_title": True,
                "display.show_view_status": True,
                "overlay.show_orientation": True,
                "overlay.show_slice_position": True,
                "overlay.show_scale": True,
                "overlay.show_patient": True,
                "overlay.show_pixel_value": False,
                "privacy.screen_mode": False,
            }
        )
        self._performance = PerformanceManager()
        self._performance.set_thread_count(2)
        self._performance.set_cache_size(256)

    def get_setting(self, key: str, default_value: Any = None) -> Any:
        if key not in self._values:
            return default_value
        return self.registry.coerce(key, self._values[key])

    def get_typed(self, setting: str | SettingSpec[Any]) -> Any:
        spec = setting if isinstance(setting, SettingSpec) else self.registry.require(setting)
        return self.get_setting(spec.key, spec.default)

    def set_setting(self, key: str, value: Any) -> None:
        self.set_many({key: value})

    def set_typed(self, setting: str | SettingSpec[Any], value: Any) -> Any:
        spec = setting if isinstance(setting, SettingSpec) else self.registry.require(setting)
        normalized = spec.coerce(value)
        self.set_many({spec.key: normalized})
        return normalized

    def set_many(self, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            normalized = self.registry.coerce(str(key), value)
            self._values[str(key)] = normalized
            if key == "thread_count":
                self._performance.set_thread_count(int(normalized))
                self.performance_settings_changed.emit(str(key), normalized)
            elif key == "cache_size":
                self._performance.set_cache_size(int(normalized))
                self.performance_settings_changed.emit(str(key), normalized)
            self.setting_changed.emit(str(key), normalized)

    def remove_setting(self, key: str) -> None:
        self._values.pop(str(key), None)

    def get_all_settings(self) -> dict[str, Any]:
        return dict(self._values)

    def get_config_directory(self) -> Path:
        self._config_root.mkdir(parents=True, exist_ok=True)
        return self._config_root

    def get_performance_manager(self) -> PerformanceManager:
        return self._performance

    def save_settings(self) -> bool:
        """Match SettingsManager without writing a portable settings file."""

        return True

    def shutdown(self) -> None:
        self._performance.shutdown()


class VisualWorkbenchShell(QMainWindow):
    """Deterministic release shell composed from production reading widgets.

    This intentionally is not a second MainWindow implementation.  It supplies
    only the callbacks required by the production ``ViewerToolbar`` and lays
    out the production ``SeriesPanel`` beside one real release surface.  The
    shell gives pixel baselines stable menu/toolbar/navigation/workspace/status
    chrome without loading application state or touching ``main_window.py``.
    """

    def __init__(
        self,
        settings_manager: _MemorySettingsManager,
        theme_manager: ThemeManager,
        series_manager: MultiSeriesManager,
        primary_surface: QWidget,
        *,
        navigator_visible: bool,
    ) -> None:
        super().__init__()
        self.setObjectName("VisualWorkbenchShell")
        self.settings_manager = settings_manager
        self.theme_manager = theme_manager
        self.series_manager = series_manager
        self.primary_surface = primary_surface
        self.sync_manager = None
        self._cine_fps = 10
        self._image_required_actions = []
        self._image_required_widgets = []
        self._active_tool_name = "default"

        self.toolbar: ViewerToolbar = create_main_toolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.menuBar().addMenu(t("mainwindow.file_f"))
        self.menuBar().addMenu(t("mainwindow.view"))
        self.menuBar().addMenu(t("mainwindow.help_h"))

        central = QWidget(self)
        central.setObjectName("VisualWorkbenchCentral")
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(3)

        self.binding_manager = SeriesViewBindingManager(series_manager, self)
        self.navigator = SeriesPanel(
            series_manager,
            self.binding_manager,
            central,
            thumbnail_loading=False,
        )
        # The production navigator expands its proxy hierarchy with a zero
        # delay timer after show/model-reset events. Release surfaces never
        # mutate their model, so keep the stable collapsed hierarchy and avoid
        # retaining a deferred proxy QModelIndex traversal across scenario
        # teardown.
        visual_series_list = self.navigator._series_list
        visual_series_list._browser_expand_timer.stop()
        visual_series_list._schedule_browser_expand = lambda: None
        cards_index = visual_series_list._density_combo.findData("cards")
        if cards_index >= 0:
            visual_series_list._density_combo.setCurrentIndex(cards_index)
        self._expand_stable_navigator_hierarchy(visual_series_list)
        self.navigator.setObjectName("VisualSeriesNavigator")
        self.navigator.setMinimumWidth(220)
        self.navigator.setMaximumWidth(300)
        self.navigator.setVisible(navigator_visible)
        central_layout.addWidget(self.navigator)

        self.workspace_host = QWidget(central)
        self.workspace_host.setObjectName("VisualWorkspaceHost")
        workspace_layout = QHBoxLayout(self.workspace_host)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        if isinstance(primary_surface, SettingsDialog):
            primary_surface.setModal(False)
            primary_surface.setWindowFlags(Qt.WindowType.Widget)
        workspace_layout.addWidget(primary_surface)
        central_layout.addWidget(self.workspace_host, 1)
        self.setCentralWidget(central)

        self.statusBar().setObjectName("VisualWorkbenchStatusBar")
        self.statusBar().showMessage(
            f"{t('mainwindow.ready')}  ·  {t('startcenter.disclaimer')}"
        )
        self._apply_data_availability()

    @staticmethod
    def _expand_stable_navigator_hierarchy(series_list) -> None:
        """Expand the immutable QA model without a teardown-racing timer."""

        proxy = series_list._browser_proxy
        view = series_list._browser_view
        for patient_row in range(proxy.rowCount()):
            patient_index = proxy.index(patient_row, 0)
            if not patient_index.isValid():
                continue
            view.setExpanded(patient_index, True)
            for study_row in range(proxy.rowCount(patient_index)):
                study_index = proxy.index(study_row, 0, patient_index)
                if study_index.isValid():
                    view.setExpanded(study_index, True)

    def _apply_data_availability(self) -> None:
        has_images = bool(self.series_manager.get_series_count())
        for action in self._image_required_actions:
            action.setEnabled(has_images)
        for widget in self._image_required_widgets:
            widget.setEnabled(has_images)
        self.mpr_action.setEnabled(has_images)
        self.mpr_action.setChecked(
            isinstance(self.primary_surface, MprWorkspace)
            and self.primary_surface.is_ready
        )

    def _on_tool_selected(self, tool_name: str) -> None:
        self._active_tool_name = str(tool_name)

    def _apply_viewer_transform(self, _transform: str) -> None:
        return

    def _auto_assign_all_series(self) -> None:
        return

    def _clear_all_bindings(self) -> None:
        return

    def _cine_set_fps(self, fps: int) -> None:
        self._cine_fps = int(fps)

    def _cine_toggle_play(self) -> None:
        return

    def _on_sync_pan_changed(self, _enabled: bool) -> None:
        return

    def _on_sync_position_changed(self, _mode: str) -> None:
        return

    def _on_sync_window_level_changed(self, _enabled: bool) -> None:
        return

    def _on_sync_zoom_changed(self, _enabled: bool) -> None:
        return

    def _open_custom_wl_dialog(self) -> None:
        return

    def _set_layout(self, _layout) -> None:
        return

    def _set_window_level_preset(self, _width: float, _level: float) -> None:
        return

    def _toggle_mpr_workspace(self, _checked: bool = False) -> None:
        return


def _ct_volume(phase: int, *, depth: int = 24, size: int = 112) -> np.ndarray:
    z, y, x = np.indices((depth, size, size), dtype=np.float32)
    cx = (size - 1.0) / 2.0
    cy = (size - 1.0) / 2.0
    nx = (x - cx) / (size * 0.44)
    ny = (y - cy) / (size * 0.39)
    nz = (z - (depth - 1.0) / 2.0) / (depth * 0.55)
    body = nx**2 + ny**2 + nz**2 * 0.18 <= 1.0
    left_lung = ((nx + 0.31) / 0.24) ** 2 + ((ny + 0.13) / 0.43) ** 2 <= 1.0
    right_lung = ((nx - 0.31) / 0.24) ** 2 + ((ny + 0.13) / 0.43) ** 2 <= 1.0
    vertebra = (nx / 0.12) ** 2 + ((ny - 0.42) / 0.12) ** 2 <= 1.0
    aorta = ((nx + 0.07) / 0.065) ** 2 + ((ny - 0.20) / 0.065) ** 2 <= 1.0
    liver = ((nx - 0.29) / 0.34) ** 2 + ((ny - 0.23) / 0.26) ** 2 <= 1.0
    lesion = ((nx - 0.29) / 0.075) ** 2 + ((ny - 0.19) / 0.06) ** 2 <= 1.0

    volume = np.full((depth, size, size), -1000.0, dtype=np.float32)
    texture = 10.0 * np.sin(x / 6.0) + 7.0 * np.cos(y / 8.0) + z * 0.8
    volume[body] = 35.0 + texture[body]
    volume[left_lung | right_lung] = -730.0 + texture[left_lung | right_lung]
    volume[vertebra] = 850.0 + texture[vertebra]
    volume[liver] = 58.0 + texture[liver]
    enhancements = (0.0, 185.0, 95.0, 45.0)
    liver_shifts = (0.0, 42.0, 24.0, 12.0)
    volume[aorta] += enhancements[phase % len(enhancements)]
    volume[liver] += liver_shifts[phase % len(liver_shifts)]
    volume[lesion] += (15.0, 95.0, 55.0, 30.0)[phase % 4]
    return volume


def _mr_volume(sequence: int, *, depth: int = 24, size: int = 112) -> np.ndarray:
    z, y, x = np.indices((depth, size, size), dtype=np.float32)
    cx = (size - 1.0) / 2.0
    cy = (size - 1.0) / 2.0
    nx = (x - cx) / (size * 0.41)
    ny = (y - cy) / (size * 0.47)
    nz = (z - (depth - 1.0) / 2.0) / (depth * 0.58)
    brain = nx**2 + ny**2 + nz**2 * 0.20 <= 1.0
    white = (nx / 0.72) ** 2 + (ny / 0.76) ** 2 + nz**2 * 0.28 <= 1.0
    ventricle_left = ((nx + 0.14) / 0.09) ** 2 + (ny / 0.20) ** 2 <= 1.0
    ventricle_right = ((nx - 0.14) / 0.09) ** 2 + (ny / 0.20) ** 2 <= 1.0
    ventricles = ventricle_left | ventricle_right
    lesion = ((nx - 0.34) / 0.11) ** 2 + ((ny + 0.12) / 0.09) ** 2 <= 1.0
    texture = 5.0 * np.sin(x / 4.5) + 4.0 * np.cos(y / 6.5) + z * 0.35

    values = (
        (72.0, 112.0, 20.0, 86.0),
        (105.0, 72.0, 180.0, 155.0),
        (110.0, 76.0, 34.0, 172.0),
        (52.0, 44.0, 32.0, 225.0),
    )[sequence % 4]
    gray_value, white_value, fluid_value, lesion_value = values
    volume = np.full((depth, size, size), 4.0, dtype=np.float32)
    volume[brain] = gray_value + texture[brain]
    volume[white] = white_value + texture[white]
    volume[ventricles] = fluid_value + texture[ventricles] * 0.25
    volume[lesion] = lesion_value + texture[lesion]
    return volume


def _series_model(
    volume: np.ndarray,
    *,
    modality: str,
    description: str,
    series_number: int,
) -> ImageDataModel:
    model = ImageDataModel()
    window_width, window_level = ((1400.0, -250.0) if modality == "CT" else (240.0, 105.0))
    metadata = {
        "Modality": modality,
        "SeriesDescription": description,
        "SeriesNumber": series_number,
        "PatientName": "Synthetic^Teaching",
        "StudyDescription": "Deterministic visual QA",
        "Rows": int(volume.shape[1]),
        "Columns": int(volume.shape[2]),
        "PixelSpacing": [0.8, 0.8],
        "SliceThickness": 1.5,
        "SpacingBetweenSlices": 1.5,
        "ImageOrientationPatient": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "ImagePositionPatient": [-44.4, -44.4, -17.25],
        "WindowWidth": window_width,
        "WindowCenter": window_level,
    }
    if not model.load_single_image(volume.astype(np.float32, copy=False), metadata):
        raise RuntimeError(f"Could not load deterministic {description} volume")
    model.set_window(window_width, window_level)
    model.set_current_slice(model.get_slice_count() // 2)
    return model


class RealMedImagerSurfaceProvider:
    """Build the 12 release surfaces from actual MedImager QWidget classes."""

    def __init__(self) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("Real visual surfaces require a QApplication")
        self._app = app
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="medimager-visual-qa-"
        )
        root = Path(self._temporary_directory.name)
        self.settings = _MemorySettingsManager(root / "config")
        self.theme_manager = ThemeManager(self.settings)
        self._translation_manager = get_translation_manager()
        self._original_language = self._translation_manager.current_language()
        self._original_stylesheet = app.styleSheet()
        self._original_font = QFont(app.font())
        self._active_surface: QWidget | None = None
        self._closed = False

        # ImageViewer and MultiViewerGrid use the established settings accessor.
        # Replace its process-local singleton only for the provider lifetime and
        # restore it exactly on close; the in-memory object never writes settings.
        from medimager.utils import settings as settings_module

        self._settings_module = settings_module
        self._previous_settings_manager = settings_module._settings_manager
        settings_module._settings_manager = self.settings
        app.setFont(QFont("Segoe UI", 9))

    def __enter__(self) -> RealMedImagerSurfaceProvider:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def __call__(self, scenario: VisualScenario) -> QWidget:
        if self._closed:
            raise RuntimeError("The visual surface provider is closed")
        self._dispose_active_surface()
        self._translation_manager.set_language(scenario.language)
        self.settings.set_many(
            {"language": scenario.language, "ui_theme": scenario.theme}
        )
        self.theme_manager.current_theme = scenario.theme
        self.theme_manager.apply_theme(scenario.theme)

        builders = {
            "start_center": self._build_start_center,
            "ct_2x2": lambda: self._build_grid("CT"),
            "reference_lines": lambda: self._build_grid("CT", reference_lines=True),
            "mr_2x2": lambda: self._build_grid("MR"),
            "mpr": self._build_mpr,
            "geometry_rejection": self._build_geometry_rejection,
            "settings": self._build_settings,
        }
        try:
            primary_surface = builders[scenario.surface]()
        except KeyError as error:
            raise KeyError(f"Unknown MedImager visual surface: {scenario.surface}") from error
        series_manager, navigator_visible = self._manager_for_surface(
            primary_surface,
            scenario.surface,
        )
        surface = VisualWorkbenchShell(
            self.settings,
            self.theme_manager,
            series_manager,
            primary_surface,
            navigator_visible=navigator_visible,
        )
        surface.setProperty("visualScenarioKey", scenario.key)
        surface.setProperty("visualScenarioSurface", scenario.surface)
        primary_surface.setProperty("visualScenarioKey", scenario.key)
        primary_surface.setProperty("visualScenarioSurface", scenario.surface)
        self._active_surface = surface
        self._app.processEvents()
        return surface

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._dispose_active_surface()
        if self._settings_module._settings_manager is self.settings:
            self._settings_module._settings_manager = self._previous_settings_manager
        self._translation_manager.set_language(self._original_language)
        self._app.setStyleSheet(self._original_stylesheet)
        self._app.setFont(self._original_font)
        self.settings.shutdown()
        self._temporary_directory.cleanup()

    def _dispose_active_surface(self) -> None:
        surface = self._active_surface
        self._active_surface = None
        if surface is None:
            return
        surface.close()
        surface.deleteLater()
        self._app.processEvents()

    def _manager_for_surface(
        self,
        primary_surface: QWidget,
        surface_name: str,
    ) -> tuple[MultiSeriesManager, bool]:
        if isinstance(primary_surface, MultiViewerGrid):
            return primary_surface._series_manager, True

        manager = MultiSeriesManager()
        if isinstance(primary_surface, MprWorkspace):
            model = getattr(primary_surface, "_visual_model", None)
            description = (
                "Arterial MPR"
                if surface_name == "mpr"
                else "Irregular Spacing · MPR Rejected"
            )
            if model is None:
                model = _series_model(
                    _ct_volume(0, depth=16, size=80),
                    modality="CT",
                    description=description,
                    series_number=1,
                )
            series_id = f"visual-{surface_name}"
            manager.add_series(
                SeriesInfo(
                    series_id=series_id,
                    patient_name="Synthetic Teaching",
                    study_description="Geometry Lab",
                    series_description=description,
                    modality="CT",
                    study_date="20260115",
                    slice_count=model.get_slice_count(),
                    series_number="1",
                    study_instance_uid="2.25.260000000000000000000000000000000001",
                    series_instance_uid=f"2.25.2600000000000000000000000000000{len(surface_name):05d}",
                    frame_of_reference_uid="2.25.260000000000000000000000000000000099",
                    orientation="axial",
                )
            )
            manager.load_series_data(series_id, model)
            manager.bind_series_to_view(manager.get_active_view_id(), series_id)
            return manager, True
        return manager, False

    def _build_start_center(self) -> StartCenter:
        center = StartCenter()
        center.set_samples(
            tuple(
                StartCenterSample(
                    sample_id=spec.id.value,
                    title=t(spec.title_key),
                    subtitle=t(spec.description_key),
                    preview_path=str(spec.preview_path),
                )
                for spec in load_demo_catalog()
            )
        )
        entries = (
            RecentStudyEntry(
                entry_id="visual-ct",
                source_kind=LocalSourceKind.FOLDER,
                source_path=r"C:\MedImager Samples\CT Multiphase",
                study_key="9e4827f161c4d0aa",
                display_label="CT Multiphase Teaching Study",
                study_date="2026-01-15",
                modalities=("CT",),
                series_count=4,
                last_opened_at=1_768_435_200.0,
                pinned=True,
            ),
            RecentStudyEntry(
                entry_id="visual-mr",
                source_kind=LocalSourceKind.FOLDER,
                source_path=r"D:\Teaching Media\MR Brain",
                study_key="1bd34fd7669e4fb1",
                display_label="MR Brain Teaching Study",
                study_date="2026-01-14",
                modalities=("MR",),
                series_count=4,
                last_opened_at=1_768_348_800.0,
            ),
        )
        center.set_recent_entries(
            entries,
            {
                "visual-ct": RecentAvailability.AVAILABLE,
                "visual-mr": RecentAvailability.MISSING,
            },
        )
        center.set_privacy_mode(False)
        return center

    def _build_grid(
        self,
        modality: str,
        *,
        reference_lines: bool = False,
    ) -> MultiViewerGrid:
        manager = MultiSeriesManager()
        grid = MultiViewerGrid(manager)
        grid.theme_manager = self.theme_manager
        self.theme_manager.register_component(grid)
        if not manager.set_layout(2, 2) or not grid.set_layout(2, 2):
            raise RuntimeError("Could not create the deterministic 2x2 grid")

        descriptions = (
            ("Non-contrast", "Arterial", "Venous", "Coronal Reference")
            if modality == "CT"
            else ("T1", "T2", "FLAIR", "DWI")
        )
        models: list[ImageDataModel] = []
        view_ids = manager.get_all_view_ids()
        for index, (view_id, description) in enumerate(zip(view_ids, descriptions, strict=True)):
            volume = _ct_volume(index) if modality == "CT" else _mr_volume(index)
            series_id = f"visual-{modality.lower()}-{index + 1}"
            model = _series_model(
                volume,
                modality=modality,
                description=description,
                series_number=index + 1,
            )
            info = SeriesInfo(
                series_id=series_id,
                patient_name="Synthetic Teaching",
                patient_id="SYNTHETIC-VISUAL-QA",
                study_description="Deterministic visual QA",
                series_description=description,
                modality=modality,
                study_date="20260115",
                slice_count=model.get_slice_count(),
                series_number=str(index + 1),
                study_instance_uid="2.25.260000000000000000000000000000000001",
                series_instance_uid=f"2.25.260000000000000000000000000000001{index + 1:02d}",
                frame_of_reference_uid="2.25.260000000000000000000000000000000099",
                orientation="axial" if index < 3 else "coronal",
            )
            manager.add_series(info)
            manager.load_series_data(series_id, model)
            if not manager.bind_series_to_view(view_id, series_id):
                raise RuntimeError(f"Could not bind {series_id} to {view_id}")
            models.append(model)

        manager.set_active_view(view_ids[0])
        if reference_lines:
            for index, view_id in enumerate(view_ids):
                frame = grid.get_view_frame(view_id)
                if frame is None:
                    continue
                offset = float(index * 5)
                frame.image_viewer.show_reference_line(
                    QPointF(8.0, 54.0 + offset),
                    QPointF(104.0, 48.0 - offset),
                )
                frame.image_viewer.show_patient_cursor(QPointF(56.0, 56.0))

        # Keep explicit references on the real widget for inspection and to
        # document that no placeholder raster was used.
        grid._visual_models = tuple(models)
        QTimer.singleShot(0, grid._fit_all_bound_views_to_window)
        return grid

    def _build_mpr_model(self) -> tuple[ImageDataModel, VolumeData]:
        pixels = _ct_volume(1, depth=32, size=96).astype(np.float32, copy=False)
        model = _series_model(
            pixels,
            modality="CT",
            description="Arterial MPR",
            series_number=2,
        )
        geometry = VolumeGeometry(
            origin_lps=(-47.5, -47.5, -23.25),
            direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            spacing_xyz=(1.0, 1.0, 1.5),
            shape_zyx=tuple(int(value) for value in pixels.shape),
            frame_of_reference_uid="2.25.260000000000000000000000000000000099",
            source_frame_indices=tuple(range(pixels.shape[0])),
        )
        volume = VolumeData(
            pixels_zyx=pixels,
            geometry=geometry,
            modality="CT",
            series_instance_uid="2.25.260000000000000000000000000000001002",
        )
        return model, volume

    def _build_mpr(self) -> MprWorkspace:
        model, volume = self._build_mpr_model()
        workspace = MprWorkspace()
        workspace._model = model
        workspace._series_id = "visual-ct-mpr"
        workspace._build_generation = 1
        workspace._on_build_finished(
            (1, VolumeBuildResult(GeometryStatus.COMPATIBLE, volume=volume))
        )
        if not workspace.is_ready:
            raise RuntimeError("The deterministic MPR surface did not become ready")
        workspace._visual_model = model
        return workspace

    def _build_geometry_rejection(self) -> MprWorkspace:
        workspace = MprWorkspace()
        workspace._build_generation = 1
        workspace._on_build_finished(
            (
                1,
                VolumeBuildResult(
                    GeometryStatus.NON_UNIFORM_SPACING,
                    detail="mpr.non_uniform_spacing",
                ),
            )
        )
        return workspace

    def _build_settings(self) -> SettingsDialog:
        dialog = SettingsDialog(self.settings)
        dialog.setModal(False)
        return dialog


def critical_widgets_for_surface(
    _scenario: VisualScenario,
    surface: QWidget,
) -> tuple[QWidget, ...]:
    """Return controls that must remain directly visible at high DPI.

    Scroll-area contents and hover-only MPR controls are intentionally omitted:
    they may extend beyond the viewport while remaining reachable.  The release
    check instead protects primary entry points, pane geometry, and dialog
    navigation from accidental clipping.
    """

    if isinstance(surface, VisualWorkbenchShell):
        primary = surface.primary_surface
        chrome: list[QWidget] = [
            surface.menuBar(),
            surface.toolbar,
            surface.toolbar.active_tool_chip,
            surface.toolbar.active_tool_chip.icon_label,
            surface.toolbar.active_tool_chip.name_label,
            surface.toolbar.active_tool_chip.shortcut_label,
            surface.workspace_host,
            primary,
            surface.statusBar(),
        ]
        if not surface.navigator.isHidden():
            chrome.append(surface.navigator)
        return (*chrome, *_critical_primary_widgets(primary))
    return _critical_primary_widgets(surface)


def _critical_primary_widgets(surface: QWidget) -> tuple[QWidget, ...]:
    if isinstance(surface, StartCenter):
        return (
            surface.title_label,
            surface.open_folder_button,
            surface.open_dicomdir_button,
            surface.open_image_button,
            surface.open_multiple_button,
        )
    if isinstance(surface, MultiViewerGrid):
        return tuple(surface.get_all_view_frames().values())
    if isinstance(surface, MprWorkspace):
        return (
            surface._status,
            surface._back_button,
            surface._orientation_cube,
            *surface._plane_panels.values(),
        )
    if isinstance(surface, SettingsDialog):
        return (
            surface.search_edit,
            surface.nav_list,
            surface.stacked_widget,
            surface.button_box,
        )
    return (surface,)


__all__ = [
    "RealMedImagerSurfaceProvider",
    "VisualWorkbenchShell",
    "critical_widgets_for_surface",
]
