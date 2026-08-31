"""
同步管理器模块

该模块提供多视图间的同步功能，包括窗宽窗位同步、切片同步、
缩放/平移同步、交叉参考线同步等高级功能。
"""

from typing import Dict, Optional, Set, Tuple, Any
from enum import Enum, Flag
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal, QPointF
from PySide6.QtGui import QTransform

from medimager.core.multi_series_manager import MultiSeriesManager
from medimager.core.image_data_model import ImageDataModel
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


class SyncMode(Flag):
    """同步模式枚举"""
    NONE = 0
    WINDOW_LEVEL = 1        # 窗宽窗位同步
    SLICE = 2               # 切片同步
    ZOOM = 4                # 缩放同步
    CROSS_REFERENCE = 8     # 交叉参考线同步
    ROI = 16                # ROI同步
    MEASUREMENT = 32        # 测量工具同步
    PAN = 64                # 平移同步
    ZOOM_PAN = ZOOM | PAN   # 向后兼容旧的组合名称
    
    # 组合模式
    BASIC = WINDOW_LEVEL | SLICE
    ADVANCED = BASIC | ZOOM_PAN
    # ROI/measurement persistence is series-local and is not silently copied
    # between datasets. FULL therefore means every currently safe view sync.
    FULL = ADVANCED | CROSS_REFERENCE


class SyncGroup(Enum):
    """同步分组"""
    ALL_VIEWS = "all_views"         # 所有视图
    SAME_PATIENT = "same_patient"   # 同一患者
    SAME_STUDY = "same_study"       # 同一研究
    SAME_MODALITY = "same_modality" # 同一模态
    CUSTOM = "custom"               # 自定义分组


@dataclass
class ViewSyncState:
    """视图同步状态"""
    view_id: str
    series_id: Optional[str] = None
    
    # 窗宽窗位状态
    window_width: int = 400
    window_level: int = 40
    
    # 切片状态
    slice_index: int = 0
    slice_count: int = 1
    
    # 缩放平移状态
    zoom_factor: float = 1.0
    pan_offset: QPointF = None
    view_transform: QTransform = None
    
    # 交叉参考线状态
    cursor_position: QPointF = None
    
    # ROI同步状态
    rois_synced: bool = False
    last_roi_update: Optional[str] = None  # 最后更新的ROI ID
    
    # 测量工具同步状态
    measurement_synced: bool = False
    measurement_start: Optional[QPointF] = None
    measurement_end: Optional[QPointF] = None
    measurement_distance: Optional[float] = None
    measurement_unit: str = "mm"
    
    def __post_init__(self):
        """初始化后处理"""
        if self.pan_offset is None:
            self.pan_offset = QPointF(0, 0)
        if self.view_transform is None:
            self.view_transform = QTransform()
        if self.cursor_position is None:
            self.cursor_position = QPointF(-1, -1)
        
        logger.debug(f"[ViewSyncState.__post_init__] 创建视图同步状态: view_id={self.view_id}")


@dataclass
class CrossReferenceState:
    """交叉参考线状态"""
    enabled: bool = False
    source_view_id: Optional[str] = None
    cursor_scene_pos: QPointF = None
    
    def __post_init__(self):
        """初始化后处理"""
        if self.cursor_scene_pos is None:
            self.cursor_scene_pos = QPointF(-1, -1)


class SyncManager(QObject):
    """同步管理器
    
    负责管理多个视图间的同步操作，包括窗宽窗位、切片、缩放等。
    
    Signals:
        sync_mode_changed (SyncMode): 同步模式变更时发出
        sync_group_changed (SyncGroup): 同步分组变更时发出
        view_synced (str, str): 视图同步时发出，参数为(source_view_id, target_view_id)
        cross_reference_updated (str, QPointF): 交叉参考线更新时发出
    """
    
    # 信号定义
    sync_mode_changed = Signal(SyncMode)
    sync_group_changed = Signal(SyncGroup)
    view_synced = Signal(str, str)  # source_view_id, target_view_id
    cross_reference_updated = Signal(str, QPointF)  # legacy cursor signal
    cross_reference_line_updated = Signal(str, QPointF, QPointF)
    patient_cursor_updated = Signal(str, QPointF)
    roi_synced = Signal(str, str, str)  # source_view_id, target_view_id, roi_id
    measurement_synced = Signal(str, str, QPointF, QPointF, float)  # source_view_id, target_view_id, start, end, distance
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QObject] = None) -> None:
        """初始化同步管理器
        
        Args:
            series_manager: 多序列管理器
            parent: 父对象
        """
        super().__init__(parent)
        logger.debug("[SyncManager.__init__] 开始初始化同步管理器")
        
        self._series_manager = series_manager
        
        # 同步配置
        self._sync_mode = SyncMode.NONE
        # 医学数据默认只在同一检查内联动，避免不同患者之间误同步切片。
        self._sync_group = SyncGroup.SAME_STUDY
        
        # 视图同步状态
        self._view_states: Dict[str, ViewSyncState] = {}
        
        # 交叉参考线状态
        self._cross_reference = CrossReferenceState()
        self._reference_lines_visible = True
        self._shared_cursor_visible = True
        
        # 自定义分组
        self._custom_groups: Dict[str, Set[str]] = {}  # group_name -> view_ids
        
        # 同步锁，防止递归同步
        self._sync_lock = False

        # 视图网格引用，用于访问 ImageViewer 实例（由 MultiViewerGrid 设置）
        self._viewer_grid = None

        # 连接信号
        self._connect_signals()
        
        logger.info("[SyncManager.__init__] 同步管理器初始化完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[SyncManager._connect_signals] 连接同步管理器信号槽")
        
        # 序列管理器信号
        self._series_manager.binding_changed.connect(self._on_binding_changed)
        self._series_manager.active_view_changed.connect(self._on_active_view_changed)
        self._series_manager.layout_changed.connect(self._on_layout_changed)
    
    def set_viewer_grid(self, viewer_grid) -> None:
        """设置视图网格引用，用于访问 ImageViewer 实例

        Args:
            viewer_grid: MultiViewerGrid 实例
        """
        self._viewer_grid = viewer_grid
        logger.debug("[SyncManager.set_viewer_grid] 视图网格引用已设置")

    def _get_image_viewer(self, view_id: str):
        """获取指定视图的 ImageViewer 实例"""
        if self._viewer_grid:
            view_frame = self._viewer_grid.get_view_frame(view_id)
            if view_frame and view_frame.image_viewer:
                return view_frame.image_viewer
        return None

    def _get_view_slice_index(self, view_id: str, model: ImageDataModel) -> int:
        """Return the pane-local slice, falling back to legacy model state."""
        viewer = self._get_image_viewer(view_id)
        if viewer is not None and getattr(viewer, "model", None) is model:
            try:
                return int(viewer.current_slice_index)
            except (AttributeError, TypeError, ValueError):
                pass
        return int(model.current_slice_index)

    def set_sync_mode(self, mode: SyncMode) -> None:
        """设置同步模式

        Args:
            mode: 同步模式
        """
        logger.debug(f"[SyncManager.set_sync_mode] 设置同步模式: {self._sync_mode} -> {mode}")
        
        if self._sync_mode != mode:
            self._sync_mode = mode
            logger.info(f"[SyncManager.set_sync_mode] 同步模式已更新: {mode}")
            self.sync_mode_changed.emit(mode)
            
            # 如果启用交叉参考线，初始化状态
            if SyncMode.CROSS_REFERENCE in mode:
                self._cross_reference.enabled = True
            else:
                self._cross_reference.enabled = False
                self._cross_reference.source_view_id = None
                self._cross_reference.cursor_scene_pos = QPointF(-1, -1)
                for view_id in self._series_manager.get_all_view_ids():
                    viewer = self._get_image_viewer(view_id)
                    if viewer:
                        viewer.hide_cross_reference()
    
    def set_sync_group(self, group: SyncGroup) -> None:
        """设置同步分组
        
        Args:
            group: 同步分组
        """
        logger.debug(f"[SyncManager.set_sync_group] 设置同步分组: {self._sync_group} -> {group}")
        
        if self._sync_group != group:
            self._sync_group = group
            # 分组变化后旧目标可能不再属于同步集合，先清除过期参考线。
            self.clear_cross_reference()
            logger.info(f"[SyncManager.set_sync_group] 同步分组已更新: {group}")
            self.sync_group_changed.emit(group)

    def set_cross_reference_visibility(
        self,
        *,
        reference_lines: bool,
        shared_cursor: bool,
    ) -> None:
        """Control plane intersections and cursor markers independently."""

        self._reference_lines_visible = bool(reference_lines)
        self._shared_cursor_visible = bool(shared_cursor)
        for view_id in self._series_manager.get_all_view_ids():
            viewer = self._get_image_viewer(view_id)
            if viewer is None:
                continue
            if not self._reference_lines_visible and hasattr(
                viewer, "hide_reference_line"
            ):
                viewer.hide_reference_line()
            if not self._shared_cursor_visible and hasattr(
                viewer, "hide_patient_cursor"
            ):
                viewer.hide_patient_cursor()
    
    def create_custom_group(self, group_name: str, view_ids: Set[str]) -> bool:
        """创建自定义同步分组
        
        Args:
            group_name: 分组名称
            view_ids: 视图ID集合
            
        Returns:
            是否成功创建
        """
        logger.debug(f"[SyncManager.create_custom_group] 创建自定义分组: {group_name}, view_ids={view_ids}")
        
        try:
            # 验证视图ID是否有效
            all_view_ids = set(self._series_manager.get_all_view_ids())
            if not view_ids.issubset(all_view_ids):
                logger.error(f"[SyncManager.create_custom_group] 无效的视图ID: {view_ids - all_view_ids}")
                return False
            
            self._custom_groups[group_name] = view_ids
            logger.info(f"[SyncManager.create_custom_group] 自定义分组创建成功: {group_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"[SyncManager.create_custom_group] 创建自定义分组失败: {e}", exc_info=True)
            return False
    
    def sync_window_level(self, source_view_id: str, window_width: float, window_level: float) -> None:
        """同步窗宽窗位
        
        Args:
            source_view_id: 源视图ID
            window_width: 窗宽
            window_level: 窗位
        """
        logger.debug(f"[SyncManager.sync_window_level] 同步窗宽窗位: "
                    f"source={source_view_id}, W={window_width}, L={window_level}")
        
        if self._sync_lock or SyncMode.WINDOW_LEVEL not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].window_width = window_width
                self._view_states[target_view_id].window_level = window_level
                
                # 应用到图像模型
                self._apply_window_level_to_view(target_view_id, window_width, window_level)
                
                logger.debug(f"[SyncManager.sync_window_level] 窗宽窗位同步完成: "
                           f"{source_view_id} -> {target_view_id}")
                self.view_synced.emit(source_view_id, target_view_id)
            
        except Exception as e:
            logger.error(f"[SyncManager.sync_window_level] 窗宽窗位同步失败: {e}", exc_info=True)
        finally:
            self._sync_lock = False
    
    def sync_slice(self, source_view_id: str, slice_index: int) -> None:
        """同步切片位置
        
        Args:
            source_view_id: 源视图ID
            slice_index: 切片索引
        """
        logger.debug(f"[SyncManager.sync_slice] 同步切片: "
                    f"source={source_view_id}, slice={slice_index}")

        # 参考点投影依赖源/靶当前切片平面。任何切片变化都会使旧投影
        # 失效，即使当前未启用切片联动也必须先清除。
        self.clear_cross_reference()
        
        if self._sync_lock or SyncMode.SLICE not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                target_slice = self._find_corresponding_slice(
                    source_view_id, target_view_id, slice_index
                )
                if target_slice is None:
                    logger.debug(
                        "[SyncManager.sync_slice] 缺少兼容的患者空间信息，跳过: %s -> %s",
                        source_view_id, target_view_id,
                    )
                    continue
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].slice_index = target_slice
                
                # 应用到图像模型
                self._apply_slice_to_view(target_view_id, target_slice)
                
                logger.debug(f"[SyncManager.sync_slice] 切片同步完成: "
                           f"{source_view_id} -> {target_view_id}")
                self.view_synced.emit(source_view_id, target_view_id)
            
        except Exception as e:
            logger.error(f"[SyncManager.sync_slice] 切片同步失败: {e}", exc_info=True)
        finally:
            self._sync_lock = False
    
    def sync_zoom_pan(self, source_view_id: str, zoom_factor: float, 
                      pan_offset: QPointF, transform: QTransform) -> None:
        """同步缩放和平移
        
        Args:
            source_view_id: 源视图ID
            zoom_factor: 缩放因子
            pan_offset: 平移偏移
            transform: 视图变换
        """
        logger.debug(f"[SyncManager.sync_zoom_pan] 同步缩放平移: "
                    f"source={source_view_id}, zoom={zoom_factor}")
        
        sync_zoom = SyncMode.ZOOM in self._sync_mode
        sync_pan = SyncMode.PAN in self._sync_mode
        if self._sync_lock or not (sync_zoom or sync_pan):
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                target_center = None
                target_sync_pan = sync_pan
                if sync_pan:
                    target_center = self._convert_position_between_views(
                        source_view_id, target_view_id, pan_offset
                    )
                    if target_center.x() < 0 or target_center.y() < 0:
                        # 平移中心是图像坐标，跨序列时必须能用患者坐标转换。
                        target_sync_pan = False
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].zoom_factor = zoom_factor
                if target_sync_pan and target_center is not None:
                    self._view_states[target_view_id].pan_offset = QPointF(target_center)
                self._view_states[target_view_id].view_transform = QTransform(transform)
                
                # 应用到视图
                self._apply_zoom_pan_to_view(
                    target_view_id,
                    zoom_factor,
                    target_center,
                    sync_zoom=sync_zoom,
                    sync_pan=target_sync_pan,
                )
                
                logger.debug(f"[SyncManager.sync_zoom_pan] 缩放平移同步完成: "
                           f"{source_view_id} -> {target_view_id}")
                self.view_synced.emit(source_view_id, target_view_id)
            
        except Exception as e:
            logger.error(f"[SyncManager.sync_zoom_pan] 缩放平移同步失败: {e}", exc_info=True)
        finally:
            self._sync_lock = False
    
    def update_cross_reference(self, source_view_id: str, cursor_pos: QPointF) -> None:
        """更新交叉参考线
        
        Args:
            source_view_id: 源视图ID
            cursor_pos: 光标位置（场景坐标）
        """
        if not self._cross_reference.enabled or SyncMode.CROSS_REFERENCE not in self._sync_mode:
            return
        
        logger.debug(f"[SyncManager.update_cross_reference] 更新交叉参考线: "
                    f"source={source_view_id}, pos=({cursor_pos.x():.1f}, {cursor_pos.y():.1f})")
        
        try:
            self._cross_reference.source_view_id = source_view_id
            self._cross_reference.cursor_scene_pos = QPointF(cursor_pos)
            
            # The source cursor defines one patient-space point.  Each
            # target receives both that point (when it intersects the displayed
            # slice) and the clipped intersection of the two image planes.
            if self._shared_cursor_visible:
                self.patient_cursor_updated.emit(source_view_id, QPointF(cursor_pos))
            target_views = self._get_sync_targets(source_view_id)

            for target_view_id in target_views:
                line = (
                    self._plane_intersection_segment(source_view_id, target_view_id)
                    if self._reference_lines_visible
                    else None
                )
                if self._reference_lines_visible and line is not None:
                    self.cross_reference_line_updated.emit(
                        target_view_id, line[0], line[1]
                    )
                else:
                    viewer = self._get_image_viewer(target_view_id)
                    if viewer and hasattr(viewer, 'hide_reference_line'):
                        viewer.hide_reference_line()

                target_pos = self._convert_position_between_views(
                    source_view_id,
                    target_view_id,
                    cursor_pos,
                    require_on_target_plane=True,
                )
                if (
                    self._shared_cursor_visible
                    and target_pos.x() >= 0
                    and target_pos.y() >= 0
                ):
                    # Keep the old signal for extensions written against v2.4.
                    self.cross_reference_updated.emit(target_view_id, target_pos)
                    self.patient_cursor_updated.emit(target_view_id, target_pos)
                else:
                    viewer = self._get_image_viewer(target_view_id)
                    if viewer and hasattr(viewer, 'hide_patient_cursor'):
                        viewer.hide_patient_cursor()
            
        except Exception as e:
            logger.error(f"[SyncManager.update_cross_reference] 更新交叉参考线失败: {e}", exc_info=True)

    def clear_cross_reference(self, source_view_id: Optional[str] = None) -> None:
        """清除交叉参考线；指定源时只清理由该视图产生的状态。"""
        if (
            source_view_id
            and self._cross_reference.source_view_id
            and self._cross_reference.source_view_id != source_view_id
        ):
            return
        self._cross_reference.source_view_id = None
        self._cross_reference.cursor_scene_pos = QPointF(-1, -1)
        for view_id in self._series_manager.get_all_view_ids():
            viewer = self._get_image_viewer(view_id)
            if viewer:
                viewer.hide_cross_reference()
    
    def sync_roi(self, source_view_id: str, roi_data: Dict) -> None:
        """同步ROI
        
        Args:
            source_view_id: 源视图ID
            roi_data: ROI数据字典，包含ROI的所有信息
        """
        logger.debug(f"[SyncManager.sync_roi] 同步ROI: "
                    f"source={source_view_id}, roi_type={roi_data.get('type', 'unknown')}")
        
        if self._sync_lock or SyncMode.ROI not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].rois_synced = True
                self._view_states[target_view_id].last_roi_update = roi_data.get('id')
                
                # 应用到目标视图
                self._apply_roi_to_view(target_view_id, roi_data)
                
                logger.debug(f"[SyncManager.sync_roi] ROI同步完成: "
                           f"{source_view_id} -> {target_view_id}")
                self.roi_synced.emit(source_view_id, target_view_id, roi_data.get('id', ''))
            
        except Exception as e:
            logger.error(f"[SyncManager.sync_roi] ROI同步失败: {e}", exc_info=True)
        finally:
            self._sync_lock = False
    
    def sync_measurement(self, source_view_id: str, start_point: QPointF, 
                        end_point: QPointF, distance: float, unit: str = "mm") -> None:
        """同步测量工具
        
        Args:
            source_view_id: 源视图ID
            start_point: 测量起点
            end_point: 测量终点
            distance: 测量距离
            unit: 距离单位
        """
        logger.debug(f"[SyncManager.sync_measurement] 同步测量: "
                    f"source={source_view_id}, distance={distance:.2f}{unit}")
        
        if self._sync_lock or SyncMode.MEASUREMENT not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                # 转换坐标到目标视图
                target_start = self._convert_position_between_views(
                    source_view_id, target_view_id, start_point
                )
                target_end = self._convert_position_between_views(
                    source_view_id, target_view_id, end_point
                )
                
                self._view_states[target_view_id].measurement_synced = True
                self._view_states[target_view_id].measurement_start = target_start
                self._view_states[target_view_id].measurement_end = target_end
                self._view_states[target_view_id].measurement_distance = distance
                self._view_states[target_view_id].measurement_unit = unit
                
                # 应用到目标视图
                self._apply_measurement_to_view(target_view_id, target_start, target_end, distance, unit)
                
                logger.debug(f"[SyncManager.sync_measurement] 测量同步完成: "
                           f"{source_view_id} -> {target_view_id}")
                self.measurement_synced.emit(source_view_id, target_view_id, 
                                           target_start, target_end, distance)
            
        except Exception as e:
            logger.error(f"[SyncManager.sync_measurement] 测量同步失败: {e}", exc_info=True)
        finally:
            self._sync_lock = False
    
    def _get_sync_targets(self, source_view_id: str) -> Set[str]:
        """获取同步目标视图
        
        Args:
            source_view_id: 源视图ID
            
        Returns:
            目标视图ID集合
        """
        all_view_ids = set(self._series_manager.get_all_view_ids())
        
        if self._sync_group == SyncGroup.ALL_VIEWS:
            targets = all_view_ids - {source_view_id}
        
        elif self._sync_group == SyncGroup.SAME_PATIENT:
            targets = self._get_views_by_criteria(source_view_id, 'patient_id') - {source_view_id}
        
        elif self._sync_group == SyncGroup.SAME_STUDY:
            targets = self._get_views_by_criteria(source_view_id, 'study_instance_uid') - {source_view_id}
        
        elif self._sync_group == SyncGroup.SAME_MODALITY:
            targets = self._get_views_by_criteria(source_view_id, 'modality') - {source_view_id}
        
        elif self._sync_group == SyncGroup.CUSTOM:
            targets = set()
            for group_views in self._custom_groups.values():
                if source_view_id in group_views:
                    targets.update(group_views - {source_view_id})
        
        else:
            targets = set()
        
        logger.debug(f"[SyncManager._get_sync_targets] 获取同步目标: "
                    f"source={source_view_id}, targets={len(targets)}个")
        
        return targets
    
    def _get_views_by_criteria(self, source_view_id: str, criteria: str) -> Set[str]:
        """根据条件获取视图集合
        
        Args:
            source_view_id: 源视图ID
            criteria: 筛选条件 ('patient_id', 'study_instance_uid', 'modality')
            
        Returns:
            符合条件的视图ID集合
        """
        try:
            # 获取源视图的序列信息
            source_binding = self._series_manager.get_view_binding(source_view_id)
            if not source_binding or not source_binding.series_id:
                return set()
            
            source_series = self._series_manager.get_series_info(source_binding.series_id)
            if not source_series:
                return set()
            
            # 获取源视图的条件值
            if criteria == 'patient_id':
                source_value = source_series.patient_id
            elif criteria == 'study_instance_uid':
                source_value = source_series.study_instance_uid
            elif criteria == 'modality':
                source_value = source_series.modality
            else:
                return set()
            
            if not self._is_meaningful_identifier(source_value):
                return set()
            
            # 查找具有相同条件值的视图
            matching_views = set()
            for view_id in self._series_manager.get_all_view_ids():
                binding = self._series_manager.get_view_binding(view_id)
                if not binding or not binding.series_id:
                    continue
                
                series_info = self._series_manager.get_series_info(binding.series_id)
                if not series_info:
                    continue
                
                # 比较条件值
                if criteria == 'patient_id' and self._is_meaningful_identifier(series_info.patient_id) and series_info.patient_id == source_value:
                    matching_views.add(view_id)
                elif criteria == 'study_instance_uid' and self._is_meaningful_identifier(series_info.study_instance_uid) and series_info.study_instance_uid == source_value:
                    matching_views.add(view_id)
                elif criteria == 'modality' and self._is_meaningful_identifier(series_info.modality) and series_info.modality == source_value:
                    matching_views.add(view_id)
            
            return matching_views
            
        except Exception as e:
            logger.error(f"[SyncManager._get_views_by_criteria] 获取视图失败: {e}", exc_info=True)
            return set()
    
    def _apply_window_level_to_view(self, view_id: str, window_width: float, window_level: float) -> None:
        """应用窗宽窗位到视图"""
        try:
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                image_model = self._series_manager.get_series_model(binding.series_id)
                if image_model:
                    viewer = self._get_image_viewer(view_id)
                    if viewer is not None and getattr(viewer, "model", None) is image_model:
                        viewer.set_view_window(window_width, window_level, emit=True)
                    else:
                        # Compatibility for headless integrations that have no pane.
                        image_model.set_window(window_width, window_level)
                    logger.debug(f"[SyncManager._apply_window_level_to_view] "
                               f"窗宽窗位应用成功: {view_id}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_window_level_to_view] 应用窗宽窗位失败: {e}")
    
    def _apply_slice_to_view(self, view_id: str, slice_index: int) -> None:
        """应用切片到视图"""
        try:
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                image_model = self._series_manager.get_series_model(binding.series_id)
                if image_model:
                    max_slice = image_model.get_slice_count() - 1
                    valid_index = max(0, min(slice_index, max_slice))
                    viewer = self._get_image_viewer(view_id)
                    if viewer is not None and getattr(viewer, "model", None) is image_model:
                        viewer.set_view_slice(valid_index, emit=True)
                    else:
                        # Compatibility for headless integrations that have no pane.
                        image_model.set_current_slice(valid_index)
                    logger.debug(f"[SyncManager._apply_slice_to_view] "
                               f"切片应用成功: {view_id}, slice={valid_index}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_slice_to_view] 应用切片失败: {e}")
    
    def _apply_zoom_pan_to_view(
        self,
        view_id: str,
        zoom_factor: float,
        center_scene: Optional[QPointF],
        *,
        sync_zoom: bool,
        sync_pan: bool,
    ) -> None:
        """应用缩放平移到视图"""
        try:
            viewer = self._get_image_viewer(view_id)
            if viewer:
                if hasattr(viewer, 'set_synced_view_state'):
                    viewer.set_synced_view_state(
                        zoom_factor,
                        center_scene,
                        sync_zoom=sync_zoom,
                        sync_pan=sync_pan,
                    )
                else:
                    if sync_zoom:
                        current = max(1e-6, abs(viewer.transform().determinant()) ** 0.5)
                        viewer.scale(zoom_factor / current, zoom_factor / current)
                    if sync_pan and center_scene is not None:
                        viewer.centerOn(center_scene)
                logger.debug(f"[SyncManager._apply_zoom_pan_to_view] "
                           f"缩放平移应用成功: {view_id}, zoom={zoom_factor:.2f}")
            else:
                logger.debug(f"[SyncManager._apply_zoom_pan_to_view] "
                           f"未找到视图的ImageViewer: {view_id}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_zoom_pan_to_view] 应用缩放平移失败: {e}")
    
    def _apply_roi_to_view(self, view_id: str, roi_data: Dict) -> None:
        """应用ROI到视图"""
        try:
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                image_model = self._series_manager.get_series_model(binding.series_id)
                if image_model:
                    # 创建ROI对象并添加到模型
                    roi = self._create_roi_from_data(roi_data)
                    if roi:
                        # 检查是否已存在相同ID的ROI，如果存在则跳过
                        existing_roi = image_model.get_roi_by_id(roi.id)
                        if not existing_roi:
                            image_model.add_roi(roi)
                            logger.debug(f"[SyncManager._apply_roi_to_view] "
                                       f"ROI应用成功: {view_id}, roi_id={roi.id}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_roi_to_view] 应用ROI失败: {e}")
    
    def _apply_measurement_to_view(self, view_id: str, start_point: QPointF, 
                                  end_point: QPointF, distance: float, unit: str) -> None:
        """应用测量工具到视图"""
        try:
            # 这里需要与ViewFrame或ImageViewer协作
            # 通过信号通知视图设置测量线
            logger.debug(f"[SyncManager._apply_measurement_to_view] "
                       f"测量工具状态已记录: {view_id}, distance={distance:.2f}{unit}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_measurement_to_view] 应用测量工具失败: {e}")
    
    def _create_roi_from_data(self, roi_data: Dict):
        """从数据字典创建ROI对象"""
        try:
            from medimager.core.roi import EllipseROI, CircleROI, RectangleROI, ROIShape
            
            roi_type = roi_data.get('type')
            slice_index = roi_data.get('slice_index', 0)
            
            if roi_type == ROIShape.CIRCLE.value:
                return CircleROI(
                    center=tuple(roi_data.get('center', (0, 0))),
                    radius=roi_data.get('radius', 10),
                    slice_index=slice_index
                )
            elif roi_type == ROIShape.ELLIPSE.value:
                return EllipseROI(
                    center=tuple(roi_data.get('center', (0, 0))),
                    radius_x=roi_data.get('radius_x', 10),
                    radius_y=roi_data.get('radius_y', 10),
                    slice_index=slice_index
                )
            elif roi_type == ROIShape.RECTANGLE.value:
                return RectangleROI(
                    top_left=tuple(roi_data.get('top_left', (0, 0))),
                    bottom_right=tuple(roi_data.get('bottom_right', (10, 10))),
                    slice_index=slice_index
                )
            else:
                logger.warning(f"[SyncManager._create_roi_from_data] 未知ROI类型: {roi_type}")
                return None
                
        except Exception as e:
            logger.error(f"[SyncManager._create_roi_from_data] 创建ROI失败: {e}")
            return None
    
    @staticmethod
    def _is_meaningful_identifier(value: Any) -> bool:
        text = str(value or '').strip()
        return bool(text) and text.lower() not in {'unknown', 'n/a', 'none', 'null'}

    def _get_view_model(self, view_id: str) -> Optional[ImageDataModel]:
        binding = self._series_manager.get_view_binding(view_id)
        if not binding or not binding.series_id:
            return None
        return self._series_manager.get_series_model(binding.series_id)

    def _get_view_series_info(self, view_id: str):
        binding = self._series_manager.get_view_binding(view_id)
        if not binding or not binding.series_id:
            return None
        return self._series_manager.get_series_info(binding.series_id)

    @staticmethod
    def _vector(values: Any, expected: int) -> Optional[Tuple[float, ...]]:
        try:
            result = tuple(float(values[index]) for index in range(expected))
            if all(value == value and abs(value) != float('inf') for value in result):
                return result
        except (TypeError, ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _dot(left: Tuple[float, ...], right: Tuple[float, ...]) -> float:
        return sum(a * b for a, b in zip(left, right))

    @staticmethod
    def _cross(left: Tuple[float, float, float], right: Tuple[float, float, float]) -> Tuple[float, float, float]:
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    @classmethod
    def _normalise(cls, vector: Tuple[float, float, float]) -> Optional[Tuple[float, float, float]]:
        length = cls._dot(vector, vector) ** 0.5
        if length <= 1e-8:
            return None
        return tuple(value / length for value in vector)

    @staticmethod
    def _functional_group_item(dataset: Any, frame_index: int, sequence_name: str):
        """读取 per-frame/shared functional group 中的首个序列项。"""
        containers = []
        per_frame = getattr(dataset, 'PerFrameFunctionalGroupsSequence', None)
        if per_frame:
            try:
                containers.append(per_frame[min(max(frame_index, 0), len(per_frame) - 1)])
            except (IndexError, TypeError):
                pass
        shared = getattr(dataset, 'SharedFunctionalGroupsSequence', None)
        if shared:
            try:
                containers.append(shared[0])
            except (IndexError, TypeError):
                pass
        for container in containers:
            sequence = getattr(container, sequence_name, None)
            if sequence:
                try:
                    return sequence[0]
                except (IndexError, TypeError):
                    continue
        return None

    def _frame_geometry(self, model: ImageDataModel, slice_index: int) -> Optional[Dict[str, Any]]:
        """返回一帧从像素坐标映射到患者坐标所需的几何信息。"""
        dataset = model.get_dicom_file(slice_index)
        if dataset is None:
            return None
        datasets = getattr(model, 'dicom_files', None) or []
        frame_index = slice_index if len(datasets) == 1 and model.get_slice_count() > 1 else 0

        orientation_item = self._functional_group_item(
            dataset, frame_index, 'PlaneOrientationSequence'
        )
        position_item = self._functional_group_item(
            dataset, frame_index, 'PlanePositionSequence'
        )
        measures_item = self._functional_group_item(
            dataset, frame_index, 'PixelMeasuresSequence'
        )

        orientation = self._vector(
            getattr(orientation_item, 'ImageOrientationPatient', None)
            or getattr(dataset, 'ImageOrientationPatient', None),
            6,
        )
        position = self._vector(
            getattr(position_item, 'ImagePositionPatient', None)
            or getattr(dataset, 'ImagePositionPatient', None),
            3,
        )
        spacing = self._vector(
            getattr(measures_item, 'PixelSpacing', None)
            or getattr(dataset, 'PixelSpacing', None),
            2,
        )
        if not orientation or not position or not spacing or spacing[0] <= 0 or spacing[1] <= 0:
            return None

        column_axis = self._normalise(tuple(orientation[:3]))
        row_axis = self._normalise(tuple(orientation[3:]))
        if not column_axis or not row_axis:
            return None
        normal = self._normalise(self._cross(column_axis, row_axis))
        if not normal:
            return None

        return {
            'origin': position,
            'column_axis': column_axis,
            'row_axis': row_axis,
            'normal': normal,
            'row_spacing': spacing[0],
            'column_spacing': spacing[1],
            'slice_thickness': (
                getattr(measures_item, 'SliceThickness', None)
                or getattr(dataset, 'SliceThickness', None)
            ),
            'spacing_between_slices': (
                getattr(measures_item, 'SpacingBetweenSlices', None)
                or getattr(dataset, 'SpacingBetweenSlices', None)
            ),
            'frame_of_reference_uid': str(getattr(dataset, 'FrameOfReferenceUID', '') or ''),
        }

    def _patients_compatible(self, source_view_id: str, target_view_id: str) -> bool:
        source = self._get_view_series_info(source_view_id)
        target = self._get_view_series_info(target_view_id)
        if not source or not target:
            return False
        source_id, target_id = source.patient_id, target.patient_id
        if self._is_meaningful_identifier(source_id) and self._is_meaningful_identifier(target_id):
            return str(source_id) == str(target_id)
        source_study, target_study = source.study_instance_uid, target.study_instance_uid
        return (
            self._is_meaningful_identifier(source_study)
            and self._is_meaningful_identifier(target_study)
            and str(source_study) == str(target_study)
        )

    @staticmethod
    def _frames_compatible(source: Dict[str, Any], target: Dict[str, Any]) -> bool:
        source_uid = source.get('frame_of_reference_uid')
        target_uid = target.get('frame_of_reference_uid')
        # 不同 model 间只有双方明确声明同一患者坐标系时才允许映射。
        if not source_uid or not target_uid or source_uid != target_uid:
            return False
        return abs(SyncManager._dot(source['normal'], target['normal'])) >= 0.99

    def _find_corresponding_slice(
        self,
        source_view_id: str,
        target_view_id: str,
        source_index: int,
    ) -> Optional[int]:
        source_model = self._get_view_model(source_view_id)
        target_model = self._get_view_model(target_view_id)
        if not source_model or not target_model or target_model.get_slice_count() <= 0:
            return None
        if source_model is target_model:
            return max(0, min(source_index, target_model.get_slice_count() - 1))
        if not self._patients_compatible(source_view_id, target_view_id):
            return None

        source_geometry = self._frame_geometry(source_model, source_index)
        if not source_geometry:
            return None
        source_origin = source_geometry['origin']
        best_index = None
        best_distance = float('inf')
        for target_index in range(target_model.get_slice_count()):
            target_geometry = self._frame_geometry(target_model, target_index)
            if not target_geometry or not self._frames_compatible(source_geometry, target_geometry):
                continue
            delta = tuple(
                source_origin[index] - target_geometry['origin'][index]
                for index in range(3)
            )
            distance = abs(self._dot(delta, target_geometry['normal']))
            if distance < best_distance:
                best_index, best_distance = target_index, distance
        if best_index is None:
            return None
        best_geometry = self._frame_geometry(target_model, best_index)
        if not best_geometry:
            return None
        tolerance = self._slice_plane_tolerance(target_model, best_index, best_geometry)
        return best_index if best_distance <= tolerance else None

    def _slice_plane_tolerance(
        self,
        model: ImageDataModel,
        slice_index: int,
        geometry: Dict[str, Any],
    ) -> float:
        """返回当前切片可接受的半层厚；缺失标签时由相邻层间距推导。"""
        candidates = []
        for key in ('slice_thickness', 'spacing_between_slices'):
            try:
                value = abs(float(geometry.get(key) or 0.0))
            except (TypeError, ValueError):
                value = 0.0
            if value > 1e-6:
                candidates.append(value)

        for neighbour_index in (slice_index - 1, slice_index + 1):
            if not 0 <= neighbour_index < model.get_slice_count():
                continue
            neighbour = self._frame_geometry(model, neighbour_index)
            if not neighbour:
                continue
            if abs(self._dot(geometry['normal'], neighbour['normal'])) < 0.99:
                continue
            delta = tuple(
                neighbour['origin'][axis] - geometry['origin'][axis]
                for axis in range(3)
            )
            distance = abs(self._dot(delta, geometry['normal']))
            if distance > 1e-6:
                candidates.append(distance)

        # 单张二次捕获图像经常没有层厚；此时只接受确实位于平面上的点。
        return max(max(candidates, default=0.0) * 0.5, 1e-3)

    def _plane_intersection_segment(
        self, source_view_id: str, target_view_id: str
    ) -> Optional[Tuple[QPointF, QPointF]]:
        """Clip the source image plane to the target image rectangle."""
        source_model = self._get_view_model(source_view_id)
        target_model = self._get_view_model(target_view_id)
        if not source_model or not target_model or source_model is target_model:
            return None
        if not self._patients_compatible(source_view_id, target_view_id):
            return None
        source_geometry = self._frame_geometry(
            source_model, self._get_view_slice_index(source_view_id, source_model)
        )
        target_geometry = self._frame_geometry(
            target_model, self._get_view_slice_index(target_view_id, target_model)
        )
        if not source_geometry or not target_geometry:
            return None
        source_uid = source_geometry.get('frame_of_reference_uid')
        target_uid = target_geometry.get('frame_of_reference_uid')
        if not source_uid or source_uid != target_uid:
            return None
        if abs(self._dot(source_geometry['normal'], target_geometry['normal'])) >= 0.999:
            return None

        # Target pixel (x, y) maps to origin + x*column + y*row.  Substitution
        # into the source plane equation yields a*x + b*y + c = 0.
        source_normal = source_geometry['normal']
        a = self._dot(source_normal, target_geometry['column_axis']) * target_geometry['column_spacing']
        b = self._dot(source_normal, target_geometry['row_axis']) * target_geometry['row_spacing']
        origin_delta = tuple(
            target_geometry['origin'][axis] - source_geometry['origin'][axis]
            for axis in range(3)
        )
        c = self._dot(source_normal, origin_delta)
        shape = target_model.get_image_shape()
        if not shape or len(shape) < 3:
            return None
        width, height = float(shape[2] - 1), float(shape[1] - 1)
        if width <= 0 or height <= 0:
            return None

        candidates = []
        epsilon = 1e-9
        if abs(b) > epsilon:
            for x in (0.0, width):
                y = -(a * x + c) / b
                if -epsilon <= y <= height + epsilon:
                    candidates.append(QPointF(x, min(height, max(0.0, y))))
        if abs(a) > epsilon:
            for y in (0.0, height):
                x = -(b * y + c) / a
                if -epsilon <= x <= width + epsilon:
                    candidates.append(QPointF(min(width, max(0.0, x)), y))

        unique = []
        for point in candidates:
            if not any(
                abs(point.x() - other.x()) < 1e-5
                and abs(point.y() - other.y()) < 1e-5
                for other in unique
            ):
                unique.append(point)
        if len(unique) < 2:
            return None
        best = max(
            (
                ((left.x() - right.x()) ** 2 + (left.y() - right.y()) ** 2, left, right)
                for index, left in enumerate(unique)
                for right in unique[index + 1:]
            ),
            key=lambda item: item[0],
        )
        return QPointF(best[1]), QPointF(best[2])

    def _convert_position_between_views(
        self,
        source_view_id: str,
        target_view_id: str,
        source_pos: QPointF,
        *,
        require_on_target_plane: bool = False,
    ) -> QPointF:
        """在视图间转换位置坐标
        
        Args:
            source_view_id: 源视图ID
            target_view_id: 目标视图ID
            source_pos: 源位置
            
        Returns:
            目标位置
        """
        try:
            source_model = self._get_view_model(source_view_id)
            target_model = self._get_view_model(target_view_id)
            if not source_model or not target_model:
                return QPointF(-1, -1)
            if source_model is target_model:
                return QPointF(source_pos)
            if not self._patients_compatible(source_view_id, target_view_id):
                return QPointF(-1, -1)

            source_index = self._get_view_slice_index(source_view_id, source_model)
            target_index = self._get_view_slice_index(target_view_id, target_model)
            source_geometry = self._frame_geometry(source_model, source_index)
            target_geometry = self._frame_geometry(target_model, target_index)
            if not source_geometry or not target_geometry:
                return QPointF(-1, -1)
            source_uid = source_geometry.get('frame_of_reference_uid')
            target_uid = target_geometry.get('frame_of_reference_uid')
            if not source_uid or not target_uid or source_uid != target_uid:
                return QPointF(-1, -1)

            origin = source_geometry['origin']
            patient_point = tuple(
                origin[index]
                + source_pos.x() * source_geometry['column_spacing'] * source_geometry['column_axis'][index]
                + source_pos.y() * source_geometry['row_spacing'] * source_geometry['row_axis'][index]
                for index in range(3)
            )
            delta = tuple(
                patient_point[index] - target_geometry['origin'][index]
                for index in range(3)
            )
            if require_on_target_plane:
                plane_distance = abs(self._dot(delta, target_geometry['normal']))
                tolerance = self._slice_plane_tolerance(
                    target_model,
                    target_index,
                    target_geometry,
                )
                if plane_distance > tolerance:
                    return QPointF(-1, -1)
            target_x = self._dot(delta, target_geometry['column_axis']) / target_geometry['column_spacing']
            target_y = self._dot(delta, target_geometry['row_axis']) / target_geometry['row_spacing']

            shape = target_model.get_image_shape()
            if not shape or not (0 <= target_x < shape[2] and 0 <= target_y < shape[1]):
                return QPointF(-1, -1)
            return QPointF(target_x, target_y)
            
        except Exception as e:
            logger.error(f"[SyncManager._convert_position_between_views] 位置转换失败: {e}")
            return QPointF(-1, -1)
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[SyncManager._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")

        # 源或靶序列一旦替换，旧患者空间投影不再属于当前图像。
        self.clear_cross_reference()
        
        # 更新视图状态
        if view_id not in self._view_states:
            self._view_states[view_id] = ViewSyncState(view_id)
        
        self._view_states[view_id].series_id = series_id
        
        # 如果绑定了序列，初始化同步状态
        if series_id:
            image_model = self._series_manager.get_series_model(series_id)
            if image_model:
                self._view_states[view_id].window_width = image_model.window_width
                self._view_states[view_id].window_level = image_model.window_level
                self._view_states[view_id].slice_index = image_model.current_slice_index
                self._view_states[view_id].slice_count = image_model.get_slice_count()
    
    def _on_active_view_changed(self, view_id: str) -> None:
        """处理活动视图变更事件"""
        logger.debug(f"[SyncManager._on_active_view_changed] 活动视图变更: {view_id}")
        
        # 可以在这里添加特定的活动视图同步逻辑
        pass
    
    def _on_layout_changed(self, layout: tuple) -> None:
        """处理布局变更事件"""
        logger.debug(f"[SyncManager._on_layout_changed] 布局变更: {layout}")
        
        # 清理不存在视图的状态
        current_view_ids = set(self._series_manager.get_all_view_ids())
        obsolete_view_ids = set(self._view_states.keys()) - current_view_ids
        
        for view_id in obsolete_view_ids:
            del self._view_states[view_id]
            logger.debug(f"[SyncManager._on_layout_changed] 清理视图状态: {view_id}")
    
    # 查询方法
    
    def get_sync_mode(self) -> SyncMode:
        """获取当前同步模式"""
        return self._sync_mode
    
    def get_sync_group(self) -> SyncGroup:
        """获取当前同步分组"""
        return self._sync_group
    
    def get_view_state(self, view_id: str) -> Optional[ViewSyncState]:
        """获取视图同步状态"""
        return self._view_states.get(view_id)
    
    def get_cross_reference_state(self) -> CrossReferenceState:
        """获取交叉参考线状态"""
        return self._cross_reference
    
    def get_custom_groups(self) -> Dict[str, Set[str]]:
        """获取自定义分组"""
        return self._custom_groups.copy()
    
    def is_sync_enabled(self, mode: SyncMode) -> bool:
        """检查指定同步模式是否启用"""
        return mode in self._sync_mode
    
    def get_sync_targets_for_view(self, view_id: str) -> Set[str]:
        """获取指定视图的同步目标"""
        return self._get_sync_targets(view_id)
