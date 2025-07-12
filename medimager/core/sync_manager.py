"""
同步管理器模块

该模块提供多视图间的同步功能，包括窗宽窗位同步、切片同步、
缩放/平移同步、交叉参考线同步等高级功能。
"""

from typing import Dict, List, Optional, Set, Tuple
from enum import Enum, Flag
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal, QPointF, QRectF
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
    ZOOM_PAN = 4            # 缩放平移同步
    CROSS_REFERENCE = 8     # 交叉参考线同步
    
    # 组合模式
    BASIC = WINDOW_LEVEL | SLICE
    ADVANCED = BASIC | ZOOM_PAN
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
    cross_reference_updated = Signal(str, QPointF)  # view_id, position
    
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
        self._sync_group = SyncGroup.ALL_VIEWS
        
        # 视图同步状态
        self._view_states: Dict[str, ViewSyncState] = {}
        
        # 交叉参考线状态
        self._cross_reference = CrossReferenceState()
        
        # 自定义分组
        self._custom_groups: Dict[str, Set[str]] = {}  # group_name -> view_ids
        
        # 同步锁，防止递归同步
        self._sync_lock = False
        
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
    
    def set_sync_group(self, group: SyncGroup) -> None:
        """设置同步分组
        
        Args:
            group: 同步分组
        """
        logger.debug(f"[SyncManager.set_sync_group] 设置同步分组: {self._sync_group} -> {group}")
        
        if self._sync_group != group:
            self._sync_group = group
            logger.info(f"[SyncManager.set_sync_group] 同步分组已更新: {group}")
            self.sync_group_changed.emit(group)
    
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
    
    def sync_window_level(self, source_view_id: str, window_width: int, window_level: int) -> None:
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
        
        if self._sync_lock or SyncMode.SLICE not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].slice_index = slice_index
                
                # 应用到图像模型
                self._apply_slice_to_view(target_view_id, slice_index)
                
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
        
        if self._sync_lock or SyncMode.ZOOM_PAN not in self._sync_mode:
            return
        
        try:
            self._sync_lock = True
            
            # 获取目标视图
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 更新视图状态
                if target_view_id not in self._view_states:
                    self._view_states[target_view_id] = ViewSyncState(target_view_id)
                
                self._view_states[target_view_id].zoom_factor = zoom_factor
                self._view_states[target_view_id].pan_offset = QPointF(pan_offset)
                self._view_states[target_view_id].view_transform = QTransform(transform)
                
                # 应用到视图
                self._apply_zoom_pan_to_view(target_view_id, zoom_factor, pan_offset, transform)
                
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
            
            # 通知其他视图更新交叉参考线
            target_views = self._get_sync_targets(source_view_id)
            
            for target_view_id in target_views:
                # 计算目标视图中的对应位置
                target_pos = self._convert_position_between_views(
                    source_view_id, target_view_id, cursor_pos
                )
                
                if target_pos.x() >= 0 and target_pos.y() >= 0:
                    self.cross_reference_updated.emit(target_view_id, target_pos)
                    logger.debug(f"[SyncManager.update_cross_reference] 交叉参考线更新: "
                               f"{source_view_id} -> {target_view_id}")
            
        except Exception as e:
            logger.error(f"[SyncManager.update_cross_reference] 更新交叉参考线失败: {e}", exc_info=True)
    
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
            
            if not source_value:
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
                if criteria == 'patient_id' and series_info.patient_id == source_value:
                    matching_views.add(view_id)
                elif criteria == 'study_instance_uid' and series_info.study_instance_uid == source_value:
                    matching_views.add(view_id)
                elif criteria == 'modality' and series_info.modality == source_value:
                    matching_views.add(view_id)
            
            return matching_views
            
        except Exception as e:
            logger.error(f"[SyncManager._get_views_by_criteria] 获取视图失败: {e}", exc_info=True)
            return set()
    
    def _apply_window_level_to_view(self, view_id: str, window_width: int, window_level: int) -> None:
        """应用窗宽窗位到视图"""
        try:
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                image_model = self._series_manager.get_series_model(binding.series_id)
                if image_model:
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
                    # 确保切片索引在有效范围内
                    max_slice = image_model.get_slice_count() - 1
                    valid_index = max(0, min(slice_index, max_slice))
                    image_model.set_current_slice(valid_index)
                    logger.debug(f"[SyncManager._apply_slice_to_view] "
                               f"切片应用成功: {view_id}, slice={valid_index}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_slice_to_view] 应用切片失败: {e}")
    
    def _apply_zoom_pan_to_view(self, view_id: str, zoom_factor: float, 
                               pan_offset: QPointF, transform: QTransform) -> None:
        """应用缩放平移到视图"""
        try:
            # 这里需要与MultiViewerGrid或ViewFrame协作
            # 由于当前架构限制，暂时记录状态，实际应用需要扩展ViewFrame接口
            logger.debug(f"[SyncManager._apply_zoom_pan_to_view] "
                       f"缩放平移状态已记录: {view_id}")
        except Exception as e:
            logger.error(f"[SyncManager._apply_zoom_pan_to_view] 应用缩放平移失败: {e}")
    
    def _convert_position_between_views(self, source_view_id: str, target_view_id: str, 
                                      source_pos: QPointF) -> QPointF:
        """在视图间转换位置坐标
        
        Args:
            source_view_id: 源视图ID
            target_view_id: 目标视图ID
            source_pos: 源位置
            
        Returns:
            目标位置
        """
        try:
            # 简化实现：假设图像坐标系相同
            # 实际应用中需要根据图像的空间信息进行坐标转换
            return QPointF(source_pos)
            
        except Exception as e:
            logger.error(f"[SyncManager._convert_position_between_views] 位置转换失败: {e}")
            return QPointF(-1, -1)
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[SyncManager._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")
        
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