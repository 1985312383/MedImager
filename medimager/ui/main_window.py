"""
主窗口模块

集成多序列管理器、多视图网格和序列面板的主窗口实现。
支持多序列加载、多视图布局和序列绑定管理。
"""

import os
import uuid
import copy
import json
import hashlib
import tempfile
import time
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set
from concurrent.futures import CancelledError

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QStatusBar, QFileDialog, QMessageBox, QDialog, QToolBar,
    QPushButton, QProgressBar, QToolButton,
    QAbstractItemView, QListView, QTreeView, QLineEdit, QTextEdit,
    QPlainTextEdit, QDockWidget, QInputDialog, QStackedWidget,
)
from PySide6.QtCore import Qt, QDir, QEvent, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from PySide6.QtWidgets import QApplication # Added for QApplication.processEvents()

from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.hanging_protocols import (
    HangingProtocolId,
    build_hanging_plan,
)
from medimager.core.study_model import classify_orientation
from medimager.core.series_view_binding import SeriesViewBindingManager, BindingStrategy
from medimager.core.image_data_model import ImageDataModel
from medimager.core.annotation_persistence import (
    import_annotations,
    export_annotations,
    save_annotations,
    AnnotationSeriesMismatchError,
    InvalidAnnotationError,
    has_unsaved_annotations,
)
from medimager.core.dicom_parser import DicomParser
from medimager.app_info import APP_NAME, get_about_html
from medimager.ui.multi_viewer_grid import MultiViewerGrid
from medimager.ui.mpr_workspace import MprWorkspace
from medimager.core.volume_geometry import GeometryStatus, VolumeBuilder
from medimager.core.view_presentation_state import (
    InterpolationMode,
    prefetch_display_slices,
)
from medimager.ui.qt_image_utils import qimage_from_display_data
from medimager.ui.panels.series_panel import SeriesPanel
from medimager.ui.panels.dicom_tag_panel import DicomTagPanel
from medimager.ui.dialogs.custom_wl_dialog import CustomWLDialog
from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.ui.shortcut_registry import ShortcutRegistry
from medimager.utils.logger import get_logger
from medimager.utils.settings import get_settings_manager, get_performance_manager
from medimager.utils.theme_manager import ThemeManager
from medimager.ui.tools.default_tool import DefaultTool
from medimager.ui.tools.roi_tool import EllipseROITool, RectangleROITool, CircleROITool
from medimager.ui.tools.measurement_tool import MeasurementTool
from medimager.ui.tools.angle_tool import AngleTool
from medimager.ui.main_toolbar import create_main_toolbar
from medimager.utils.i18n import t

logger = get_logger(__name__)


# Drafts from the same process are not crash-recovery candidates.  Marking
# every draft with a process-session id keeps a second MainWindow (tests,
# previews, or an in-process restart) from importing another live window's
# unsaved work, while a later application process can still recover it.
_ANNOTATION_DRAFT_SESSION_ID = uuid.uuid4().hex


class _DockAwareDicomTagPanel(DicomTagPanel):
    """Preserve the old panel.show()/setVisible(True) public behavior."""

    dock_visibility_requested = Signal()

    def show(self) -> None:
        super().show()
        self.dock_visibility_requested.emit()

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        if visible:
            self.dock_visibility_requested.emit()


class _SeriesLoadResult:
    """序列加载结果容器"""
    __slots__ = (
        'series_id', 'image_model', 'success', 'error', 'error_key',
        'error_args', 'metadata',
    )

    def __init__(self, series_id: str):
        self.series_id = series_id
        self.image_model: Optional[ImageDataModel] = None
        self.success = False
        self.error = ''
        self.error_key = ''
        self.error_args: Dict = {}
        self.metadata: Dict = {}


class _FolderScanResult:
    """后台文件夹扫描结果；仅包含可安全跨线程传递的 Python 数据。"""
    __slots__ = ('folder_path', 'series', 'candidate_count', 'skipped_count', 'error')

    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.series: List[Dict] = []
        self.candidate_count = 0
        self.skipped_count = 0
        self.error = ''


def _scan_dicom_folder_task(
    folder_path: str,
    recursive: bool,
    include_extensionless: bool,
    strict_metadata: bool,
) -> _FolderScanResult:
    """在工作线程扫描、分组并预读元数据，避免阻塞 GUI。"""
    result = _FolderScanResult(folder_path)
    try:
        folder = Path(folder_path)
        if not folder.is_dir():
            raise ValueError(f"目录不存在: {folder_path}")
        suffixes = {'.dcm', '.dicom', '.ima'}
        if include_extensionless:
            suffixes.add('')
        candidates = folder.rglob('*') if recursive else folder.glob('*')
        files = [
            str(path) for path in candidates
            if path.is_file() and path.suffix.lower() in suffixes
        ]
        result.candidate_count = len(files)
        if not files:
            return result

        parser = DicomParser()
        groups = parser._group_files_by_series(files)
        import pydicom

        required_tags = (
            'SeriesInstanceUID', 'StudyInstanceUID', 'Modality',
            'Rows', 'Columns', 'PhotometricInterpretation',
        )
        for _group_key, series_files in groups.items():
            if not series_files:
                continue
            try:
                first = pydicom.dcmread(series_files[0], stop_before_pixels=True, force=True)
                missing = [tag for tag in required_tags if not getattr(first, tag, None)]
                if strict_metadata and missing:
                    result.skipped_count += 1
                    logger.warning(
                        "[_scan_dicom_folder_task] 严格模式跳过缺少 %s 的序列: %s",
                        missing, series_files[0],
                    )
                    continue
                if len(series_files) == 1:
                    try:
                        slice_count = max(1, int(getattr(first, 'NumberOfFrames', 1) or 1))
                    except (TypeError, ValueError):
                        slice_count = 1
                else:
                    slice_count = len(series_files)
                result.series.append({
                    'patient_name': str(getattr(first, 'PatientName', 'Unknown Patient')),
                    'patient_id': str(getattr(first, 'PatientID', '') or ''),
                    'study_description': str(getattr(first, 'StudyDescription', '') or ''),
                    'series_description': str(getattr(first, 'SeriesDescription', '') or ''),
                    'modality': str(getattr(first, 'Modality', '') or ''),
                    'acquisition_date': str(getattr(first, 'AcquisitionDate', '') or ''),
                    'acquisition_time': str(getattr(first, 'AcquisitionTime', '') or ''),
                    'study_date': str(getattr(first, 'StudyDate', '') or ''),
                    'study_time': str(getattr(first, 'StudyTime', '') or ''),
                    'protocol_name': str(getattr(first, 'ProtocolName', '') or ''),
                    'body_part_examined': str(getattr(first, 'BodyPartExamined', '') or ''),
                    'slice_count': slice_count,
                    'series_number': str(getattr(first, 'SeriesNumber', 0)),
                    'study_instance_uid': str(getattr(first, 'StudyInstanceUID', '') or ''),
                    'series_instance_uid': str(getattr(first, 'SeriesInstanceUID', '') or ''),
                    'frame_of_reference_uid': str(getattr(first, 'FrameOfReferenceUID', '') or ''),
                    'orientation': classify_orientation(
                        getattr(first, 'ImageOrientationPatient', None)
                    ).value,
                    'file_paths': list(series_files),
                })
            except Exception as error:
                result.skipped_count += 1
                logger.warning("[_scan_dicom_folder_task] 预读序列失败: %s", error)
    except Exception as error:
        result.error = str(error)
        logger.error("[_scan_dicom_folder_task] 文件夹扫描失败: %s", error, exc_info=True)
    return result


def _load_series_task(file_paths: List[str], series_id: str) -> _SeriesLoadResult:
    """在线程池中执行的序列加载任务（纯函数，不涉及Qt信号）"""
    result = _SeriesLoadResult(series_id)
    try:
        image_model = ImageDataModel()
        success = image_model.load_dicom_series(file_paths)
        if success:
            # QObject 必须在其所属线程内迁移。加载结束后、交给 GUI 前迁回主线程，
            # 避免后续信号与销毁发生在线程池线程。
            app = QApplication.instance()
            if app is not None and image_model.thread() is not app.thread():
                if image_model.moveToThread(app.thread()) is False:
                    result.error_key = 'mainwindow.model_thread_transfer_failed'
                    return result
            result.image_model = image_model
            result.success = True
            logger.info(f"[_load_series_task] 序列加载成功: {series_id}")
        else:
            result.error_key = 'mainwindow.dicom_decode_failed'
            result.error = str(getattr(getattr(image_model, 'parser', None), 'last_error', '') or '')
            logger.error(f"[_load_series_task] 序列加载失败: {series_id}")
    except Exception as e:
        result.error = str(e)
        result.error_key = 'mainwindow.background_load_failed'
        logger.error(f"[_load_series_task] 序列加载异常: {e}", exc_info=True)
    return result


def _load_single_image_task(
    file_path: str,
    series_id: str,
    strict_metadata: bool = False,
) -> _SeriesLoadResult:
    """在工作线程读取单个 DICOM、NumPy 或常规图像文件。"""
    result = _SeriesLoadResult(series_id)
    image_model = ImageDataModel()
    path = Path(file_path)
    suffix = path.suffix.lower()
    is_dicom = suffix in {'.dcm', '.dicom', '.ima'}
    prefetched_dataset = None
    if not is_dicom and suffix not in {'.npy', '.png', '.jpg', '.jpeg', '.bmp'}:
        try:
            import pydicom

            prefetched_dataset = pydicom.dcmread(
                file_path,
                stop_before_pixels=True,
                force=True,
                specific_tags=[
                    'SOPClassUID', 'Rows', 'Columns', 'Modality',
                    'SeriesInstanceUID', 'StudyInstanceUID',
                    'PhotometricInterpretation',
                ],
            )
            is_dicom = bool(
                getattr(prefetched_dataset, 'Rows', None)
                and getattr(prefetched_dataset, 'Columns', None)
                and (
                    getattr(prefetched_dataset, 'SOPClassUID', None)
                    or getattr(prefetched_dataset, 'Modality', None)
                )
            )
        except Exception:
            prefetched_dataset = None
    try:
        dataset = prefetched_dataset
        if is_dicom:
            if strict_metadata:
                import pydicom

                dataset = dataset or pydicom.dcmread(
                    file_path, stop_before_pixels=True, force=True
                )
                required_tags = (
                    'SeriesInstanceUID', 'StudyInstanceUID', 'Modality',
                    'Rows', 'Columns', 'PhotometricInterpretation',
                )
                missing = [tag for tag in required_tags if not getattr(dataset, tag, None)]
                if missing:
                    result.error_key = 'mainwindow.strict_metadata_missing_tags'
                    result.error_args = {'tags': ', '.join(missing)}
                    return result
            success = image_model.load_dicom_series([file_path])
            if success:
                dataset = image_model.get_dicom_file(0) or dataset
        elif suffix == '.npy':
            data = np.load(file_path, allow_pickle=False)
            success = image_model.load_single_image(data)
        else:
            from PIL import Image

            with Image.open(file_path) as image:
                if image.mode not in ('L', 'I', 'F', 'RGB', 'RGBA'):
                    image = image.convert('RGB')
                data = np.array(image)
            success = image_model.load_single_image(data)

        if not success:
            result.error_key = (
                'mainwindow.dicom_decode_failed'
                if is_dicom else 'mainwindow.image_decode_failed'
            )
            result.error = str(getattr(getattr(image_model, 'parser', None), 'last_error', '') or '')
            return result

        app = QApplication.instance()
        if app is not None and image_model.thread() is not app.thread():
            if image_model.moveToThread(app.thread()) is False:
                result.error_key = 'mainwindow.model_thread_transfer_failed'
                return result

        if dataset is not None:
            result.metadata = {
                'patient_name': str(getattr(dataset, 'PatientName', '') or ''),
                'patient_id': str(getattr(dataset, 'PatientID', '') or ''),
                'study_description': str(getattr(dataset, 'StudyDescription', '') or ''),
                'series_description': str(getattr(dataset, 'SeriesDescription', '') or path.name),
                'modality': str(getattr(dataset, 'Modality', '') or 'DICOM'),
                'acquisition_date': str(getattr(dataset, 'AcquisitionDate', '') or ''),
                'acquisition_time': str(getattr(dataset, 'AcquisitionTime', '') or ''),
                'study_date': str(getattr(dataset, 'StudyDate', '') or ''),
                'study_time': str(getattr(dataset, 'StudyTime', '') or ''),
                'protocol_name': str(getattr(dataset, 'ProtocolName', '') or ''),
                'body_part_examined': str(getattr(dataset, 'BodyPartExamined', '') or ''),
                'series_number': str(getattr(dataset, 'SeriesNumber', '') or ''),
                'study_instance_uid': str(getattr(dataset, 'StudyInstanceUID', '') or ''),
                'series_instance_uid': str(getattr(dataset, 'SeriesInstanceUID', '') or ''),
                'frame_of_reference_uid': str(getattr(dataset, 'FrameOfReferenceUID', '') or ''),
                'orientation': classify_orientation(
                    getattr(dataset, 'ImageOrientationPatient', None)
                ).value,
                'slice_count': image_model.get_slice_count(),
            }
        else:
            result.metadata = {'slice_count': image_model.get_slice_count()}
        result.image_model = image_model
        result.success = True
    except Exception as error:
        result.error = str(error)
        result.error_key = 'mainwindow.background_load_failed'
        logger.error("[_load_single_image_task] 单文件加载异常: %s", error, exc_info=True)
    return result


class MainWindow(QMainWindow):
    """主窗口

    支持多序列管理、多视图布局和高级绑定功能的新主窗口。
    """

    # 线程安全信号：从工作线程通知主线程序列加载完成
    _series_load_done = Signal(str, object)  # (series_id, future)
    _folder_scan_done = Signal(str, object)  # (folder_path, future)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化主窗口"""
        super().__init__(parent)
        logger.debug("[MainWindow.__init__] 开始初始化主窗口")

        # 连接线程安全的序列加载完成信号
        self._series_load_done.connect(self._on_series_loading_finished)
        self._folder_scan_done.connect(self._on_folder_scan_finished)

        # 布局切换守卫标志（必须在信号连接之前初始化）
        self._setting_layout = False

        # 使用全局单例设置管理器和主题管理器
        self.settings_manager = get_settings_manager()
        self.theme_manager = ThemeManager(self.settings_manager, self)

        # UI 创建和首次状态刷新会访问这些字段，必须先于工具栏初始化。
        self._loading_futures: Dict[str, object] = {}
        self._folder_scan_futures: Dict[str, object] = {}
        self._loading_errors: List[str] = []
        self._load_requests: Dict[str, Dict] = {}
        self._failed_load_requests: Dict[str, Dict] = {}
        self._failed_folder_requests: Dict[str, Dict] = {}
        self._last_loading_errors: List[str] = []
        self._cancelled_load_ids: Set[str] = set()
        self._cancelled_folder_scans: Set[str] = set()
        self._load_batch_counts = {
            'submitted': 0, 'succeeded': 0, 'failed': 0, 'cancelled': 0
        }
        self._closing = False
        self._cine_timer = QTimer(self)
        self._cine_timer.timeout.connect(self._cine_advance)
        self._cine_playing = False
        self._cine_fps = self._int_setting('cine.default_fps', 10, 1, 60)
        self._cine_configured_fps = self._cine_fps
        self._cine_source_view_id: Optional[str] = None
        self._cine_source_series_id: Optional[str] = None
        self._cine_source_model: Optional[ImageDataModel] = None
        self._cine_metadata_timing = False

        # 初始化核心组件
        self._init_core_components()

        # 每个序列独立维护标注快照历史；只记录内容变化，不记录选择状态。
        self._annotation_histories: Dict[str, Dict] = {}
        self._annotation_sidecar_paths: Dict[str, Path] = {}
        self._annotation_draft_timers: Dict[str, QTimer] = {}
        self._default_presentation_by_series: Dict[
            str, Tuple[float, float, bool, Optional[int]]
        ] = {}
        self._dicom_tag_update_timer = QTimer(self)
        self._dicom_tag_update_timer.setSingleShot(True)
        self._dicom_tag_update_timer.timeout.connect(
            self._flush_pending_dicom_tags
        )
        self._image_required_actions: List[QAction] = []
        self._image_required_widgets: List[QWidget] = []
        self._mpr_active = False
        self._mpr_series_id: Optional[str] = None
        self._workspace_state_timer = QTimer(self)
        self._workspace_state_timer.setSingleShot(True)
        self._workspace_state_timer.timeout.connect(self._save_study_workspace_state)
        self._restored_study_keys: Set[str] = set()
        self._restoring_workspace = False
        self._prefetch_pending: Set[str] = set()

        # 初始化UI
        self._init_ui()
        self.shortcut_registry = ShortcutRegistry(self)
        self._init_shortcuts()
        
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

        logger.info("[MainWindow.__init__] 主窗口初始化完成")
    
    def _ensure_initial_layout(self) -> None:
        """确保初始布局正确设置"""
        logger.debug("[MainWindow._ensure_initial_layout] 确保初始布局设置")
        
        rows, cols = self._default_layout_from_settings()
        self.series_manager.set_layout(rows, cols)
        self.multi_viewer_grid.set_layout(rows, cols)
        
        logger.debug("[MainWindow._ensure_initial_layout] 初始布局设置完成")

    def _default_layout_from_settings(self) -> Tuple[int, int]:
        value = self.settings_manager.get_setting("multiview.default_layout", "1x1")
        mapping = {
            "1x1": (1, 1),
            "1x2": (1, 2),
            "2x1": (2, 1),
            "2x2": (2, 2),
        }
        return mapping.get(str(value), (1, 1))

    def _sync_mode_from_setting(self):
        from medimager.core.sync_manager import SyncMode

        value = self.settings_manager.get_setting("multiview.default_sync_mode", "basic")
        mapping = {
            "none": SyncMode.NONE,
            "basic": SyncMode.BASIC,
            "advanced": SyncMode.ADVANCED,
            "full": SyncMode.FULL,
        }
        return mapping.get(str(value), SyncMode.BASIC)

    def _sync_group_from_setting(self):
        from medimager.core.sync_manager import SyncGroup

        value = str(self.settings_manager.get_setting("multiview.sync_group", "same_study"))
        mapping = {
            "same_study": SyncGroup.SAME_STUDY,
            "same_patient": SyncGroup.SAME_PATIENT,
            "same_modality": SyncGroup.SAME_MODALITY,
            "all_views": SyncGroup.ALL_VIEWS,
        }
        return mapping.get(value, SyncGroup.SAME_STUDY)

    def _int_setting(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.settings_manager.get_setting(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _bool_setting(self, key: str, default: bool) -> bool:
        value = self.settings_manager.get_setting(key, default)
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    
    def _init_core_components(self) -> None:
        """初始化核心组件"""
        logger.debug("[MainWindow._init_core_components] 初始化核心组件")
        
        # 多序列管理器
        self.series_manager = MultiSeriesManager(self)
        
        # 同步管理器
        from medimager.core.sync_manager import SyncManager
        self.sync_manager = SyncManager(self.series_manager, self)
        
        # 按设置启用默认同步模式
        self.sync_manager.set_sync_mode(self._sync_mode_from_setting())
        self.sync_manager.set_sync_group(self._sync_group_from_setting())
        
        # 序列视图绑定管理器
        self.binding_manager = SeriesViewBindingManager(self.series_manager, self)
        self.binding_manager.set_target_view_selector(
            self._select_binding_target_view
        )
        
        # 设置默认绑定策略
        self.binding_manager.set_binding_strategy(BindingStrategy.AUTO_ASSIGN)
        
        # 初始化默认工具
        self._init_default_tool()
        
        logger.debug("[MainWindow._init_core_components] 核心组件初始化完成")
    
    def _init_ui(self) -> None:
        """初始化用户界面"""
        logger.debug("[MainWindow._init_ui] 初始化主窗口UI")
        
        self.setGeometry(100, 100, 1800, 1000)
        self.setWindowTitle(
            t("mainwindow.medimager_pro_multi_sequence_dicom_viewer_and_analysis")
            + " [*]"
        )
        
        # 中央组件只承载影像网格；侧栏使用原生 Dock，可调整大小、浮动，
        # 并由 QMainWindow.saveState/restoreState 自动持久化。
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        # 左侧序列面板
        self.series_panel = SeriesPanel(
            self.series_manager,
            self.binding_manager,
            self
        )
        self.series_panel.setMinimumWidth(240)
        self.series_panel.set_series_removal_handler(self._request_remove_series)
        self.series_dock = QDockWidget(t("mainwindow.show_hide_sequence_panel"), self)
        self.series_dock.setObjectName("SeriesDock")
        self.series_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.series_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.series_dock.setWidget(self.series_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.series_dock)

        # 中央工作区在常规 2-D 网格与三平面 MPR 之间切换。
        self.workspace_stack = QStackedWidget(self)
        self.multi_viewer_grid = MultiViewerGrid(self.series_manager, self)
        self.mpr_workspace = MprWorkspace(self)
        self.mpr_workspace.request_return_to_2d.connect(self._leave_mpr_workspace)
        self.workspace_stack.addWidget(self.multi_viewer_grid)
        self.workspace_stack.addWidget(self.mpr_workspace)
        self.workspace_stack.setCurrentWidget(self.multi_viewer_grid)
        main_layout.addWidget(self.workspace_stack, 1)

        # 右侧信息面板
        self.dicom_tag_panel = _DockAwareDicomTagPanel()
        self.dicom_tag_panel.setMinimumWidth(220)
        self.dicom_tag_panel.installEventFilter(self)
        self.info_dock = QDockWidget(t("mainwindow.show_hide_information_panel"), self)
        self.info_dock.setObjectName("DicomInfoDock")
        self.info_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.info_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.info_dock.setWidget(self.dicom_tag_panel)
        self.dicom_tag_panel.dock_visibility_requested.connect(
            self.info_dock.show
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.info_dock)
        # Keep the child explicitly hidden whenever its dock is closed.  This
        # also lets legacy callers that invoke ``dicom_tag_panel.show()``
        # request the information dock through eventFilter().
        self.dicom_tag_panel.hide()
        self.info_dock.hide()
        
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
        self.series_manager.series_removed.connect(self._on_series_removed)
        self.series_manager.binding_changed.connect(self._on_binding_changed)
        self.series_manager.layout_changed.connect(self._on_layout_changed)
        
        # 绑定管理器信号
        self.binding_manager.auto_assignment_completed.connect(self._on_auto_assignment_completed)
        self.binding_manager.binding_failed.connect(self._on_binding_failed)
        
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
        self.series_dock.visibilityChanged.connect(
            self._on_series_dock_visibility_changed
        )
        self.info_dock.visibilityChanged.connect(
            self._on_info_dock_visibility_changed
        )
        
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
        file_menu = menubar.addMenu(t("mainwindow.file_f"))
        
        # 打开多个DICOM文件夹
        open_multiple_folders_action = QAction(t("mainwindow.open_multiple_dicom_folders_m"), self)
        open_multiple_folders_action.setShortcut("Ctrl+Shift+D")
        open_multiple_folders_action.setStatusTip(t("mainwindow.open_multiple_folders_containing_dicom_sequences_at_the"))
        open_multiple_folders_action.triggered.connect(self._open_multiple_dicom_folders)
        file_menu.addAction(open_multiple_folders_action)
        
        # 打开DICOM文件夹
        open_folder_action = QAction(t("mainwindow.open_dicom_folder_d"), self)
        open_folder_action.setShortcut("Ctrl+D")
        open_folder_action.setStatusTip(t("mainwindow.open_the_folder_containing_the_dicom_sequence"))
        open_folder_action.triggered.connect(self._open_dicom_folder)
        file_menu.addAction(open_folder_action)
        
        # 打开图像文件
        open_image_action = QAction(t("mainwindow.open_image_file_i"), self)
        open_image_action.setShortcut(QKeySequence.Open)
        open_image_action.setStatusTip(t("mainwindow.open_a_single_image_file"))
        open_image_action.triggered.connect(self._open_image_file)
        file_menu.addAction(open_image_action)
        
        file_menu.addSeparator()
        
        # 导入测试数据
        test_menu = file_menu.addMenu(t("mainwindow.test_data"))
        
        load_test_series_action = QAction(t("mainwindow.load_test_sequence"), self)
        load_test_series_action.triggered.connect(self._load_test_series)
        test_menu.addAction(load_test_series_action)

        file_menu.addSeparator()

        # 导出当前视图
        self.export_view_action = QAction(t("mainwindow.export_current_view_e"), self)
        self.export_view_action.setShortcut("Ctrl+E")
        self.export_view_action.setStatusTip(t("mainwindow.export_current_view_as_image"))
        self.export_view_action.triggered.connect(self._export_current_view)
        file_menu.addAction(self.export_view_action)

        self.export_slice_action = QAction(t("mainwindow.export_current_slice_image_s"), self)
        self.export_slice_action.setShortcut("Ctrl+Shift+E")
        self.export_slice_action.setStatusTip(t("mainwindow.export_current_slice_image_without_chrome"))
        self.export_slice_action.triggered.connect(self._export_current_slice_image)
        file_menu.addAction(self.export_slice_action)

        file_menu.addSeparator()

        self.import_annotations_action = QAction(t("mainwindow.import_annotations_a"), self)
        self.import_annotations_action.setStatusTip(t("mainwindow.import_roi_measurements_from_json"))
        self.import_annotations_action.triggered.connect(self._import_annotations)
        file_menu.addAction(self.import_annotations_action)

        self.save_annotations_action = QAction(t("mainwindow.save_annotations"), self)
        self.save_annotations_action.setShortcut(QKeySequence.Save)
        self.save_annotations_action.triggered.connect(self._save_active_annotations)
        file_menu.addAction(self.save_annotations_action)

        self.save_annotations_as_action = QAction(t("mainwindow.save_annotations_as"), self)
        self.save_annotations_as_action.setShortcut(QKeySequence.SaveAs)
        self.save_annotations_as_action.triggered.connect(self._save_active_annotations_as)
        file_menu.addAction(self.save_annotations_as_action)

        self.save_all_annotations_action = QAction(t("mainwindow.save_all_annotations"), self)
        self.save_all_annotations_action.setShortcut("Ctrl+Alt+S")
        self.save_all_annotations_action.triggered.connect(self._save_all_annotations)
        file_menu.addAction(self.save_all_annotations_action)

        self.export_annotations_action = QAction(t("mainwindow.export_annotations_n"), self)
        self.export_annotations_action.setStatusTip(t("mainwindow.export_roi_measurements_to_json"))
        self.export_annotations_action.triggered.connect(self._export_annotations)
        file_menu.addAction(self.export_annotations_action)

        # 复制视图到剪贴板
        self.copy_view_action = QAction(t("mainwindow.copy_view_to_clipboard_c"), self)
        self.copy_view_action.setShortcut("Ctrl+Shift+C")
        self.copy_view_action.setStatusTip(t("mainwindow.copy_current_view_to_clipboard"))
        self.copy_view_action.triggered.connect(self._copy_view_to_clipboard)
        file_menu.addAction(self.copy_view_action)

        file_menu.addSeparator()

        # 退出
        exit_action = QAction(t("mainwindow.exit_x"), self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setStatusTip(t("mainwindow.exit_the_application"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单：标注内容按活动序列分别撤销/重做。
        edit_menu = menubar.addMenu(t("mainwindow.edit_e"))
        self.undo_annotation_action = QAction(t("mainwindow.undo_annotation_change"), self)
        self.undo_annotation_action.setShortcut(QKeySequence.Undo)
        self.undo_annotation_action.triggered.connect(self._undo_annotation_change)
        self.undo_annotation_action.setEnabled(False)
        edit_menu.addAction(self.undo_annotation_action)

        self.redo_annotation_action = QAction(t("mainwindow.redo_annotation_change"), self)
        self.redo_annotation_action.setShortcut(QKeySequence.Redo)
        self.redo_annotation_action.triggered.connect(self._redo_annotation_change)
        self.redo_annotation_action.setEnabled(False)
        edit_menu.addAction(self.redo_annotation_action)

        self._image_required_actions.extend([
            self.export_view_action,
            self.export_slice_action,
            self.import_annotations_action,
            self.save_annotations_action,
            self.save_annotations_as_action,
            self.export_annotations_action,
            self.copy_view_action,
        ])
        
        # 查看菜单
        view_menu = menubar.addMenu(t("mainwindow.view"))
        
        # 显示/隐藏面板
        self.toggle_series_panel_action = QAction(t("mainwindow.show_hide_sequence_panel"), self)
        self.toggle_series_panel_action.setShortcut("F1")
        self.toggle_series_panel_action.setCheckable(True)
        self.toggle_series_panel_action.setChecked(True)
        self.toggle_series_panel_action.toggled.connect(self._toggle_series_panel)
        view_menu.addAction(self.toggle_series_panel_action)
        
        self.toggle_info_panel_action = QAction(t("mainwindow.show_hide_information_panel"), self)
        self.toggle_info_panel_action.setShortcut("F2")
        self.toggle_info_panel_action.setCheckable(True)
        self.toggle_info_panel_action.setChecked(False)
        self.toggle_info_panel_action.toggled.connect(self._toggle_info_panel)
        view_menu.addAction(self.toggle_info_panel_action)
        
        # 序列菜单
        series_menu = menubar.addMenu(t("mainwindow.sequence_s"))
        
        # 绑定策略
        binding_strategy_menu = series_menu.addMenu(t("mainwindow.binding_strategy"))
        
        self._binding_strategy_group = QActionGroup(self)
        strategy_actions = [
            (t("mainwindow.automatic_assignment"), BindingStrategy.AUTO_ASSIGN),
            (t("mainwindow.keep_existing"), BindingStrategy.PRESERVE_EXISTING),
            (t("mainwindow.replace_the_oldest"), BindingStrategy.REPLACE_OLDEST),
            (t("mainwindow.ask_the_user"), BindingStrategy.ASK_USER)
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
        self.auto_assign_action = QAction(t("mainwindow.automatically_assign_all_sequences"), self)
        self.auto_assign_action.triggered.connect(self._auto_assign_all_series)
        series_menu.addAction(self.auto_assign_action)

        hanging_menu = series_menu.addMenu(t("mainwindow.hanging_protocols"))
        self._hanging_actions = []
        for protocol, title_key in (
            (HangingProtocolId.STUDY_OVERVIEW, "mainwindow.hanging_study_overview"),
            (HangingProtocolId.CT_COMPARISON, "mainwindow.hanging_ct_comparison"),
            (HangingProtocolId.MR_NEURO, "mainwindow.hanging_mr_neuro"),
            (HangingProtocolId.CURRENT_MPR, "mainwindow.hanging_current_mpr"),
        ):
            action = QAction(t(title_key), self)
            action.triggered.connect(
                lambda checked=False, value=protocol: self._apply_hanging_protocol(value)
            )
            hanging_menu.addAction(action)
            self._hanging_actions.append(action)
            self._image_required_actions.append(action)

        # 清除所有绑定
        self.clear_bindings_action = QAction(t("mainwindow.clear_all_bindings"), self)
        self.clear_bindings_action.triggered.connect(self._clear_all_bindings)
        series_menu.addAction(self.clear_bindings_action)
        
        # 窗位菜单
        wl_menu = menubar.addMenu(t("mainwindow.window_position_w"))
        
        # 预设窗位
        presets: List[Tuple[str, Tuple[int, int]]] = [
            (t("mainwindow.auto"), (-1, -1)),
            (t("mainwindow.abdomen"), (400, 50)),
            (t("mainwindow.brain_window"), (80, 40)),
            (t("mainwindow.bone_window"), (2000, 600)),
            (t("mainwindow.lung_window"), (1500, -600)),
            (t("mainwindow.mediastinum"), (350, 50)),
        ]
        
        for name, (width, level) in presets:
            action = QAction(name, self)
            action.setStatusTip(t("mainwindow.set_window_level_for_value").replace("%1", name).replace("%2", str(width)).replace("%3", str(level)))
            action.triggered.connect(
                lambda checked=False, width=width, level=level: (
                    self._set_window_level_preset(width, level)
                )
            )
            wl_menu.addAction(action)
        
        wl_menu.addSeparator()
        
        custom_wl_action = QAction(t("mainwindow.custom"), self)
        custom_wl_action.setStatusTip(t("mainwindow.manually_set_the_window_width_and_window_position"))
        custom_wl_action.triggered.connect(self._open_custom_wl_dialog)
        wl_menu.addAction(custom_wl_action)
        

        
        # 工具菜单
        tools_menu = menubar.addMenu(t("mainwindow.tools_t"))
        
        # 设置
        settings_action = QAction(t("mainwindow.settings_s"), self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.setStatusTip(t("mainwindow.open_the_settings_dialog_box"))
        settings_action.triggered.connect(self._open_settings_dialog)
        tools_menu.addAction(settings_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu(t("mainwindow.help_h"))
        
        about_action = QAction(t("mainwindow.about"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
        logger.debug("[MainWindow._init_menus] 主窗口菜单初始化完成")
    
    def _init_toolbars(self) -> None:
        """初始化工具栏"""
        logger.debug("[MainWindow._init_toolbars] 初始化主窗口工具栏")
        
        # 使用统一的主工具栏创建函数（包含所有工具和按钮）
        main_toolbar = create_main_toolbar(self)
        self.main_toolbar = main_toolbar
        self.addToolBar(main_toolbar)
        self._connect_viewer_toolbar(main_toolbar)
        
        # 获取同步按钮的引用（工具栏创建时已添加）
        for widget in main_toolbar.children():
            if hasattr(widget, 'set_sync_states'):
                self._sync_button = widget
                break
        
        logger.debug("[MainWindow._init_toolbars] 主窗口工具栏初始化完成")

    def _connect_viewer_toolbar(self, toolbar) -> None:
        """Connect the optional richer toolbar API without breaking older bars."""
        connections = (
            ('interaction_mode_requested', self._on_viewer_interaction_mode_requested),
            ('viewer_command_requested', self._on_viewer_command_requested),
            ('voi_option_requested', self._on_toolbar_voi_option_requested),
            ('voi_menu_about_to_show', self._refresh_toolbar_dicom_voi_options),
        )
        for signal_name, handler in connections:
            signal = getattr(toolbar, signal_name, None)
            connect = getattr(signal, 'connect', None)
            if callable(connect):
                connect(handler)

    def _on_viewer_interaction_mode_requested(self, mode: str) -> None:
        mode = str(mode)
        if mode not in {'default', 'pan', 'zoom', 'window_level'}:
            return
        if (
            self._current_tool == 'default'
            and getattr(self, '_default_interaction_mode', 'default') == mode
        ):
            return
        self._on_tool_selected('default', interaction_mode=mode)
        if getattr(self, '_mpr_active', False):
            self.mpr_workspace.set_interaction_mode(mode)

    def _on_viewer_command_requested(self, command: str) -> None:
        operations = {
            'fit': 'fit_to_window',
            'actual_size': 'actual_size',
            'reset_view': 'reset_view',
        }
        viewer = self._active_viewer()
        operation = getattr(viewer, operations.get(str(command), ''), None)
        if callable(operation):
            operation()

    def _refresh_toolbar_dicom_voi_options(self) -> None:
        toolbar = getattr(self, 'main_toolbar', None)
        setter = getattr(toolbar, 'set_dicom_voi_options', None)
        if not callable(setter):
            return
        model = self._get_active_image_model()
        viewer = self._active_viewer()
        getter = getattr(model, 'get_dicom_voi_options', None) if model else None
        if not callable(getter):
            setter([], active_index=None)
            return
        slice_index = self._active_view_slice_index()
        try:
            options = list(getter(slice_index) or [])
        except Exception:
            logger.exception('[MainWindow] 读取 DICOM VOI 选项失败')
            options = []
        active_index = None
        state = getattr(viewer, 'presentation_state', None)
        if state is not None:
            for index, option in enumerate(options):
                if not isinstance(option, dict):
                    continue
                if (
                    option.get('kind') == 'lut'
                    and state.use_dicom_voi_lut
                    and int(option.get('index', -1)) == state.voi_lut_index
                ):
                    active_index = index
                    break
                if option.get('kind') == 'window' and not state.use_dicom_voi_lut:
                    try:
                        if (
                            abs(float(option['width']) - state.window_width) < 1e-6
                            and abs(float(option['center']) - state.window_level) < 1e-6
                        ):
                            active_index = index
                            break
                    except (KeyError, TypeError, ValueError):
                        pass
        setter(options, active_index=active_index)

    def _on_toolbar_voi_option_requested(self, option) -> None:
        """Apply a validated DICOM VOI choice to the active pane only."""
        if not isinstance(option, dict):
            return
        model = self._get_active_image_model()
        viewer = self._active_viewer()
        getter = getattr(model, "get_dicom_voi_options", None) if model else None
        if viewer is None or not callable(getter):
            return
        try:
            slice_index = self._active_view_slice_index()
            candidates = list(getter(slice_index) or [])
            selected = next(
                (candidate for candidate in candidates if candidate == option),
                None,
            )
            if selected is None:
                return
            if selected.get("kind") == "window":
                setter = getattr(viewer, "set_view_window", None)
                if callable(setter):
                    setter(float(selected["width"]), float(selected["center"]))
            elif selected.get("kind") == "lut":
                setter = getattr(viewer, "set_view_voi_lut", None)
                if callable(setter):
                    setter(True, int(selected.get("index", 0)))
            else:
                return
            self._refresh_toolbar_dicom_voi_options()
        except Exception:
            logger.exception("[MainWindow] 激活 DICOM VOI 选项失败: %r", option)
    
    def _init_default_tool(self) -> None:
        """初始化默认工具"""
        logger.debug("[MainWindow._init_default_tool] 初始化默认工具")
        self._current_tool = 'default'
        self.current_tool = DefaultTool(None)  # 稍后会传播到各个视图
        logger.debug("[MainWindow._init_default_tool] 默认工具初始化完成")
    
    def _on_tool_selected(
        self, tool_name: str, *, interaction_mode: Optional[str] = None
    ) -> None:
        """处理工具选择事件"""
        logger.debug(f"[MainWindow._on_tool_selected] 工具选择: {tool_name}")
        
        # 保存当前工具状态
        self._current_tool = tool_name
        if tool_name == 'default':
            self._default_interaction_mode = interaction_mode or 'default'
        
        # 创建对应的工具实例
        self.current_tool = self._create_tool_instance(tool_name)
        if getattr(self, "_mpr_active", False):
            self.mpr_workspace.set_annotation_tool(tool_name)
        
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
        from medimager.ui.tools.measurement_tool import MeasurementTool
        from medimager.ui.tools.angle_tool import AngleTool

        tool_map = {
            'default': DefaultTool,
            'ellipse_roi': EllipseROITool,
            'rectangle_roi': RectangleROITool,
            'circle_roi': CircleROITool,
            'measurement': MeasurementTool,
            'angle': AngleTool,
        }
        
        tool_class = tool_map.get(tool_name, DefaultTool)
        if tool_class is DefaultTool:
            return tool_class(
                None, getattr(self, '_default_interaction_mode', 'default')
            )
        if tool_class in (MeasurementTool, AngleTool):
            return tool_class(None, creation_only=True)
        return tool_class(None)  # 临时创建，稍后会为每个viewer创建副本
    
    def _create_tool_copy(self, image_viewer) -> Optional:
        """为指定的ImageViewer创建工具副本"""
        try:
            if self.current_tool:
                tool_class = type(self.current_tool)
                if tool_class is DefaultTool:
                    return tool_class(
                        image_viewer,
                        getattr(self.current_tool, 'interaction_mode', 'default'),
                    )
                if tool_class in (MeasurementTool, AngleTool):
                    return tool_class(image_viewer, creation_only=True)
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
        self.series_count_label = QLabel(t("mainwindow.sequence_0"))
        self.status_bar.addWidget(self.series_count_label)
        
        # 视图信息标签
        self.view_info_label = QLabel(t("mainwindow.layout_1_1"))
        self.status_bar.addWidget(self.view_info_label)
        
        # 活动视图标签
        self.active_view_label = QLabel(t("mainwindow.event_view"))
        self.status_bar.addWidget(self.active_view_label)

        self.non_diagnostic_label = QLabel(
            t('mainwindow.non_diagnostic_notice')
        )
        self.non_diagnostic_label.setToolTip(
            t('mainwindow.non_diagnostic_notice_tooltip')
        )
        self.status_bar.addPermanentWidget(self.non_diagnostic_label)
        
        # 加载进度条
        self.loading_progress = QProgressBar()
        self.loading_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.loading_progress)

        self.loading_cancel_button = QPushButton(t('mainwindow.cancel_loading'))
        self.loading_cancel_button.clicked.connect(self._cancel_pending_loads)
        self.loading_cancel_button.hide()
        self.status_bar.addPermanentWidget(self.loading_cancel_button)

        self.loading_retry_button = QPushButton(t('mainwindow.retry_failed_loads'))
        self.loading_retry_button.clicked.connect(self._retry_failed_loads)
        self.loading_retry_button.hide()
        self.status_bar.addPermanentWidget(self.loading_retry_button)

        self.loading_details_button = QPushButton(t('mainwindow.loading_details'))
        self.loading_details_button.clicked.connect(self._show_loading_details)
        self.loading_details_button.hide()
        self.status_bar.addPermanentWidget(self.loading_details_button)

        self.empty_open_folder_button = QPushButton(
            t('mainwindow.open_dicom_folder_d')
        )
        self.empty_open_folder_button.clicked.connect(self._open_dicom_folder)
        self.status_bar.addPermanentWidget(self.empty_open_folder_button)
        
        # 准备状态
        self.status_bar.showMessage(t("mainwindow.ready"))
        
        logger.debug("[MainWindow._init_statusbar] 主窗口状态栏初始化完成")

    def _init_shortcuts(self) -> None:
        """Register focus-safe viewport shortcuts in one discoverable place."""
        registry = self.shortcut_registry
        registry.register('slice.previous', 'PgUp', t('shortcut.previous_slice'),
                          lambda: self._step_active_slice(-1))
        registry.register('slice.next', 'PgDown', t('shortcut.next_slice'),
                          lambda: self._step_active_slice(1))
        registry.register('slice.first', 'Home', t('shortcut.first_slice'),
                          lambda: self._set_active_slice_boundary(first=True))
        registry.register('slice.last', 'End', t('shortcut.last_slice'),
                          lambda: self._set_active_slice_boundary(first=False))
        registry.register('cine.toggle', 'Space', t('shortcut.cine_toggle'),
                          self._cine_toggle_play)
        registry.register('view.fit', 'F', t('shortcut.fit_to_window'),
                          self._fit_active_view)
        registry.register('view.actual_size', '1', t('shortcut.actual_size'),
                          self._actual_size_active_view)
        registry.register('interaction.cancel', 'Esc', t('shortcut.cancel_interaction'),
                          self._cancel_active_interaction)
        if hasattr(self, '_cine_play_btn'):
            registry.apply_tooltip(
                self._cine_play_btn, 'cine.toggle',
                t('mainwindow.cine_play_pause')
            )

    def _active_viewer(self):
        if getattr(self, '_mpr_active', False):
            workspace = getattr(self, 'mpr_workspace', None)
            return workspace.active_viewer if workspace is not None else None
        frame = self.multi_viewer_grid.get_active_view_frame()
        return getattr(frame, 'image_viewer', None) if frame else None

    def _active_view_slice_index(self) -> int:
        viewer = self._active_viewer()
        if viewer is not None:
            accessor = getattr(viewer, 'current_slice_index', None)
            if callable(accessor):
                try:
                    return int(accessor())
                except (TypeError, ValueError):
                    pass
            state = getattr(viewer, 'presentation_state', None)
            if state is not None and hasattr(state, 'slice_index'):
                return int(state.slice_index)
        model = self._get_active_image_model()
        return int(getattr(model, 'current_slice_index', 0) or 0)

    def _set_active_slice(self, index: int) -> None:
        viewer = self._active_viewer()
        model = self._get_active_image_model()
        if model is None:
            return
        index = max(0, min(model.get_slice_count() - 1, int(index)))
        setter = getattr(viewer, 'set_view_slice', None) if viewer else None
        if callable(setter):
            setter(index)
        else:
            model.set_current_slice(index)

    def _step_active_slice(self, delta: int) -> None:
        self._set_active_slice(self._active_view_slice_index() + delta)

    def _set_active_slice_boundary(self, *, first: bool) -> None:
        model = self._get_active_image_model()
        if model is not None:
            self._set_active_slice(0 if first else model.get_slice_count() - 1)

    def _fit_active_view(self) -> None:
        viewer = self._active_viewer()
        operation = getattr(viewer, 'fit_to_window', None)
        if callable(operation):
            operation()

    def _actual_size_active_view(self) -> None:
        viewer = self._active_viewer()
        operation = getattr(viewer, 'actual_size', None)
        if callable(operation):
            operation()

    def _cancel_active_interaction(self) -> None:
        viewer = self._active_viewer()
        tool = getattr(viewer, 'current_tool', None) if viewer else None
        cancel = getattr(tool, 'cancel_interaction', None)
        if callable(cancel):
            cancel()
    
    def _mpr_memory_budget_bytes(self) -> int:
        cache_mb = get_performance_manager().get_cache_size()
        return max(512, min(2048, cache_mb * 4)) * 1024 * 1024

    def _refresh_mpr_availability(self) -> None:
        action = getattr(self, 'mpr_action', None)
        if action is None:
            return
        if self._mpr_active:
            action.setEnabled(True)
            action.setChecked(True)
            action.setText(t('mpr.return_to_2d'))
            action.setToolTip(t('mpr.return_to_2d'))
            return
        model = self._get_active_image_model()
        result = (
            VolumeBuilder.inspect(model, memory_budget_bytes=self._mpr_memory_budget_bytes())
            if model is not None and model.has_image()
            else None
        )
        compatible = bool(result and result.status is GeometryStatus.COMPATIBLE)
        action.setEnabled(compatible)
        action.setChecked(False)
        action.setText(t('mpr.enter'))
        action.setToolTip(t('mpr.enter') if compatible else t(result.detail) if result else t('mpr.no_active_series'))

    def _toggle_mpr_workspace(self, checked: bool = False) -> None:
        if self._mpr_active:
            self._leave_mpr_workspace()
            return
        model = self._get_active_image_model()
        series_id = self._active_series_id()
        if model is None or series_id is None:
            self._refresh_mpr_availability()
            return
        inspection = VolumeBuilder.inspect(
            model, memory_budget_bytes=self._mpr_memory_budget_bytes()
        )
        if inspection.status is not GeometryStatus.COMPATIBLE:
            QMessageBox.warning(self, t('mpr.title'), t(inspection.detail))
            self._refresh_mpr_availability()
            return
        self._cine_stop()
        self._mpr_active = True
        self._mpr_series_id = series_id
        self.workspace_stack.setCurrentWidget(self.mpr_workspace)
        self.mpr_workspace.start_build(
            model, series_id, self._mpr_memory_budget_bytes()
        )
        self._refresh_mpr_availability()

    def _leave_mpr_workspace(self) -> None:
        if hasattr(self, 'mpr_workspace'):
            self.mpr_workspace.clear()
        self._mpr_active = False
        self._mpr_series_id = None
        if hasattr(self, 'workspace_stack'):
            self.workspace_stack.setCurrentWidget(self.multi_viewer_grid)
        self._refresh_mpr_availability()

    def _update_ui_state(self) -> None:
        """更新UI状态"""
        series_count = self.series_manager.get_series_count()
        layout = self.series_manager.get_current_layout()
        
        # 更新状态栏
        self.series_count_label.setText(t("mainwindow.sequence_value").replace("%1", str(series_count)))
        self.view_info_label.setText(t("mainwindow.layout_size").replace("%1", str(layout[0])).replace("%2", str(layout[1])))
        
        # 更新菜单和工具栏状态
        has_series = series_count > 0
        active_model = self._get_active_image_model()
        has_active_image = bool(active_model and active_model.has_image())
        has_cine_frames = bool(has_active_image and active_model.get_slice_count() > 1)
        for action in self._image_required_actions:
            action.setEnabled(has_active_image)
        for widget in self._image_required_widgets:
            widget.setEnabled(has_active_image)
        if hasattr(self, 'empty_open_folder_button'):
            self.empty_open_folder_button.setVisible(
                not has_series
                and not self._folder_scan_futures
                and not self._loading_futures
            )
        self._refresh_toolbar_dicom_voi_options()
        self._refresh_mpr_availability()
        if hasattr(self, '_cine_play_btn'):
            if not has_cine_frames and self._cine_playing:
                self._cine_stop()
            self._cine_play_btn.setEnabled(has_cine_frames)
        if hasattr(self, '_cine_fps_spin'):
            self._cine_fps_spin.setEnabled(has_cine_frames)
        if hasattr(self, 'auto_assign_action'):
            self.auto_assign_action.setEnabled(has_series)
        if hasattr(self, 'clear_bindings_action'):
            has_binding = any(
                bool(self.series_manager.get_view_binding(view_id).series_id)
                for view_id in self.series_manager.get_all_view_ids()
                if self.series_manager.get_view_binding(view_id)
            )
            self.clear_bindings_action.setEnabled(has_binding)
        self._update_annotation_history_actions()

    def _active_series_id(self) -> Optional[str]:
        view_id = self.series_manager.get_active_view_id()
        binding = self.series_manager.get_view_binding(view_id) if view_id else None
        return binding.series_id if binding and binding.series_id else None

    def _register_annotation_history(self, series_id: str) -> None:
        if series_id in self._annotation_histories:
            return
        model = self.series_manager.get_series_model(series_id)
        if not model:
            return
        self._recover_annotation_state(series_id, model)
        snapshot = export_annotations(model)
        history = {
            'model': model,
            'current': copy.deepcopy(snapshot),
            'saved': copy.deepcopy(snapshot) if not has_unsaved_annotations(model) else None,
            'undo': [],
            'redo': [],
            'restoring': False,
        }

        def callback(sid=series_id):
            self._on_annotation_content_changed(sid)

        history['callback'] = callback
        self._annotation_histories[series_id] = history
        model.annotation_changed.connect(callback)

    def _on_annotation_content_changed(self, series_id: str) -> None:
        history = self._annotation_histories.get(series_id)
        if not history or history['restoring']:
            return
        snapshot = export_annotations(history['model'])
        if snapshot == history['current']:
            return
        history['undo'].append(copy.deepcopy(history['current']))
        del history['undo'][:-100]
        history['current'] = copy.deepcopy(snapshot)
        history['redo'].clear()
        self._schedule_annotation_draft(series_id)
        self._update_annotation_history_actions()

    def _mark_annotation_history_saved(self, model: ImageDataModel) -> None:
        for history in self._annotation_histories.values():
            if history['model'] is model:
                snapshot = export_annotations(model)
                history['current'] = copy.deepcopy(snapshot)
                history['saved'] = copy.deepcopy(snapshot)
                series_id = next(
                    (
                        candidate_id
                        for candidate_id, candidate_history in self._annotation_histories.items()
                        if candidate_history is history
                    ),
                    None,
                )
                if series_id:
                    self._remove_annotation_draft(series_id)
                break
        self._update_annotation_history_actions()

    def _update_annotation_history_actions(self) -> None:
        if not hasattr(self, 'undo_annotation_action'):
            return
        history = self._annotation_histories.get(self._active_series_id() or '')
        self.undo_annotation_action.setEnabled(bool(history and history['undo']))
        self.redo_annotation_action.setEnabled(bool(history and history['redo']))
        any_dirty = any(
            has_unsaved_annotations(candidate['model'])
            for candidate in self._annotation_histories.values()
        )
        self.setWindowModified(any_dirty)
        if hasattr(self, 'save_annotations_action'):
            self.save_annotations_action.setEnabled(bool(history))
            self.save_annotations_as_action.setEnabled(bool(history))
            self.save_all_annotations_action.setEnabled(any_dirty)

    def _default_annotation_sidecar_path(self, series_id: str) -> Optional[Path]:
        info = self.series_manager.get_series_info(series_id)
        if info is None or not info.file_paths:
            return None
        first = Path(info.file_paths[0])
        if len(info.file_paths) == 1:
            return first.with_suffix(first.suffix + '.medimager.json')
        uid = str(info.series_instance_uid or series_id)
        safe_uid = ''.join(character for character in uid if character.isalnum())[-16:]
        return first.parent / f'.medimager-{safe_uid}.annotations.json'

    def _draft_path(self, series_id: str, model: ImageDataModel) -> Path:
        identity = str(model.get_metadata('SeriesInstanceUID', '') or series_id)
        digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        directory = self.settings_manager.get_config_directory() / 'annotation_drafts'
        return directory / f'{digest}.json'

    def _draft_recovery_enabled(self, series_id: str) -> bool:
        """Drafts require a source that the next process can reopen."""
        info = self.series_manager.get_series_info(series_id)
        return bool(info and info.file_paths)

    def _recover_annotation_state(self, series_id: str, model: ImageDataModel) -> None:
        sidecar = self._default_annotation_sidecar_path(series_id)
        if sidecar is not None:
            self._annotation_sidecar_paths[series_id] = sidecar
        if sidecar is not None and sidecar.is_file():
            try:
                import_annotations(model, sidecar, replace=True)
                # Re-saving marks the imported sidecar as the saved baseline.
                save_annotations(model, sidecar)
            except Exception as error:
                logger.warning(
                    '[MainWindow] 自动载入标注 sidecar 失败: %s', error,
                    exc_info=True,
                )
        if not self._draft_recovery_enabled(series_id):
            return
        draft = self._draft_path(series_id, model)
        if draft.is_file():
            try:
                with draft.open('r', encoding='utf-8') as handle:
                    document = json.load(handle)
                draft_metadata = document.get('draft_metadata')
                if not isinstance(draft_metadata, dict):
                    logger.info(
                        '[MainWindow] 忽略无法验证来源的旧版标注草稿: %s', draft
                    )
                    return
                if draft_metadata.get('session_id') == _ANNOTATION_DRAFT_SESSION_ID:
                    # The producer belongs to this still-running process; this
                    # is not a previous-session crash draft.
                    return
                import_annotations(model, document, replace=True)
                model.mark_annotations_dirty()
                self.status_bar.showMessage(
                    t('mainwindow.annotation_draft_recovered'), 5000
                )
            except Exception as error:
                logger.warning(
                    '[MainWindow] 恢复标注草稿失败: %s', error, exc_info=True
                )

    def _schedule_annotation_draft(self, series_id: str) -> None:
        if not self._draft_recovery_enabled(series_id):
            return
        timer = self._annotation_draft_timers.get(series_id)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(
                lambda sid=series_id: self._write_annotation_draft(sid)
            )
            self._annotation_draft_timers[series_id] = timer
        timer.start(750)

    def _write_annotation_draft(self, series_id: str) -> None:
        history = self._annotation_histories.get(series_id)
        if (
            not history
            or not self._draft_recovery_enabled(series_id)
            or not has_unsaved_annotations(history['model'])
        ):
            return
        path = self._draft_path(series_id, history['model'])
        temporary_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            document = export_annotations(history['model'])
            document['draft_metadata'] = {
                'session_id': _ANNOTATION_DRAFT_SESSION_ID,
            }
            payload = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except Exception:
            logger.exception('[MainWindow] 写入标注恢复草稿失败: %s', path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _remove_annotation_draft(self, series_id: str) -> None:
        history = self._annotation_histories.get(series_id)
        timer = self._annotation_draft_timers.pop(series_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if not history:
            return
        path = self._draft_path(series_id, history['model'])
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning('[MainWindow] 无法删除标注草稿: %s', path)

    def _save_model_annotations(
        self,
        series_id: str,
        model: ImageDataModel,
        *,
        save_as: bool = False,
    ) -> bool:
        path = self._annotation_sidecar_paths.get(series_id)
        if save_as or path is None:
            suggested = path or self._default_annotation_sidecar_path(series_id)
            if suggested is None:
                suggested = Path(QDir.homePath()) / 'MedImager_annotations.json'
            selected, _ = QFileDialog.getSaveFileName(
                self,
                t('mainwindow.save_annotations_as'),
                str(suggested),
                t('mainwindow.annotation_json_filter'),
            )
            if not selected:
                return False
            path = Path(selected)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            save_annotations(model, path)
            self._annotation_sidecar_paths[series_id] = path
            self._mark_annotation_history_saved(model)
            self.status_bar.showMessage(
                t('mainwindow.annotations_saved_to', path=str(path)), 5000
            )
            return True
        except Exception as error:
            logger.exception('[MainWindow] 保存标注失败: %s', path)
            QMessageBox.critical(
                self,
                t('mainwindow.error'),
                t('mainwindow.export_annotations_failed_prefix') + str(error),
            )
            return False

    def _save_active_annotations(self) -> None:
        series_id = self._active_series_id()
        model = self._get_active_image_model()
        if series_id and model:
            self._save_model_annotations(series_id, model)

    def _save_active_annotations_as(self) -> None:
        series_id = self._active_series_id()
        model = self._get_active_image_model()
        if series_id and model:
            self._save_model_annotations(series_id, model, save_as=True)

    def _save_all_annotations(self) -> bool:
        dirty = [
            (series_id, history['model'])
            for series_id, history in self._annotation_histories.items()
            if has_unsaved_annotations(history['model'])
        ]
        if not dirty:
            self.status_bar.showMessage(t('mainwindow.nothing_to_save'), 2000)
            return True
        for series_id, model in dirty:
            if not self._save_model_annotations(series_id, model):
                return False
        return True

    def _rebuild_roi_dependent_state_for_model(self, model: ImageDataModel) -> None:
        """清除旧 ROI 视图临时态，并立即为所有绑定窗格重建标签。"""
        for view_id in self.series_manager.get_all_view_ids():
            frame = self.multi_viewer_grid.get_view_frame(view_id)
            viewer = (
                getattr(frame, 'image_viewer', None)
                or getattr(frame, '_image_viewer', None)
            ) if frame else None
            if not viewer or viewer.model is not model:
                continue
            viewer.clear_roi_dependent_state()
            restore = getattr(frame, '_restore_roi_stats_positions', None)
            if callable(restore):
                restore()

    def _restore_annotation_snapshot(self, history: Dict, snapshot: Dict) -> None:
        model = history['model']
        history['restoring'] = True
        try:
            import_annotations(
                model,
                copy.deepcopy(snapshot),
                replace=True,
                allow_identity_mismatch=True,
            )
            history['current'] = copy.deepcopy(snapshot)
            if history['saved'] is not None and snapshot == history['saved']:
                model.mark_annotations_saved()
            else:
                model.mark_annotations_dirty()
            self._rebuild_roi_dependent_state_for_model(model)
        finally:
            history['restoring'] = False
        self._update_annotation_history_actions()

    def _undo_annotation_change(self) -> None:
        if self._route_undo_redo_to_focused_text_editor(redo=False):
            return
        history = self._annotation_histories.get(self._active_series_id() or '')
        if not history or not history['undo']:
            self.status_bar.showMessage(t("mainwindow.nothing_to_undo"), 2000)
            return
        previous = history['undo'].pop()
        history['redo'].append(copy.deepcopy(history['current']))
        self._restore_annotation_snapshot(history, previous)

    def _redo_annotation_change(self) -> None:
        if self._route_undo_redo_to_focused_text_editor(redo=True):
            return
        history = self._annotation_histories.get(self._active_series_id() or '')
        if not history or not history['redo']:
            self.status_bar.showMessage(t("mainwindow.nothing_to_redo"), 2000)
            return
        following = history['redo'].pop()
        history['undo'].append(copy.deepcopy(history['current']))
        self._restore_annotation_snapshot(history, following)

    @staticmethod
    def _route_undo_redo_to_focused_text_editor(redo: bool) -> bool:
        """标准文本控件有焦点时，保留其原生 Undo/Redo 语义。"""
        focus_widget = QApplication.focusWidget()
        if not isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return False
        operation = getattr(focus_widget, 'redo' if redo else 'undo', None)
        if not callable(operation):
            return False
        operation()
        return True
    
    def _toggle_series_panel(self, checked: bool) -> None:
        """切换序列面板显示状态"""
        logger.debug(f"[MainWindow._toggle_series_panel] 切换序列面板: {checked}")
        self.series_dock.setVisible(checked)

    def _on_left_toggle_strip_clicked(self, visible: bool) -> None:
        """处理左侧切换条点击事件"""
        logger.debug(f"[MainWindow._on_left_toggle_strip_clicked] 左侧切换条点击: {visible}")
        self.series_dock.setVisible(visible)
        # 同步菜单中的勾选状态
        if hasattr(self, 'toggle_series_panel_action'):
            self.toggle_series_panel_action.blockSignals(True)
            self.toggle_series_panel_action.setChecked(visible)
            self.toggle_series_panel_action.blockSignals(False)
    
    def _toggle_info_panel(self, checked: bool) -> None:
        """切换信息面板显示状态"""
        logger.debug(f"[MainWindow._toggle_info_panel] 切换信息面板: {checked}")
        if checked:
            self.info_dock.show()
            self.dicom_tag_panel.show()
            self._flush_pending_dicom_tags()
        else:
            self.info_dock.hide()

    def _on_toggle_strip_clicked(self, visible: bool) -> None:
        """处理切换条点击事件"""
        logger.debug(f"[MainWindow._on_toggle_strip_clicked] 切换条点击: {visible}")
        self.info_dock.setVisible(visible)
        if visible:
            self._flush_pending_dicom_tags()
        # 同步菜单中的勾选状态
        if hasattr(self, 'toggle_info_panel_action'):
            self.toggle_info_panel_action.blockSignals(True)
            self.toggle_info_panel_action.setChecked(visible)
            self.toggle_info_panel_action.blockSignals(False)

    def _on_series_dock_visibility_changed(self, visible: bool) -> None:
        if hasattr(self, 'toggle_series_panel_action'):
            self.toggle_series_panel_action.blockSignals(True)
            self.toggle_series_panel_action.setChecked(visible)
            self.toggle_series_panel_action.blockSignals(False)

    def _on_info_dock_visibility_changed(self, visible: bool) -> None:
        if hasattr(self, 'toggle_info_panel_action'):
            self.toggle_info_panel_action.blockSignals(True)
            self.toggle_info_panel_action.setChecked(visible)
            self.toggle_info_panel_action.blockSignals(False)
        if visible:
            self.dicom_tag_panel.show()
            self._flush_pending_dicom_tags()
        elif self.info_dock.isHidden():
            self.dicom_tag_panel.hide()

    def eventFilter(self, watched, event) -> bool:
        """Bridge the legacy information-panel visibility API to its dock."""
        if (
            watched is getattr(self, 'dicom_tag_panel', None)
            and event.type() == QEvent.Type.Show
            and hasattr(self, 'info_dock')
            and self.info_dock.isHidden()
        ):
            self.info_dock.show()
        return super().eventFilter(watched, event)

    def _queue_dicom_tag_update(self, dataset) -> None:
        """缓存最新标签；仅在面板显示时以最多约 10 fps 重建树。"""
        self._pending_dicom_dataset = dataset
        if getattr(self, '_closing', False):
            return
        if not self.info_dock.isVisible():
            return
        timer = self._dicom_tag_update_timer
        if not timer.isActive():
            timer.start(100)

    def _flush_pending_dicom_tags(self) -> None:
        if not self.info_dock.isVisible():
            return
        dataset = getattr(self, '_pending_dicom_dataset', None)
        if dataset is None:
            self.dicom_tag_panel.clear()
        else:
            self.dicom_tag_panel.update_tags(dataset)
    
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

                # 先按特殊布局的实际槽位更新序列管理器，避免绑定表显示不存在的视图。
                equivalent = self.multi_viewer_grid._get_equivalent_layout(layout_config)
                positions = self.multi_viewer_grid._get_special_view_positions(layout_config)
                self.series_manager.set_custom_layout(positions, equivalent)

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
                    logger.info("[MainWindow._set_layout] 回退到默认2×2网格布局")
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
        
        self.status_bar.showMessage(t("mainwindow.auto_assignment_complete_value_sequences_assigned").replace("%1", str(assigned_count)), 3000)
        logger.info(f"[MainWindow._auto_assign_all_series] 自动分配完成: {assigned_count}个序列")
    
    def _apply_hanging_protocol(self, protocol: HangingProtocolId) -> None:
        active_series_id = self._active_series_id()
        infos = [
            self.series_manager.get_series_info(series_id)
            for series_id in self.series_manager.get_all_series_ids()
        ]
        plan = build_hanging_plan(
            protocol,
            [info for info in infos if info is not None],
            active_series_id,
        )
        if not plan.series_ids:
            self.status_bar.showMessage(t("mainwindow.hanging_no_series"), 3000)
            return
        if protocol is HangingProtocolId.CURRENT_MPR:
            view_id = self.series_manager.get_active_view_id()
            if view_id:
                self.series_manager.bind_series_to_view(view_id, plan.series_ids[0])
            self._toggle_mpr_workspace()
            return
        self._set_layout(plan.layout)
        view_ids = self.series_manager.get_all_view_ids()
        for view_id, series_id in zip(view_ids, plan.series_ids):
            self.series_manager.bind_series_to_view(view_id, series_id)
        if view_ids:
            self.series_manager.set_active_view(view_ids[0])
        self.status_bar.showMessage(t("mainwindow.hanging_applied"), 3000)
        self._schedule_workspace_state_save()

    @staticmethod
    def _workspace_study_key(study_instance_uid: str) -> Optional[str]:
        uid = str(study_instance_uid or "").strip()
        if not uid:
            return None
        return hashlib.sha256(uid.encode("utf-8", "replace")).hexdigest()[:24]

    def _schedule_workspace_state_save(self) -> None:
        if not self._restoring_workspace and not self._closing:
            self._workspace_state_timer.start(500)

    def _save_study_workspace_state(self) -> None:
        series_id = self._active_series_id()
        info = self.series_manager.get_series_info(series_id) if series_id else None
        study_key = self._workspace_study_key(
            info.study_instance_uid if info is not None else ""
        )
        if not study_key:
            return
        bindings = {}
        presentations = {}
        for view_id in self.series_manager.get_all_view_ids():
            binding = self.series_manager.get_view_binding(view_id)
            if not binding or not binding.series_id:
                continue
            series_info = self.series_manager.get_series_info(binding.series_id)
            if not series_info or not series_info.series_instance_uid:
                continue
            uid = series_info.series_instance_uid
            bindings[view_id] = uid
            frame = self.multi_viewer_grid.get_view_frame(view_id)
            viewer = getattr(frame, "image_viewer", None) if frame else None
            state = getattr(viewer, "presentation_state", None)
            if state is not None:
                presentations[view_id] = {
                    "series_uid": uid,
                    "slice": int(state.slice_index),
                    "ww": float(state.window_width),
                    "wl": float(state.window_level),
                    "zoom": float(state.zoom),
                    "pan": [float(state.pan_center.x()), float(state.pan_center.y())],
                    "invert": bool(state.inverted),
                    "interpolation": state.interpolation.value,
                    "fit": bool(state.fit_mode),
                }
        states = self.settings_manager.get_setting("study_workspace.states", {})
        if not isinstance(states, dict):
            states = {}
        states[study_key] = {
            "updated": time.time(),
            "layout": list(self.series_manager.get_current_layout()),
            "bindings": bindings,
            "presentations": presentations,
            "active_view": self.series_manager.get_active_view_id() or "",
            "sync_mode": int(self.sync_manager.get_sync_mode().value),
        }
        if len(states) > 20:
            keep = sorted(
                states,
                key=lambda key: float(states[key].get("updated", 0.0)),
                reverse=True,
            )[:20]
            states = {key: states[key] for key in keep}
        self.settings_manager.set_setting("study_workspace.states", states)

    def _restore_study_workspace_for_series(self, series_id: str) -> bool:
        info = self.series_manager.get_series_info(series_id)
        study_key = self._workspace_study_key(
            info.study_instance_uid if info is not None else ""
        )
        if not study_key or study_key in self._restored_study_keys:
            return False
        states = self.settings_manager.get_setting("study_workspace.states", {})
        state = states.get(study_key) if isinstance(states, dict) else None
        if not isinstance(state, dict):
            self._restored_study_keys.add(study_key)
            return False
        uid_to_series = {
            candidate.series_instance_uid: candidate.series_id
            for candidate in (
                self.series_manager.get_series_info(sid)
                for sid in self.series_manager.get_all_series_ids()
            )
            if candidate is not None and candidate.series_instance_uid
        }
        loaded_uids = {
            candidate.series_instance_uid
            for candidate in (
                self.series_manager.get_series_info(sid)
                for sid in self.series_manager.get_all_series_ids()
            )
            if candidate is not None
            and candidate.series_instance_uid
            and candidate.is_loaded
        }
        required_uids = set(state.get("bindings", {}).values())
        if not required_uids.issubset(loaded_uids):
            return False
        self._restored_study_keys.add(study_key)
        try:
            self._restoring_workspace = True
            layout = state.get("layout", [1, 1])
            if (
                isinstance(layout, (list, tuple))
                and len(layout) == 2
                and all(isinstance(value, int) for value in layout)
            ):
                self._set_layout((layout[0], layout[1]))
            for view_id, series_uid in state.get("bindings", {}).items():
                target_series = uid_to_series.get(series_uid)
                if target_series and self.series_manager.get_view_binding(view_id):
                    self.series_manager.bind_series_to_view(view_id, target_series)
            active_view = str(state.get("active_view", ""))
            if self.series_manager.get_view_binding(active_view):
                self.series_manager.set_active_view(active_view)
            from medimager.core.sync_manager import SyncMode
            try:
                self.sync_manager.set_sync_mode(SyncMode(int(state.get("sync_mode", 0))))
            except (TypeError, ValueError):
                pass
            self._apply_restored_presentations(state.get("presentations", {}), uid_to_series)
        finally:
            self._restoring_workspace = False
        self.status_bar.showMessage(t("mainwindow.study_workspace_restored"), 2500)
        return True

    def _apply_restored_presentations(self, saved: Dict, uid_to_series: Dict[str, str]) -> None:
        if not isinstance(saved, dict):
            return
        for view_id, values in saved.items():
            if not isinstance(values, dict):
                continue
            binding = self.series_manager.get_view_binding(view_id)
            expected = uid_to_series.get(str(values.get("series_uid", "")))
            if not binding or binding.series_id != expected:
                continue
            frame = self.multi_viewer_grid.get_view_frame(view_id)
            viewer = getattr(frame, "image_viewer", None) if frame else None
            state = getattr(viewer, "presentation_state", None)
            if state is None:
                continue
            state.slice_index = int(values.get("slice", state.slice_index))
            state.window_width = float(values.get("ww", state.window_width))
            state.window_level = float(values.get("wl", state.window_level))
            state.zoom = float(values.get("zoom", state.zoom))
            pan = values.get("pan", [state.pan_center.x(), state.pan_center.y()])
            if isinstance(pan, (list, tuple)) and len(pan) == 2:
                state.pan_center.setX(float(pan[0]))
                state.pan_center.setY(float(pan[1]))
            state.inverted = bool(values.get("invert", state.inverted))
            state.interpolation = InterpolationMode.coerce(
                values.get("interpolation", state.interpolation)
            )
            state.fit_mode = bool(values.get("fit", state.fit_mode))
            model = self.series_manager.get_series_model(expected)
            state.clamp(model.get_slice_count() if model else None)
            viewer.set_presentation_state(state)

    def _clear_all_bindings(self) -> None:
        """清除所有绑定"""
        logger.debug("[MainWindow._clear_all_bindings] 清除所有绑定")
        
        view_ids = self.series_manager.get_all_view_ids()
        cleared_count = 0
        
        for view_id in view_ids:
            if self.series_manager.unbind_series_from_view(view_id):
                cleared_count += 1
        
        self.status_bar.showMessage(t("mainwindow.unbinding_completed_value_bindings_removed").replace("%1", str(cleared_count)), 3000)
        logger.info(f"[MainWindow._clear_all_bindings] 清除绑定完成: {cleared_count}个绑定")
    
    def _set_sync_mode(self, mode) -> None:
        """设置同步模式"""
        logger.debug(f"[MainWindow._set_sync_mode] 设置同步模式: {mode}")
        self.sync_manager.set_sync_mode(mode)
        self.status_bar.showMessage(t("mainwindow.sync_mode_set_value").replace("%1", mode.name), 2000)
        logger.info(f"[MainWindow._set_sync_mode] 同步模式设置完成: {mode}")
    
    def _set_sync_group(self, group) -> None:
        """设置同步分组"""
        logger.debug(f"[MainWindow._set_sync_group] 设置同步分组: {group}")
        self.sync_manager.set_sync_group(group)
        self.statusBar().showMessage(
            t("mainwindow.synchronization_grouping_has_been_set"), 2000
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
            status_msg = t("mainwindow.automatic_location_synchronization_is_enabled")
        elif mode == "manual":
            new_mode = current_mode | SyncMode.CROSS_REFERENCE
            new_mode = new_mode & ~SyncMode.SLICE
            status_msg = t("mainwindow.manual_position_synchronization_is_enabled")
        elif mode == "both":
            new_mode = current_mode | SyncMode.SLICE | SyncMode.CROSS_REFERENCE
            status_msg = t("mainwindow.combined_position_synchronization_is_enabled")
        else:  # "none"
            new_mode = current_mode & ~(SyncMode.SLICE | SyncMode.CROSS_REFERENCE)
            status_msg = t("mainwindow.location_sync_is_off")
        
        self.sync_manager.set_sync_mode(new_mode)
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_position_changed] 同步模式更新: {new_mode}")

    def _on_sync_pan_changed(self, checked: bool) -> None:
        """平移同步状态变化处理"""
        logger.debug(f"[MainWindow._on_sync_pan_changed] 平移同步状态变化: {checked}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        if checked:
            new_mode = current_mode | SyncMode.PAN
        else:
            new_mode = current_mode & ~SyncMode.PAN
        
        self.sync_manager.set_sync_mode(new_mode)
        status_msg = t("mainwindow.pan_sync_enabled") if checked else t("mainwindow.translation_sync_disabled")
        self.statusBar().showMessage(status_msg, 2000)
        logger.debug(f"[MainWindow._on_sync_pan_changed] 同步模式更新: {new_mode}")

    def _on_sync_zoom_changed(self, checked: bool) -> None:
        """缩放同步状态变化处理"""
        logger.debug(f"[MainWindow._on_sync_zoom_changed] 缩放同步状态变化: {checked}")
        
        current_mode = self.sync_manager.get_sync_mode()
        from medimager.core.sync_manager import SyncMode
        
        if checked:
            new_mode = current_mode | SyncMode.ZOOM
        else:
            new_mode = current_mode & ~SyncMode.ZOOM
        
        self.sync_manager.set_sync_mode(new_mode)
        status_msg = t("mainwindow.zoom_sync_enabled") if checked else t("mainwindow.zoom_sync_disabled")
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
        status_msg = t("mainwindow.window_width_and_position_synchronization_is_enabled") if checked else t("mainwindow.window_width_synchronization_is_turned_off")
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
            if (
                SyncMode.SLICE in current_mode
                and SyncMode.CROSS_REFERENCE in current_mode
            ):
                position_mode = "both"
            elif SyncMode.SLICE in current_mode:
                position_mode = "auto"
            elif SyncMode.CROSS_REFERENCE in current_mode:
                position_mode = "manual"
            
            # 设置同步状态
            self._sync_button.set_sync_states(
                position_mode=position_mode,
                pan=SyncMode.PAN in current_mode,
                zoom=SyncMode.ZOOM in current_mode,
                window_level=SyncMode.WINDOW_LEVEL in current_mode
            )
        
        logger.debug("[MainWindow._update_sync_button_states] 同步按钮状态更新完成")
    
    def _open_multiple_dicom_folders(self) -> None:
        """打开多个DICOM文件夹"""
        logger.debug("[MainWindow._open_multiple_dicom_folders] 打开多个DICOM文件夹")
        
        # 使用文件对话框选择多个文件夹
        dialog = QFileDialog(self, t("mainwindow.select_dicom_folder"), QDir.homePath())
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        # 原生目录对话框通常只能单选。使用 Qt 对话框并将目录视图设为
        # ExtendedSelection，才能兑现“打开多个文件夹”的功能名称。
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        for view in dialog.findChildren(QListView) + dialog.findChildren(QTreeView):
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        
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
            t("mainwindow.select_dicom_folder"),
            QDir.homePath()
        )
        
        if folder:
            self._load_dicom_folder_as_series(folder)
    
    def _load_dicom_folder_as_series(self, folder_path: str) -> None:
        """提交后台 DICOM 扫描任务；文件遍历和头信息预读不阻塞 GUI。"""
        logger.debug(f"[MainWindow._load_dicom_folder_as_series] 加载DICOM文件夹: {folder_path}")
        normalized = str(Path(folder_path).resolve())
        if normalized in self._folder_scan_futures:
            self.status_bar.showMessage(t("mainwindow.folder_scan_in_progress"), 2000)
            return
        self._prepare_load_batch()
        pool = get_performance_manager().get_thread_pool()
        future = pool.submit(
            _scan_dicom_folder_task,
            normalized,
            self._bool_setting("dicom.recursive_scan", True),
            self._bool_setting("dicom.include_extensionless", True),
            self._bool_setting("dicom.strict_metadata", False),
        )
        self._folder_scan_futures[normalized] = future

        def _on_done(done_future):
            try:
                self._folder_scan_done.emit(normalized, done_future)
            except RuntimeError:
                return

        future.add_done_callback(_on_done)
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setVisible(True)
        self.loading_cancel_button.show()
        self.status_bar.showMessage(
            t("mainwindow.scanning_dicom_folder", name=Path(normalized).name)
        )

    def _finish_loading_ui_if_idle(self) -> None:
        """所有扫描和解码结束后统一收尾，避免并发任务争抢进度状态。"""
        if self._folder_scan_futures or self._loading_futures:
            return
        self.loading_progress.setRange(0, 1)
        self.loading_progress.setValue(1)
        self.loading_progress.setVisible(False)
        self.loading_cancel_button.hide()
        self.loading_retry_button.setVisible(
            bool(self._failed_load_requests or self._failed_folder_requests)
        )
        if self._closing:
            self._loading_errors.clear()
            if getattr(self, '_close_after_loading', False):
                QTimer.singleShot(0, self.close)
            return
        counts = dict(self._load_batch_counts)
        if self._loading_errors and not self._closing:
            self._last_loading_errors = list(self._loading_errors)
            self.loading_details_button.show()
            errors = self._loading_errors[:8]
            remaining = len(self._loading_errors) - len(errors)
            details = "\n".join(f"• {message}" for message in errors)
            if remaining > 0:
                details += "\n" + t("mainwindow.additional_load_errors", count=remaining)
            QMessageBox.critical(
                self,
                t("mainwindow.error"),
                t("mainwindow.some_files_failed_to_load") + "\n\n" + details,
            )
            if counts['succeeded']:
                status = t(
                    'mainwindow.load_partial_summary',
                    succeeded=counts['succeeded'],
                    failed=counts['failed'],
                    cancelled=counts['cancelled'],
                )
            else:
                status = t(
                    'mainwindow.load_failed_summary',
                    failed=counts['failed'],
                    cancelled=counts['cancelled'],
                )
            self.status_bar.showMessage(status, 7000)
            self._loading_errors.clear()
        elif counts['cancelled'] and not counts['succeeded']:
            self._last_loading_errors.clear()
            self.loading_details_button.hide()
            self.status_bar.showMessage(
                t('mainwindow.load_cancelled_summary', cancelled=counts['cancelled']),
                5000,
            )
        else:
            self._last_loading_errors.clear()
            self.loading_details_button.hide()
            self.status_bar.showMessage(
                t('mainwindow.load_success_summary', succeeded=counts['succeeded']),
                3000,
            )
        self._load_batch_counts = {
            'submitted': 0, 'succeeded': 0, 'failed': 0, 'cancelled': 0
        }

    def _prepare_load_batch(self) -> None:
        if self._folder_scan_futures or self._loading_futures:
            return
        self._loading_errors.clear()
        self._last_loading_errors.clear()
        if hasattr(self, 'loading_details_button'):
            self.loading_details_button.hide()
        self._load_batch_counts = {
            'submitted': 0, 'succeeded': 0, 'failed': 0, 'cancelled': 0
        }

    def _cancel_pending_loads(self) -> None:
        for series_id, future in list(self._loading_futures.items()):
            self._cancelled_load_ids.add(series_id)
            future.cancel()
        for folder_path, future in list(self._folder_scan_futures.items()):
            self._cancelled_folder_scans.add(folder_path)
            future.cancel()
        self.status_bar.showMessage(t('mainwindow.cancelling_loads'))

    def _retry_failed_loads(self) -> None:
        requests = list(self._failed_load_requests.values())
        folder_requests = list(self._failed_folder_requests)
        if not requests and not folder_requests:
            return
        self._failed_load_requests.clear()
        self._failed_folder_requests.clear()
        self.loading_retry_button.hide()
        self._prepare_load_batch()
        for folder_path in folder_requests:
            self._load_dicom_folder_as_series(folder_path)
        for request in requests:
            info = copy.deepcopy(request['series_info'])
            info.is_loaded = False
            series_id = self.series_manager.add_series(info)
            if request['kind'] == 'single':
                self._load_single_image_in_background(
                    series_id, request['file_path'], info
                )
            else:
                self._load_series_in_background(
                    series_id, list(request['file_paths']), info
                )

    def _show_loading_details(self) -> None:
        if not self._last_loading_errors:
            return
        QMessageBox.information(
            self,
            t('mainwindow.loading_details'),
            '\n'.join(f'• {detail}' for detail in self._last_loading_errors),
        )

    def _on_folder_scan_finished(self, folder_path: str, future) -> None:
        """在 GUI 线程消费后台扫描结果并启动各序列解码。"""
        try:
            if folder_path in self._cancelled_folder_scans:
                try:
                    future.result()
                except (CancelledError, Exception):
                    pass
                self._cancelled_folder_scans.discard(folder_path)
                self._load_batch_counts['cancelled'] += 1
                return
            if self._closing:
                return
            result: _FolderScanResult = future.result()
            if result.error:
                detail = t(
                    "mainwindow.failed_to_load_dicom_folder_value"
                ).replace("%1", result.error)
                self._loading_errors.append(detail)
                self._load_batch_counts['failed'] += 1
                self._failed_folder_requests[folder_path] = {
                    'folder_path': folder_path,
                }
                logger.error(
                    '[MainWindow] DICOM folder scan failed: %s', detail
                )
                return
            if result.candidate_count == 0:
                QMessageBox.warning(
                    self, t("mainwindow.warning"), t("mainwindow.dicom_file_not_found_in_folder")
                )
                return

            existing_uids = {
                self.series_manager.get_series_info(series_id).series_instance_uid
                for series_id in self.series_manager.get_all_series_ids()
                if self.series_manager.get_series_info(series_id)
            }
            added = 0
            ordered_series = sorted(result.series, key=self._series_load_priority)
            for item in ordered_series:
                uid = item['series_instance_uid']
                if uid and uid in existing_uids:
                    logger.info("[MainWindow._on_folder_scan_finished] 跳过重复序列: %s", uid)
                    continue
                series_info = SeriesInfo(series_id=str(uuid.uuid4()), **item)
                series_id = self.series_manager.add_series(series_info)
                self._load_series_in_background(series_id, item['file_paths'], series_info)
                if uid:
                    existing_uids.add(uid)
                added += 1

            if result.skipped_count:
                self._load_batch_counts['failed'] += result.skipped_count
                self._loading_errors.append(
                    t(
                        'mainwindow.scan_skipped_series_detail',
                        count=result.skipped_count,
                    )
                )
                self.status_bar.showMessage(
                    t(
                        "mainwindow.scan_series_summary",
                        series_count=len(result.series),
                        skipped_count=result.skipped_count,
                    ),
                    5000,
                )
            if added == 0 and not result.series:
                QMessageBox.warning(
                    self,
                    t("mainwindow.warning"),
                    t("mainwindow.no_loadable_series_matching_metadata_rules"),
                )
            logger.info(
                "[MainWindow._on_folder_scan_finished] 扫描完成: folder=%s, added=%d",
                folder_path, added,
            )
        except Exception as error:
            logger.error("[MainWindow._on_folder_scan_finished] 处理扫描结果失败: %s", error, exc_info=True)
            detail = t("mainwindow.failed_to_load_dicom_folder_value").replace(
                "%1", str(error)
            )
            self._loading_errors.append(detail)
            self._load_batch_counts['failed'] += 1
            self._failed_folder_requests[folder_path] = {
                'folder_path': folder_path,
            }
        finally:
            self._folder_scan_futures.pop(folder_path, None)
            self._finish_loading_ui_if_idle()

    def _warn_if_strict_metadata_incomplete(self, dataset, file_path: str) -> bool:
        """检查严格元数据要求，完整返回 True；缺失时返回 False。"""
        if not self._bool_setting("dicom.strict_metadata", False):
            return True
        required_tags = [
            "SeriesInstanceUID",
            "StudyInstanceUID",
            "Modality",
            "Rows",
            "Columns",
            "PhotometricInterpretation",
        ]
        missing = [tag for tag in required_tags if not getattr(dataset, tag, None)]
        if missing:
            logger.warning(
                "[MainWindow._warn_if_strict_metadata_incomplete] DICOM 缺失关键标签: "
                f"{missing}, file={file_path}"
            )
            return False
        return True
    
    def _series_load_priority(self, item: Dict) -> tuple:
        """FIFO pool priority: active study, diagnostic series, then DICOM order."""
        active_id = self._active_series_id()
        active = self.series_manager.get_series_info(active_id) if active_id else None
        same_study = bool(
            active
            and active.study_instance_uid
            and item.get("study_instance_uid") == active.study_instance_uid
        )
        description = " ".join(
            str(item.get(key, ""))
            for key in ("series_description", "protocol_name")
        ).casefold()
        is_localizer = any(
            term in description
            for term in ("localizer", "scout", "survey", "topogram", "定位", "序列定位")
        )
        modality_rank = {
            "CT": 0, "MR": 1, "PT": 2, "NM": 3, "US": 4, "CR": 5, "DX": 6
        }.get(str(item.get("modality", "")).upper(), 9)
        try:
            series_number = int(str(item.get("series_number", "")).strip())
        except (TypeError, ValueError):
            series_number = 1_000_000
        return (
            0 if same_study else 1,
            1 if is_localizer else 0,
            modality_rank,
            series_number,
            str(item.get("series_instance_uid", "")),
        )

    def _prefetch_active_neighbors(self, slice_index: int) -> None:
        if len(self._prefetch_pending) >= 8:
            return
        view_id = self.series_manager.get_active_view_id()
        binding = self.series_manager.get_view_binding(view_id) if view_id else None
        if not binding or not binding.series_id:
            return
        model = self.series_manager.get_series_model(binding.series_id)
        frame = self.multi_viewer_grid.get_view_frame(view_id)
        viewer = getattr(frame, "image_viewer", None) if frame else None
        state = getattr(viewer, "presentation_state", None)
        if model is None or state is None:
            return
        futures = prefetch_display_slices(
            model,
            state,
            (slice_index + 1, slice_index - 1, slice_index + 2, slice_index - 2),
        )
        for cache_key, future in futures:
            if cache_key in self._prefetch_pending:
                future.cancel()
                continue
            self._prefetch_pending.add(cache_key)
            future.add_done_callback(
                lambda _future, key=cache_key: self._prefetch_pending.discard(key)
            )

    def _load_series_in_background(self, series_id: str, file_paths: List[str], series_info: SeriesInfo) -> None:
        """使用性能管理器的线程池在后台加载序列"""
        logger.debug(f"[MainWindow._load_series_in_background] 后台加载序列: {series_id}")

        self._prepare_load_batch()
        self._load_requests[series_id] = {
            'kind': 'series',
            'series_info': copy.deepcopy(series_info),
            'file_paths': list(file_paths),
        }
        self._load_batch_counts['submitted'] += 1
        # 获取性能管理器的线程池
        perf_manager = get_performance_manager()
        thread_pool = perf_manager.get_thread_pool()

        # 提交加载任务到线程池
        future = thread_pool.submit(_load_series_task, file_paths, series_id)
        self._loading_futures[series_id] = future

        # 使用信号将结果安全地传回主线程（QTimer.singleShot 从工作线程调用不可靠）
        def _on_done(fut):
            try:
                self._series_load_done.emit(series_id, fut)
            except RuntimeError:
                # 主窗口可能已在任务结束前销毁。
                return

        future.add_done_callback(_on_done)

        # 显示加载进度
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setAccessibleName(t("mainwindow.loading_sequence_value").replace("%1", series_info.series_description or series_id))
        self.loading_progress.setVisible(True)
        self.loading_cancel_button.show()
        self.status_bar.showMessage(t("mainwindow.loading_sequence_value").replace("%1", series_info.series_description or series_id))

    def _load_single_image_in_background(
        self,
        series_id: str,
        file_path: str,
        series_info: SeriesInfo,
    ) -> None:
        """后台读取单文件；完成后复用统一的 GUI 线程收尾流程。"""
        self._prepare_load_batch()
        self._load_requests[series_id] = {
            'kind': 'single',
            'series_info': copy.deepcopy(series_info),
            'file_path': str(file_path),
        }
        self._load_batch_counts['submitted'] += 1
        pool = get_performance_manager().get_thread_pool()
        future = pool.submit(
            _load_single_image_task,
            file_path,
            series_id,
            self._bool_setting("dicom.strict_metadata", False),
        )
        self._loading_futures[series_id] = future

        def _on_done(done_future):
            try:
                self._series_load_done.emit(series_id, done_future)
            except RuntimeError:
                return

        future.add_done_callback(_on_done)
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setAccessibleName(
            t("mainwindow.loading_sequence_value").replace("%1", series_info.series_description)
        )
        self.loading_progress.setVisible(True)
        self.loading_cancel_button.show()
        self.status_bar.showMessage(
            t("mainwindow.loading_sequence_value").replace("%1", series_info.series_description)
        )

    def _on_series_loading_finished(self, series_id: str, future) -> None:
        """处理序列加载完成（在主线程中执行）"""
        logger.debug(f"[MainWindow._on_series_loading_finished] 序列加载完成: {series_id}")

        try:
            if series_id in self._cancelled_load_ids:
                try:
                    cancelled_result = future.result()
                    if cancelled_result.image_model is not None:
                        cancelled_result.image_model.deleteLater()
                except (CancelledError, Exception):
                    pass
                self._load_batch_counts['cancelled'] += 1
                self._cancelled_load_ids.discard(series_id)
                self.series_manager.remove_series(series_id)
                self._load_requests.pop(series_id, None)
                return
            result: _SeriesLoadResult = future.result()

            if self._closing:
                if result.image_model is not None:
                    result.image_model.deleteLater()
                    result.image_model = None
                return

            if result.success and result.image_model:
                series_info = self.series_manager.get_series_info(series_id)
                if series_info and result.metadata:
                    for field_name, value in result.metadata.items():
                        if hasattr(series_info, field_name):
                            setattr(series_info, field_name, value)
                if series_info:
                    series_info.slice_count = result.image_model.get_slice_count()
                # 将图像模型添加到管理器
                success = self.series_manager.load_series_data(series_id, result.image_model)

                if success:
                    logger.info(f"[MainWindow._on_series_loading_finished] 序列数据加载成功: {series_id}")
                    self._load_batch_counts['succeeded'] += 1
                    self._load_requests.pop(series_id, None)
                else:
                    logger.error(f"[MainWindow._on_series_loading_finished] 序列数据加载失败: {series_id}")
                    self._loading_errors.append(
                        f"{series_id}: {t('mainwindow.cannot_add_decoded_series_to_view')}"
                    )
                    self._load_batch_counts['failed'] += 1
                    request = self._load_requests.pop(series_id, None)
                    if request:
                        self._failed_load_requests[series_id] = request
                    self._remove_failed_series(
                        series_id, t('mainwindow.cannot_add_decoded_series_to_view')
                    )
            else:
                logger.error(f"[MainWindow._on_series_loading_finished] 序列加载失败: {series_id}")
                if result.error_key:
                    detail = t(result.error_key, **result.error_args)
                elif result.error:
                    detail = result.error
                else:
                    detail = t("mainwindow.unknown_decoding_error")
                if result.error and result.error_key:
                    detail += f" ({result.error})"
                self._loading_errors.append(f"{series_id}: {detail}")
                self._load_batch_counts['failed'] += 1
                request = self._load_requests.pop(series_id, None)
                if request:
                    self._failed_load_requests[series_id] = request
                self._remove_failed_series(series_id, detail)

        except Exception as e:
            logger.error(f"[MainWindow._on_series_loading_finished] 处理加载完成失败: {e}", exc_info=True)
            self._loading_errors.append(f"{series_id}: {e}")
            self._load_batch_counts['failed'] += 1
            request = self._load_requests.pop(series_id, None)
            if request:
                self._failed_load_requests[series_id] = request
            self._remove_failed_series(series_id, str(e))
        finally:
            self._loading_futures.pop(series_id, None)
            self._finish_loading_ui_if_idle()

    def _remove_failed_series(self, series_id: str, detail: str) -> None:
        """回滚失败序列，并在它原先绑定的窗格内保留可见错误状态。"""
        view_ids = self.series_manager.get_bound_views_for_series(series_id)
        self.series_manager.remove_series(series_id)
        for view_id in view_ids:
            frame = self.multi_viewer_grid.get_view_frame(view_id)
            if frame and hasattr(frame, 'show_error_state'):
                frame.show_error_state(detail)
    
    def _open_image_file(self) -> None:
        """打开图像文件"""
        logger.debug("[MainWindow._open_image_file] 打开图像文件")
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            t("mainwindow.open_image_file"),
            QDir.homePath(),
            t("mainwindow.all_supported_files_filter")
        )
        
        if file_path:
            self._load_single_image_file(file_path)
    
    def _load_single_image_file(self, file_path: str) -> None:
        """提交单文件后台读取，避免压缩 DICOM 或大图阻塞界面。"""
        logger.debug(f"[MainWindow._load_single_image_file] 加载图像文件: {file_path}")
        path = Path(file_path)
        if not path.is_file():
            QMessageBox.critical(
                self,
                t("mainwindow.error"),
                t("mainwindow.failed_to_load_image_file_value").replace("%1", str(path)),
            )
            return

        series_info = SeriesInfo(
            series_id=str(uuid.uuid4()),
            patient_name=t("mainwindow.single_image"),
            series_description=path.name,
            modality="IMG",
            series_number="1",
            slice_count=0,
            file_paths=[str(path)],
        )
        series_id = self.series_manager.add_series(series_info)
        self._load_single_image_in_background(series_id, str(path), series_info)
    
    def _load_test_series(self) -> None:
        """加载测试序列"""
        logger.debug("[MainWindow._load_test_series] 加载测试序列")
        
        try:
            from medimager.utils.resource_path import get_test_data_path, verify_resource_exists
            
            # 检查测试数据是否存在
            test_data_path = Path(get_test_data_path("dcm"))
            if not verify_resource_exists(str(test_data_path)):
                QMessageBox.information(self, t("mainwindow.information"), t("mainwindow.test_data_does_not_exist"))
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
        viewer = self._active_viewer()
        if image_model and viewer:
            if width == -1 and level == -1:
                default_state = self._default_presentation_by_series.get(
                    binding.series_id,
                    (
                        float(image_model.window_width),
                        float(image_model.window_level),
                        bool(getattr(image_model, '_use_dicom_voi_lut', False)),
                        getattr(image_model, '_voi_lut_index', None),
                    ),
                )
                width, level, use_voi_lut, voi_lut_index = default_state
                voi_setter = getattr(viewer, 'set_view_voi_lut', None)
                if use_voi_lut and callable(voi_setter):
                    voi_setter(True, voi_lut_index)
                else:
                    viewer.set_view_window(width, level)
            else:
                viewer.set_view_window(width, level)
            current_width = float(viewer.window_width)
            current_level = float(viewer.window_level)
            self.sync_manager.sync_window_level(
                active_view_id,
                current_width,
                current_level,
            )
            
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
                    viewer = self._active_viewer()
                    if viewer is not None:
                        current_width = viewer.window_width
                        current_level = viewer.window_level
                    else:
                        current_width = image_model.window_width
                        current_level = image_model.window_level
        
        dialog = CustomWLDialog(current_width, current_level, self)
        
        if dialog.exec_() == QDialog.Accepted:
            new_width, new_level = dialog.get_values()
            self._set_window_level_preset(new_width, new_level)

    def _apply_viewer_transform(self, transform_type: str) -> None:
        """对活动视图应用图像变换"""
        if getattr(self, "_mpr_active", False):
            viewer = self._active_viewer()
            if transform_type == "invert" and viewer is not None:
                viewer.invert()
            elif transform_type == "reset" and viewer is not None:
                viewer.reset_view()
            return
        active_frame = self.multi_viewer_grid.get_active_view_frame()
        if not active_frame:
            return
        viewer = active_frame._image_viewer
        if not viewer:
            return
        method = getattr(viewer, {
            'flip_h': 'flip_horizontal',
            'flip_v': 'flip_vertical',
            'rotate_left': 'rotate_left',
            'rotate_right': 'rotate_right',
            'invert': 'toggle_invert',
            'reset': 'reset_transforms',
        }.get(transform_type, ''), None)
        if method:
            method()

    def _export_current_view(self) -> None:
        """导出当前视图截图，包含覆盖层和视口边框。"""
        active_frame = self.multi_viewer_grid.get_active_view_frame()
        if not active_frame:
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.no_active_view"))
            return
        viewer = active_frame._image_viewer
        if not viewer or not viewer.image_item or viewer.image_item.pixmap().isNull():
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.current_view_has_no_image"))
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            t("mainwindow.export_current_view_screenshot"),
            QDir.homePath() + "/MedImager_export.png",
            t("mainwindow.image_files_filter")
        )
        if not file_path:
            return

        pixmap = viewer.viewport().grab()
        if pixmap.save(file_path):
            self.statusBar().showMessage(t("mainwindow.current_view_screenshot_exported_prefix") + file_path, 5000)
        else:
            QMessageBox.critical(self, t("mainwindow.error"), t("mainwindow.export_failed"))

    def _export_current_slice_image(self) -> None:
        """Export the active slice image without viewport chrome."""
        model = self._get_active_image_model()
        if not model or not model.has_image():
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.no_current_slice_image_to_export"))
            return

        display_slice = model.get_display_slice()
        if display_slice is None:
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.current_slice_image_empty"))
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            t("mainwindow.export_current_slice_image"),
            QDir.homePath() + "/MedImager_slice.png",
            t("mainwindow.image_files_filter")
        )
        if not file_path:
            return

        q_image = qimage_from_display_data(display_slice)
        if q_image.save(file_path):
            self.statusBar().showMessage(t("mainwindow.current_slice_image_exported_prefix") + file_path, 5000)
        else:
            QMessageBox.critical(self, t("mainwindow.error"), t("mainwindow.export_current_slice_image_failed"))

    def _export_annotations(self) -> None:
        """Export ROI and measurement annotations for the active series."""
        model = self._get_active_image_model()
        if not model or not model.has_image():
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.no_annotations_to_export_for_current_series"))
            return

        series_id = self._active_series_id()
        if series_id:
            self._save_model_annotations(series_id, model, save_as=True)

    def _import_annotations(self) -> None:
        """Import ROI and measurement annotations into the active series."""
        model = self._get_active_image_model()
        if not model or not model.has_image():
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.load_and_activate_series_first"))
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            t("mainwindow.import_annotations"),
            QDir.homePath(),
            t("mainwindow.annotation_json_filter")
        )
        if not file_path:
            return

        existing_count = len(model.rois) + len(model.measurements) + len(model.angle_measurements)
        replace = True
        if existing_count:
            mode_dialog = QMessageBox(self)
            mode_dialog.setIcon(QMessageBox.Question)
            mode_dialog.setWindowTitle(t("mainwindow.import_mode_title"))
            mode_dialog.setText(t("mainwindow.import_mode_prompt", existing_count=existing_count))
            replace_button = mode_dialog.addButton(
                t("mainwindow.replace_existing_annotations"),
                QMessageBox.ButtonRole.DestructiveRole,
            )
            mode_dialog.addButton(
                t("mainwindow.merge_annotations"),
                QMessageBox.ButtonRole.AcceptRole,
            )
            cancel_button = mode_dialog.addButton(QMessageBox.Cancel)
            mode_dialog.exec()
            clicked = mode_dialog.clickedButton()
            if clicked is cancel_button or clicked is None:
                return
            replace = clicked is replace_button

        try:
            counts = import_annotations(model, file_path, replace=replace)
        except AnnotationSeriesMismatchError as mismatch:
            mismatch_fields = ", ".join(sorted(mismatch.mismatches))
            mismatch_dialog = QMessageBox(self)
            mismatch_dialog.setIcon(QMessageBox.Warning)
            mismatch_dialog.setWindowTitle(t("mainwindow.warning"))
            mismatch_dialog.setText(
                t("mainwindow.annotation_identity_mismatch_prompt", fields=mismatch_fields)
            )
            import_anyway_button = mismatch_dialog.addButton(
                t("mainwindow.import_anyway"), QMessageBox.ButtonRole.DestructiveRole
            )
            cancel_button = mismatch_dialog.addButton(
                t("mainwindow.cancel"), QMessageBox.ButtonRole.RejectRole
            )
            mismatch_dialog.setDefaultButton(cancel_button)
            mismatch_dialog.exec()
            if mismatch_dialog.clickedButton() is not import_anyway_button:
                return
            try:
                counts = import_annotations(
                    model,
                    file_path,
                    replace=replace,
                    allow_identity_mismatch=True,
                )
            except Exception as error:
                logger.error("Failed to import annotations after identity override: %s", error, exc_info=True)
                QMessageBox.critical(
                    self,
                    t("mainwindow.error"),
                    t("mainwindow.import_annotations_failed_prefix") + str(error),
                )
                return
        except InvalidAnnotationError as error:
            logger.error("Rejected invalid annotations: %s", error, exc_info=True)
            QMessageBox.critical(
                self,
                t("mainwindow.error"),
                t("mainwindow.import_annotations_failed_prefix") + str(error),
            )
            return
        except Exception as e:
            logger.error(f"Failed to import annotations: {e}", exc_info=True)
            QMessageBox.critical(self, t("mainwindow.error"), t("mainwindow.import_annotations_failed_prefix") + str(e))
            return

        if replace:
            self._rebuild_roi_dependent_state_for_model(model)
        series_id = self._active_series_id()
        if series_id:
            self._annotation_sidecar_paths[series_id] = Path(file_path)
        total = getattr(counts, 'total', sum(counts[key] for key in ("rois", "measurements", "angle_measurements")))
        self.statusBar().showMessage(t("mainwindow.annotations_imported_prefix") + str(total), 5000)

    def _copy_view_to_clipboard(self) -> None:
        """复制当前视图到剪贴板"""
        active_frame = self.multi_viewer_grid.get_active_view_frame()
        if not active_frame:
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.no_active_view"))
            return
        viewer = active_frame._image_viewer
        if not viewer or not viewer.image_item or viewer.image_item.pixmap().isNull():
            QMessageBox.warning(self, t("mainwindow.warning"), t("mainwindow.current_view_has_no_image"))
            return

        pixmap = viewer.viewport().grab()
        QApplication.clipboard().setPixmap(pixmap)
        self.statusBar().showMessage(t("mainwindow.view_copied_to_clipboard"), 3000)

    def _cine_toggle_play(self):
        """切换 Cine 播放/暂停"""
        if self._cine_playing:
            self._cine_stop()
        else:
            self._cine_start()

    def _cine_start(self):
        """开始 Cine 播放"""
        view_id = self.series_manager.get_active_view_id()
        binding = self.series_manager.get_view_binding(view_id) if view_id else None
        model = self._get_active_image_model()
        if not view_id or not binding or not binding.series_id or not model or model.get_slice_count() <= 1:
            self._cine_stop()
            return
        self._cine_source_view_id = view_id
        self._cine_source_series_id = binding.series_id
        self._cine_source_model = model
        current_index = self._active_view_slice_index()
        frame_interval = self._cine_frame_interval_ms(model, current_index)
        metadata_fps = self._cine_metadata_fps(model)
        self._cine_metadata_timing = frame_interval is not None or metadata_fps is not None
        if frame_interval is not None:
            self._cine_fps = max(1, min(60, round(1000.0 / frame_interval)))
            self._update_cine_fps_widget(self._cine_fps)
        elif metadata_fps is not None:
            self._cine_fps = metadata_fps
            self._update_cine_fps_widget(metadata_fps)
        self._cine_playing = True
        interval = frame_interval or (1000.0 / self._cine_fps)
        self._cine_timer.start(max(1, round(interval)))
        if hasattr(self, '_cine_play_btn'):
            self._cine_play_btn.blockSignals(True)
            self._cine_play_btn.setChecked(True)
            self._cine_play_btn.blockSignals(False)
            # 切换为暂停图标
            from medimager.utils.resource_path import get_icon_path
            pause_icon_path = get_icon_path("pause.svg")
            self._cine_play_btn.setIcon(self.theme_manager.create_themed_icon(pause_icon_path))
            self._cine_play_btn._icon_path = pause_icon_path

    def _cine_stop(self):
        """停止 Cine 播放"""
        self._cine_playing = False
        self._cine_timer.stop()
        self._cine_source_view_id = None
        self._cine_source_series_id = None
        self._cine_source_model = None
        self._cine_metadata_timing = False
        if self._cine_fps != self._cine_configured_fps:
            self._cine_fps = self._cine_configured_fps
            self._update_cine_fps_widget(self._cine_fps)
        if hasattr(self, '_cine_play_btn'):
            self._cine_play_btn.blockSignals(True)
            self._cine_play_btn.setChecked(False)
            self._cine_play_btn.blockSignals(False)
            # 切换回播放图标
            from medimager.utils.resource_path import get_icon_path
            play_icon_path = get_icon_path("play.svg")
            self._cine_play_btn.setIcon(self.theme_manager.create_themed_icon(play_icon_path))
            self._cine_play_btn._icon_path = play_icon_path

    def _cine_advance(self):
        """Cine 播放前进一帧"""
        if getattr(self, '_closing', False):
            self._cine_stop()
            return
        model = self._cine_source_model
        view_id = self._cine_source_view_id
        series_id = self._cine_source_series_id
        binding = self.series_manager.get_view_binding(view_id) if view_id else None
        if (
            not model
            or not view_id
            or not series_id
            or binding is None
            or binding.series_id != series_id
            or self.series_manager.get_series_model(series_id) is not model
        ):
            self._cine_stop()
            return
        frame = self.multi_viewer_grid.get_view_frame(view_id)
        viewer = getattr(frame, 'image_viewer', None) if frame else None
        state = getattr(viewer, 'presentation_state', None) if viewer else None
        current_index = int(
            getattr(state, 'slice_index', getattr(model, 'current_slice_index', 0))
        )
        next_idx = (current_index + 1) % model.get_slice_count()
        setter = getattr(viewer, 'set_view_slice', None) if viewer else None
        if callable(setter):
            setter(next_idx)
        else:
            model.set_current_slice(next_idx)
        if self._cine_metadata_timing:
            interval = self._cine_frame_interval_ms(model, next_idx)
            if interval is not None:
                self._cine_timer.setInterval(max(1, round(interval)))
                display_fps = max(1, min(60, round(1000.0 / interval)))
                if display_fps != self._cine_fps:
                    self._cine_fps = display_fps
                    self._update_cine_fps_widget(display_fps)

    def _cine_set_fps(self, fps: int):
        """设置 Cine 播放帧率"""
        self._cine_configured_fps = max(1, min(60, int(fps)))
        self._cine_fps = self._cine_configured_fps
        self._cine_metadata_timing = False
        self.settings_manager.set_setting(
            'cine.default_fps', self._cine_configured_fps
        )
        self._update_cine_fps_widget(self._cine_fps)
        if self._cine_playing:
            self._cine_timer.setInterval(max(1, round(1000 / self._cine_fps)))

    def _update_cine_fps_widget(self, fps: int) -> None:
        toolbar_setter = getattr(
            getattr(self, 'main_toolbar', None), 'set_cine_fps', None
        )
        if callable(toolbar_setter):
            toolbar_setter(int(fps))
            return
        spin = getattr(self, '_cine_fps_spin', None)
        if spin is not None and spin.value() != int(fps):
            spin.blockSignals(True)
            spin.setValue(int(fps))
            spin.blockSignals(False)

    @staticmethod
    def _cine_frame_interval_ms(
        model: ImageDataModel, slice_index: int
    ) -> Optional[float]:
        getter = getattr(model, 'get_frame_interval_ms', None)
        if not callable(getter):
            return None
        try:
            value = float(getter(slice_index))
            if value > 0:
                # Avoid pathological metadata locking the GUI or spinning the
                # event loop; DICOM cine rates outside this range are not useful
                # for an interactive desktop viewer.
                return max(1000.0 / 60.0, min(10_000.0, value))
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _cine_metadata_fps(model: ImageDataModel) -> Optional[int]:
        """Read standard DICOM frame timing without coupling to one parser API."""
        interval = MainWindow._cine_frame_interval_ms(model, 0)
        if interval is not None:
            return max(1, min(60, round(1000.0 / interval)))
        getter = getattr(model, 'get_cine_frame_rate', None)
        if callable(getter):
            try:
                value = float(getter())
                if value > 0:
                    return max(1, min(60, round(value)))
            except (TypeError, ValueError):
                pass
        metadata_getter = getattr(model, 'get_slice_metadata', None)
        metadata = metadata_getter(0) if callable(metadata_getter) else {}

        def value_for(*keys, default=0):
            for key in keys:
                if key in metadata:
                    return metadata[key]
                value = model.get_metadata(key, None)
                if value is not None:
                    return value
            return default

        for keys in (
            ('RecommendedDisplayFrameRate', 'Recommended Display Frame Rate'),
            ('CineRate', 'Cine Rate'),
        ):
            try:
                value = float(value_for(*keys) or 0)
                if value > 0:
                    return max(1, min(60, round(value)))
            except (TypeError, ValueError):
                pass
        try:
            frame_time = float(
                value_for('FrameTime', 'Frame Time') or 0
            )
            if frame_time > 0:
                return max(1, min(60, round(1000.0 / frame_time)))
        except (TypeError, ValueError):
            pass
        vector = value_for('FrameTimeVector', 'Frame Time Vector', default=None)
        if vector is not None:
            try:
                values = [float(value) for value in vector if float(value) > 0]
                if values:
                    return max(1, min(60, round(1000.0 / (sum(values) / len(values)))))
            except (TypeError, ValueError):
                pass
        return None

    def _get_active_image_model(self) -> Optional[ImageDataModel]:
        """获取当前活动视图的图像模型"""
        active_view_id = self.series_manager.get_active_view_id()
        if not active_view_id:
            return None
        binding = self.series_manager.get_view_binding(active_view_id)
        if not binding or not binding.series_id:
            return None
        return self.series_manager.get_series_model(binding.series_id)

    def _open_settings_dialog(self) -> None:
        """打开设置对话框"""
        logger.debug("[MainWindow._open_settings_dialog] 打开设置对话框")

        dialog = SettingsDialog(self.settings_manager, self)

        if dialog.exec_() == QDialog.Accepted:
            # 应用新设置 - 使用set_theme确保发出信号
            current_theme = self.theme_manager.get_current_theme()
            self.theme_manager.set_theme(current_theme)
            self._apply_runtime_settings()

            # 如果语言发生了变化，提示用户部分界面需要重启才能完全生效
            if getattr(dialog, '_language_changed', False):
                QMessageBox.information(
                    self,
                    t("mainwindow.language_settings"),
                    t("mainwindow.language_changed_restart_notice")
                )

            logger.info("[MainWindow._open_settings_dialog] 设置更新完成")

    def _apply_runtime_settings(self) -> None:
        """应用设置面板中可即时生效的选项。"""
        self._cine_set_fps(self._int_setting('cine.default_fps', self._cine_fps, 1, 60))
        self.sync_manager.set_sync_mode(self._sync_mode_from_setting())
        self.sync_manager.set_sync_group(self._sync_group_from_setting())
        if hasattr(self.multi_viewer_grid, "apply_runtime_settings"):
            self.multi_viewer_grid.apply_runtime_settings()
        get_performance_manager().clear_cache()
        self._update_sync_button_states()
    
    def _show_about(self) -> None:
        """显示关于对话框"""
        QMessageBox.about(
            self,
            t("mainwindow.about_prefix") + APP_NAME,
            get_about_html()
            + '<hr><p><b>'
            + t('mainwindow.non_diagnostic_notice')
            + '</b><br>'
            + t('mainwindow.non_diagnostic_notice_tooltip')
            + '</p>'
        )
    
    # 信号处理方法
    
    def _on_series_added(self, series_id: str) -> None:
        """处理序列添加事件"""
        logger.debug(f"[MainWindow._on_series_added] 序列添加: {series_id}")
        self._update_ui_state()
    
    def _on_series_loaded(self, series_id: str) -> None:
        """处理序列加载事件"""
        logger.debug(f"[MainWindow._on_series_loaded] 序列加载: {series_id}")
        model = self.series_manager.get_series_model(series_id)
        if model is not None:
            self._default_presentation_by_series[series_id] = (
                float(model.window_width),
                float(model.window_level),
                bool(getattr(model, '_use_dicom_voi_lut', False)),
                getattr(model, '_voi_lut_index', None),
            )
        self._register_annotation_history(series_id)
        # 序列加载完成后可以进行自动分配
        if self.binding_manager.get_binding_strategy() == BindingStrategy.AUTO_ASSIGN:
            self.binding_manager.auto_assign_series_to_views([series_id])
        self._restore_study_workspace_for_series(series_id)
        self._update_ui_state()

    def _on_series_removed(self, series_id: str) -> None:
        """移除序列对应的撤销历史，避免保留已销毁模型。"""
        if self._mpr_series_id == series_id:
            self._leave_mpr_workspace()
        timer = self._annotation_draft_timers.pop(series_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._annotation_sidecar_paths.pop(series_id, None)
        self._default_presentation_by_series.pop(series_id, None)
        history = self._annotation_histories.pop(series_id, None)
        if history:
            try:
                history['model'].annotation_changed.disconnect(history['callback'])
            except (RuntimeError, TypeError):
                pass
        self._update_ui_state()

    def _request_remove_series(self, series_id: str) -> None:
        """Offer Save and remove / Discard / Cancel for a series document."""
        summary = self.series_manager.get_series_removal_summary(series_id)
        if not summary.exists:
            self.status_bar.showMessage(t('mainwindow.series_not_found'), 3000)
            return
        model = self.series_manager.get_series_model(series_id)
        allow_discard = False
        if model is not None and summary.has_unsaved_annotations:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(t('seriespanel.remove_sequence'))
            box.setText(t('mainwindow.remove_series_unsaved_prompt'))
            save_button = box.addButton(
                t('mainwindow.save_and_remove'), QMessageBox.AcceptRole
            )
            discard_button = box.addButton(
                t('mainwindow.discard_and_remove'), QMessageBox.DestructiveRole
            )
            cancel_button = box.addButton(
                t('mainwindow.cancel'), QMessageBox.RejectRole
            )
            box.setDefaultButton(save_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_button or clicked is None:
                return
            if clicked is save_button:
                if not self._save_model_annotations(series_id, model):
                    return
            else:
                allow_discard = clicked is discard_button
                self._remove_annotation_draft(series_id)
        else:
            answer = QMessageBox.question(
                self,
                t('seriespanel.remove_sequence'),
                t('mainwindow.remove_series_prompt'),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if not self.series_manager.remove_series(
            series_id, allow_unsaved_annotations=allow_discard
        ):
            QMessageBox.warning(
                self,
                t('mainwindow.warning'),
                t('mainwindow.remove_series_failed'),
            )
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[MainWindow._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")

        if (
            self._cine_playing
            and view_id == self._cine_source_view_id
            and series_id != self._cine_source_series_id
        ):
            self._cine_stop()
        
        # 如果绑定的是活动视图，更新DICOM标签面板
        active_view_id = self.series_manager.get_active_view_id()
        if view_id == active_view_id:
            self._on_view_activated(view_id)
        
        # 当新视图绑定序列时，传播工具到该视图
        if series_id:  # 绑定了序列
            self._propagate_tool_to_single_viewer(view_id)
        else:
            self._update_ui_state()
        self._schedule_workspace_state_save()

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
        self._schedule_workspace_state_save()
    
    def _on_auto_assignment_completed(self, assigned_count: int) -> None:
        """处理自动分配完成事件"""
        logger.debug(f"[MainWindow._on_auto_assignment_completed] 自动分配完成: {assigned_count}")
        self.status_bar.showMessage(t("mainwindow.auto_assignment_complete_value_sequences_assigned").replace("%1", str(assigned_count)), 3000)
        
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
            self._queue_dicom_tag_update(dicom_dataset)
        else:
            self._queue_dicom_tag_update(None)

    def _select_binding_target_view(
        self,
        series_id: str,
        candidate_view_ids: List[str],
        preferred_view_id: Optional[str] = None,
    ) -> Optional[str]:
        """Ask the user for a pane when the ASK_USER strategy is active."""
        labels = []
        label_to_id = {}
        for view_id in candidate_view_ids:
            binding = self.series_manager.get_view_binding(view_id)
            if binding is None:
                continue
            row, column = binding.position.value
            occupied = ""
            if binding.series_id:
                info = self.series_manager.get_series_info(binding.series_id)
                occupied = (
                    getattr(info, 'series_description', '') or binding.series_id
                )
            label = f"{row + 1}-{column + 1}"
            if occupied:
                label += f" — {occupied}"
            labels.append(label)
            label_to_id[label] = view_id
        if not labels:
            return None
        current_index = 0
        if preferred_view_id:
            for index, label in enumerate(labels):
                if label_to_id[label] == preferred_view_id:
                    current_index = index
                    break
        info = self.series_manager.get_series_info(series_id)
        series_name = (
            getattr(info, 'series_description', '') if info is not None else ''
        ) or series_id
        selected, accepted = QInputDialog.getItem(
            self,
            t("mainwindow.select_target_view"),
            t("mainwindow.select_target_view_for_series", series=series_name),
            labels,
            current_index,
            False,
        )
        return label_to_id.get(selected) if accepted else None

    def _on_binding_failed(self, series_id: str, reason: str) -> None:
        messages = {
            'series_not_found': t("mainwindow.binding_series_not_found"),
            'view_not_found': t("mainwindow.binding_view_not_found"),
            'no_target_view': t("mainwindow.binding_no_target_view"),
            'binding_rejected': t("mainwindow.binding_rejected"),
            'unexpected_error': t("mainwindow.binding_unexpected_error"),
            'selection_cancelled': t("mainwindow.binding_cancelled"),
        }
        message = messages.get(reason, t("mainwindow.binding_rejected"))
        self.status_bar.showMessage(message, 4000)
    
    def _on_binding_requested(self, view_id: str, series_id: str) -> None:
        """处理绑定请求事件"""
        logger.debug(f"[MainWindow._on_binding_requested] 绑定请求: view_id={view_id}, series_id={series_id}")
        
        success = self.binding_manager.bind_series_to_view(view_id, series_id)
        if success:
            logger.info(f"[MainWindow._on_binding_requested] 绑定成功: {view_id} -> {series_id}")
        else:
            logger.warning(f"[MainWindow._on_binding_requested] 绑定失败: {view_id} -> {series_id}")
    
    def _on_view_activated(self, view_id: str) -> None:
        """处理视图激活事件（合并了活动视图变化的处理逻辑）"""
        logger.debug(f"[MainWindow._on_view_activated] 视图激活: {view_id}")

        if self._cine_playing and view_id != self._cine_source_view_id:
            self._cine_stop()
        
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
        if (
            self._mpr_active
            and binding is not None
            and binding.series_id != self._mpr_series_id
        ):
            self._leave_mpr_workspace()
        if binding:
            pos_text = f"{binding.position.value[0]+1}-{binding.position.value[1]+1}"
            self.active_view_label.setText(t("mainwindow.event_view_value").replace("%1", pos_text))
        
        # 断开之前窗格自己的 presentation signal。切片不再存放在
        # 共享 model 中，否则同一序列的两个窗格无法独立浏览。
        if hasattr(self, '_current_active_viewer') and self._current_active_viewer:
            try:
                self._current_active_viewer.slice_changed.disconnect(
                    self._on_slice_changed
                )
            except (RuntimeError, TypeError):
                pass
        self._current_active_viewer = None
        
        # 更新DICOM标签面板并连接切片变化信号
        if binding and binding.series_id:
            image_model = self.series_manager.get_series_model(binding.series_id)
            if image_model and image_model.has_image():
                frame = self.multi_viewer_grid.get_view_frame(view_id)
                viewer = getattr(frame, 'image_viewer', None) if frame else None
                if viewer is not None:
                    viewer.slice_changed.connect(self._on_slice_changed)
                    self._current_active_viewer = viewer
                self._current_active_model = image_model

                slice_index = (
                    int(viewer.current_slice_index)
                    if viewer is not None
                    else image_model.current_slice_index
                )
                
                if image_model.is_dicom():
                    # 获取当前切片的DICOM数据
                    dicom_dataset = image_model.get_dicom_file(slice_index)
                    self._queue_dicom_tag_update(dicom_dataset)
                else:
                    self._queue_dicom_tag_update(None)
                
                # 同步序列面板切片选择
                if hasattr(self.series_panel, 'sync_slice_selection'):
                    self.series_panel.sync_slice_selection(
                        binding.series_id, slice_index
                    )
                    
                logger.debug(f"[MainWindow._on_view_activated] 切片信号连接成功: {binding.series_id}")
            else:
                self._current_active_model = None
                self._current_active_viewer = None
                self._queue_dicom_tag_update(None)
        else:
            self._current_active_model = None
            self._current_active_viewer = None
            self._queue_dicom_tag_update(None)
        self._update_ui_state()
        self._schedule_workspace_state_save()

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
                    self._queue_dicom_tag_update(dicom_dataset)
                    logger.debug(f"[MainWindow._on_slice_changed] DICOM标签面板已更新: 切片{slice_index}")
            
            # 同步序列面板切片选择
            active_view_id = self.series_manager.get_active_view_id()
            if active_view_id:
                binding = self.series_manager.get_view_binding(active_view_id)
                if binding and binding.series_id:
                    self.sync_manager.sync_slice(active_view_id, slice_index)
                    # 调用序列面板的同步方法
                    if hasattr(self.series_panel, 'sync_slice_selection'):
                        self.series_panel.sync_slice_selection(binding.series_id, slice_index)
                    self._schedule_workspace_state_save()
                    self._prefetch_active_neighbors(slice_index)

        except Exception as e:
            logger.error(f"[MainWindow._on_slice_changed] 处理切片变化失败: {e}", exc_info=True)
    
    def contextMenuEvent(self, event) -> None:
        """禁用主窗口的右键菜单，特别是工具栏右键菜单"""
        # 完全忽略右键菜单事件，防止显示工具栏的上下文菜单
        event.ignore()

    def _finalize_in_progress_annotation_edits(self) -> None:
        """关闭确认前提交已改变模型但尚未收到 mouseRelease 的编辑。"""
        for view_frame in self.multi_viewer_grid.get_all_view_frames().values():
            tool = getattr(view_frame.image_viewer, 'current_tool', None)
            finalizer = getattr(tool, 'finalize_interaction', None)
            if not callable(finalizer):
                continue
            try:
                finalizer()
            except Exception:
                logger.exception(
                    "[MainWindow.closeEvent] 结束视图 %s 的在途交互失败",
                    view_frame.view_id,
                )

    def _confirm_close_with_unsaved_annotations(self) -> bool:
        """关闭前保存或明确丢弃未保存标注；返回是否可继续关闭。"""
        unsaved = []
        total = 0
        for series_id in self.series_manager.get_all_series_ids():
            model = self.series_manager.get_series_model(series_id)
            if model and has_unsaved_annotations(model):
                count = len(model.rois) + len(model.measurements) + len(model.angle_measurements)
                unsaved.append((series_id, model))
                total += count
        if not unsaved:
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(t("mainwindow.warning"))
        box.setText(
            t(
                "mainwindow.unsaved_annotations_close_prompt",
                series_count=len(unsaved),
                total_count=total,
            )
        )
        save_button = box.addButton(QMessageBox.Save)
        discard_button = box.addButton(
            t("mainwindow.discard_and_close"), QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = box.addButton(
            t("mainwindow.cancel"), QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_button or clicked is None:
            return False
        if clicked is discard_button:
            # "Discard" is explicit and must remove recovery data as well.
            for series_id, _model in unsaved:
                self._remove_annotation_draft(series_id)
            return True

        output_directory = QFileDialog.getExistingDirectory(
            self,
            t("mainwindow.select_annotation_save_folder"),
            QDir.homePath(),
        )
        if not output_directory:
            return False

        used_names: Set[str] = set()
        output_path = Path(output_directory)
        try:
            for series_id, model in unsaved:
                description = str(model.get_metadata("SeriesDescription", "") or "series")
                safe_description = "".join(
                    character if character.isalnum() or character in "-_" else "_"
                    for character in description
                ).strip("_") or "series"
                uid = str(model.get_metadata("SeriesInstanceUID", "") or series_id)
                suffix = "".join(character for character in uid if character.isalnum())[-12:]
                base_name = f"{safe_description}_{suffix or series_id[:8]}"
                name = base_name
                sequence = 2
                target_path = output_path / f"{name}.json"
                while name.lower() in used_names or target_path.exists():
                    name = f"{base_name}_{sequence}"
                    sequence += 1
                    target_path = output_path / f"{name}.json"
                used_names.add(name.lower())
                save_annotations(model, target_path)
                self._mark_annotation_history_saved(model)
        except Exception as error:
            logger.error("[MainWindow.closeEvent] 保存未保存标注失败: %s", error, exc_info=True)
            QMessageBox.critical(
                self,
                t("mainwindow.error"),
                t("mainwindow.export_annotations_failed_prefix") + str(error),
            )
            return False
        return True
    
    def closeEvent(self, event) -> None:
        """处理窗口关闭事件"""
        logger.debug("[MainWindow.closeEvent] 处理窗口关闭事件")
        
        try:
            if not getattr(self, '_close_annotations_confirmed', False):
                self._finalize_in_progress_annotation_edits()
                if not self._confirm_close_with_unsaved_annotations():
                    event.ignore()
                    return
                self._close_annotations_confirmed = True
            self._cine_stop()
            if hasattr(self, 'mpr_workspace'):
                self.mpr_workspace.cancel_build()
            dicom_tag_timer = getattr(self, '_dicom_tag_update_timer', None)
            if dicom_tag_timer is not None:
                dicom_tag_timer.stop()
            self._closing = True

            # 取消所有正在进行的加载任务
            self._cancelled_load_ids.update(self._loading_futures)
            self._cancelled_folder_scans.update(self._folder_scan_futures)
            for future in list(self._loading_futures.values()) + list(self._folder_scan_futures.values()):
                future.cancel()
            # 已经开始的解码无法被 Future.cancel() 中断。保持 Qt 事件循环和
            # 主窗口存活，直到结果回到 GUI 线程并安全 deleteLater()。
            if self._loading_futures or self._folder_scan_futures:
                self._close_after_loading = True
                self.status_bar.showMessage(t('mainwindow.waiting_for_background_loads'))
                self.setEnabled(False)
                event.ignore()
                return
            
            # 保存设置
            self._workspace_state_timer.stop()
            self._save_study_workspace_state()
            self.settings_manager.save_settings()
            
            logger.info("[MainWindow.closeEvent] 应用程序正常关闭")
            event.accept()
            
        except Exception as e:
            logger.error(f"[MainWindow.closeEvent] 关闭时发生错误: {e}", exc_info=True)
            self._closing = False
            self._close_after_loading = False
            self._close_annotations_confirmed = False
            self.setEnabled(True)
            event.ignore()
