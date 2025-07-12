"""
序列视图绑定模块

该模块提供序列与视图之间的高级绑定操作和策略，
包括自动分配、智能绑定保持、绑定冲突解决等功能。
"""

from typing import Dict, List, Optional, Tuple, Set
from enum import Enum
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

from medimager.core.multi_series_manager import MultiSeriesManager, ViewPosition, SeriesInfo
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


class BindingStrategy(Enum):
    """绑定策略枚举"""
    AUTO_ASSIGN = "auto_assign"  # 自动分配到可用视图
    PRESERVE_EXISTING = "preserve_existing"  # 保持现有绑定
    REPLACE_OLDEST = "replace_oldest"  # 替换最旧的绑定
    ASK_USER = "ask_user"  # 询问用户


class SortOrder(Enum):
    """排序顺序"""
    SERIES_NUMBER = "series_number"
    ACQUISITION_TIME = "acquisition_time"
    PATIENT_NAME = "patient_name"
    MODALITY = "modality"


@dataclass
class BindingOperation:
    """绑定操作记录"""
    operation_type: str  # "bind", "unbind", "replace"
    view_id: str
    series_id: Optional[str]
    previous_series_id: Optional[str] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        """初始化后处理"""
        import time
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        
        logger.debug(f"[BindingOperation.__post_init__] 创建绑定操作记录: "
                    f"type={self.operation_type}, view_id={self.view_id}, "
                    f"series_id={self.series_id}")


class SeriesViewBindingManager(QObject):
    """序列视图绑定管理器
    
    提供高级的序列视图绑定功能，包括自动分配、智能保持、冲突解决等。
    
    Signals:
        binding_strategy_changed (str): 绑定策略变更时发出
        auto_assignment_completed (int): 自动分配完成时发出，参数为分配的序列数量
        binding_conflict_detected (str, str): 检测到绑定冲突时发出
    """
    
    # 信号定义
    binding_strategy_changed = Signal(str)
    auto_assignment_completed = Signal(int)
    binding_conflict_detected = Signal(str, str)  # view_id, conflicting_series_id
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QObject] = None) -> None:
        """初始化绑定管理器
        
        Args:
            series_manager: 多序列管理器实例
            parent: 父对象
        """
        super().__init__(parent)
        logger.debug("[SeriesViewBindingManager.__init__] 开始初始化绑定管理器")
        
        self._series_manager = series_manager
        self._binding_strategy = BindingStrategy.AUTO_ASSIGN
        self._sort_order = SortOrder.SERIES_NUMBER
        
        # 绑定历史记录
        self._binding_history: List[BindingOperation] = []
        self._max_history_size = 100
        
        # 连接信号
        self._connect_signals()
        
        logger.info("[SeriesViewBindingManager.__init__] 绑定管理器初始化完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[SeriesViewBindingManager._connect_signals] 连接信号槽")
        
        self._series_manager.series_added.connect(self._on_series_added)
        self._series_manager.layout_changed.connect(self._on_layout_changed)
    
    def set_binding_strategy(self, strategy: BindingStrategy) -> None:
        """设置绑定策略
        
        Args:
            strategy: 绑定策略
        """
        logger.debug(f"[SeriesViewBindingManager.set_binding_strategy] "
                    f"设置绑定策略: {self._binding_strategy} -> {strategy}")
        
        if self._binding_strategy != strategy:
            self._binding_strategy = strategy
            logger.info(f"[SeriesViewBindingManager.set_binding_strategy] "
                       f"绑定策略已更新: {strategy}")
            self.binding_strategy_changed.emit(strategy.value)
    
    def set_sort_order(self, order: SortOrder) -> None:
        """设置排序顺序
        
        Args:
            order: 排序顺序
        """
        logger.debug(f"[SeriesViewBindingManager.set_sort_order] "
                    f"设置排序顺序: {self._sort_order} -> {order}")
        
        self._sort_order = order
        logger.info(f"[SeriesViewBindingManager.set_sort_order] 排序顺序已更新: {order}")
    
    def auto_assign_series_to_views(self, series_ids: Optional[List[str]] = None) -> int:
        """自动将序列分配到视图
        
        Args:
            series_ids: 要分配的序列ID列表，None表示所有未绑定的序列
            
        Returns:
            成功分配的序列数量
        """
        logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                   f"开始自动分配序列: series_ids={series_ids}")
        logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                   f"当前绑定策略: {self._binding_strategy}")
        
        try:
            # 获取要分配的序列列表
            if series_ids is None:
                series_ids = self._get_unbound_series()
            
            logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                       f"找到未绑定序列: {len(series_ids)}个 - {series_ids}")
            
            if not series_ids:
                logger.info("[SeriesViewBindingManager.auto_assign_series_to_views] "
                           "没有未绑定的序列，跳过自动分配")
                return 0
            
            # 按照指定顺序排序
            sorted_series = self._sort_series(series_ids)
            logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                       f"排序后的序列: {sorted_series}")
            
            # 获取可用视图
            available_views = self._get_available_views()
            logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                       f"找到可用视图: {len(available_views)}个 - {available_views}")
            
            if not available_views:
                logger.info("[SeriesViewBindingManager.auto_assign_series_to_views] "
                           "没有可用视图，跳过自动分配")
                return 0
            
            assigned_count = 0
            for i, series_id in enumerate(sorted_series):
                if i >= len(available_views):
                    logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                               f"可用视图已用完，停止分配")
                    break
                
                view_id = available_views[i]
                logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                           f"尝试绑定: series_id={series_id} -> view_id={view_id}")
                
                if self._series_manager.bind_series_to_view(view_id, series_id):
                    assigned_count += 1
                    self._record_binding_operation("bind", view_id, series_id)
                    logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                               f"自动分配成功: series_id={series_id}, view_id={view_id}")
                else:
                    logger.warning(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                                  f"绑定失败: series_id={series_id}, view_id={view_id}")
            
            logger.info(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                       f"自动分配完成: 成功分配{assigned_count}个序列")
            
            if assigned_count > 0:
                self.auto_assignment_completed.emit(assigned_count)
            
            return assigned_count
            
        except Exception as e:
            logger.error(f"[SeriesViewBindingManager.auto_assign_series_to_views] "
                        f"自动分配失败: {e}", exc_info=True)
            return 0
    
    def smart_bind_series(self, series_id: str, preferred_position: Optional[ViewPosition] = None) -> bool:
        """智能绑定序列到视图
        
        根据当前绑定策略和用户偏好智能选择目标视图。
        
        Args:
            series_id: 序列ID
            preferred_position: 首选视图位置
            
        Returns:
            是否成功绑定
        """
        logger.debug(f"[SeriesViewBindingManager.smart_bind_series] "
                    f"智能绑定序列: series_id={series_id}, "
                    f"preferred_position={preferred_position}")
        
        try:
            # 检查序列是否存在
            if not self._series_manager.get_series_info(series_id):
                logger.error(f"[SeriesViewBindingManager.smart_bind_series] "
                           f"序列不存在: {series_id}")
                return False
            
            # 查找目标视图
            target_view_id = self._find_target_view(series_id, preferred_position)
            
            if not target_view_id:
                logger.warning(f"[SeriesViewBindingManager.smart_bind_series] "
                             f"未找到合适的目标视图: series_id={series_id}")
                return False
            
            # 执行绑定
            success = self._execute_binding(target_view_id, series_id)
            
            if success:
                logger.info(f"[SeriesViewBindingManager.smart_bind_series] "
                           f"智能绑定成功: series_id={series_id}, view_id={target_view_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"[SeriesViewBindingManager.smart_bind_series] "
                        f"智能绑定失败: {e}", exc_info=True)
            return False
    
    def preserve_bindings_on_layout_change(self, old_layout: Tuple[int, int], 
                                          new_layout: Tuple[int, int]) -> Dict[str, str]:
        """在布局变更时保持绑定关系
        
        Args:
            old_layout: 旧布局 (rows, cols)
            new_layout: 新布局 (rows, cols)
            
        Returns:
            保持的绑定关系字典 {series_id: new_view_id}
        """
        logger.debug(f"[SeriesViewBindingManager.preserve_bindings_on_layout_change] "
                    f"保持绑定关系: {old_layout} -> {new_layout}")
        
        try:
            # 获取当前所有绑定
            current_bindings = {}
            for view_id in self._series_manager.get_all_view_ids():
                binding = self._series_manager.get_view_binding(view_id)
                if binding and binding.series_id:
                    current_bindings[binding.position] = binding.series_id
            
            logger.debug(f"[SeriesViewBindingManager.preserve_bindings_on_layout_change] "
                        f"当前绑定: {len(current_bindings)}个")
            
            # 在布局变更后重新应用绑定
            # 注意：这个方法会在 MultiSeriesManager.set_layout 之后被调用
            preserved_bindings = {}
            
            for view_id in self._series_manager.get_all_view_ids():
                binding = self._series_manager.get_view_binding(view_id)
                if binding and binding.series_id:
                    preserved_bindings[binding.series_id] = view_id
            
            logger.info(f"[SeriesViewBindingManager.preserve_bindings_on_layout_change] "
                       f"绑定保持完成: 保持{len(preserved_bindings)}个绑定")
            
            return preserved_bindings
            
        except Exception as e:
            logger.error(f"[SeriesViewBindingManager.preserve_bindings_on_layout_change] "
                        f"绑定保持失败: {e}", exc_info=True)
            return {}
    
    def _get_unbound_series(self) -> List[str]:
        """获取未绑定的序列列表（仅包含已加载的序列）"""
        logger.debug("[SeriesViewBindingManager._get_unbound_series] 获取未绑定序列")
        
        # 获取所有已加载的序列
        all_series = set()
        for series_id in self._series_manager.get_all_series_ids():
            series_info = self._series_manager.get_series_info(series_id)
            if series_info and series_info.is_loaded:
                all_series.add(series_id)
        
        # 获取已绑定的序列
        bound_series = set()
        for view_id in self._series_manager.get_all_view_ids():
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                bound_series.add(binding.series_id)
        
        # 计算未绑定的已加载序列
        unbound = list(all_series - bound_series)
        logger.debug(f"[SeriesViewBindingManager._get_unbound_series] "
                    f"未绑定序列: {len(unbound)}个（仅已加载）, 总序列: {len(self._series_manager.get_all_series_ids())}个")
        
        return unbound
    
    def _get_available_views(self) -> List[str]:
        """获取可用视图列表"""
        logger.info("[SeriesViewBindingManager._get_available_views] 获取可用视图")
        
        all_view_ids = self._series_manager.get_all_view_ids()
        logger.info(f"[SeriesViewBindingManager._get_available_views] "
                   f"总视图数: {len(all_view_ids)} - {all_view_ids}")
        
        available = []
        for view_id in all_view_ids:
            binding = self._series_manager.get_view_binding(view_id)
            if binding:
                if not binding.series_id:
                    available.append(view_id)
                    logger.info(f"[SeriesViewBindingManager._get_available_views] "
                               f"可用视图: {view_id}")
                else:
                    logger.info(f"[SeriesViewBindingManager._get_available_views] "
                               f"已绑定视图: {view_id} -> {binding.series_id}")
            else:
                logger.warning(f"[SeriesViewBindingManager._get_available_views] "
                              f"视图绑定信息为空: {view_id}")
        
        logger.info(f"[SeriesViewBindingManager._get_available_views] "
                   f"最终可用视图: {len(available)}个 - {available}")
        
        return available
    
    def _sort_series(self, series_ids: List[str]) -> List[str]:
        """按指定顺序排序序列"""
        logger.debug(f"[SeriesViewBindingManager._sort_series] "
                    f"排序序列: 数量={len(series_ids)}, 顺序={self._sort_order}")
        
        try:
            def get_sort_key(series_id: str):
                info = self._series_manager.get_series_info(series_id)
                if not info:
                    return ""
                
                if self._sort_order == SortOrder.SERIES_NUMBER:
                    return info.series_number or "0"
                elif self._sort_order == SortOrder.ACQUISITION_TIME:
                    return info.acquisition_time or ""
                elif self._sort_order == SortOrder.PATIENT_NAME:
                    return info.patient_name or ""
                elif self._sort_order == SortOrder.MODALITY:
                    return info.modality or ""
                return ""
            
            sorted_series = sorted(series_ids, key=get_sort_key)
            logger.debug(f"[SeriesViewBindingManager._sort_series] 排序完成")
            
            return sorted_series
            
        except Exception as e:
            logger.error(f"[SeriesViewBindingManager._sort_series] "
                        f"排序失败: {e}", exc_info=True)
            return series_ids
    
    def _find_target_view(self, series_id: str, preferred_position: Optional[ViewPosition]) -> Optional[str]:
        """查找目标视图"""
        logger.debug(f"[SeriesViewBindingManager._find_target_view] "
                    f"查找目标视图: series_id={series_id}, preferred_position={preferred_position}")
        
        # 首先尝试首选位置
        if preferred_position:
            for view_id in self._series_manager.get_all_view_ids():
                binding = self._series_manager.get_view_binding(view_id)
                if binding and binding.position == preferred_position:
                    if not binding.series_id:
                        logger.debug(f"[SeriesViewBindingManager._find_target_view] "
                                   f"找到首选位置的空视图: {view_id}")
                        return view_id
                    elif self._binding_strategy == BindingStrategy.REPLACE_OLDEST:
                        logger.debug(f"[SeriesViewBindingManager._find_target_view] "
                                   f"使用替换策略选择首选位置: {view_id}")
                        return view_id
        
        # 查找任何可用视图
        available_views = self._get_available_views()
        if available_views:
            target = available_views[0]
            logger.debug(f"[SeriesViewBindingManager._find_target_view] "
                       f"选择第一个可用视图: {target}")
            return target
        
        # 根据策略处理无可用视图的情况
        if self._binding_strategy == BindingStrategy.REPLACE_OLDEST:
            return self._find_oldest_binding_view()
        
        logger.debug("[SeriesViewBindingManager._find_target_view] 未找到目标视图")
        return None
    
    def _find_oldest_binding_view(self) -> Optional[str]:
        """查找最旧绑定的视图"""
        logger.debug("[SeriesViewBindingManager._find_oldest_binding_view] 查找最旧绑定视图")
        
        # 简化实现：返回第一个有绑定的视图
        for view_id in self._series_manager.get_all_view_ids():
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                logger.debug(f"[SeriesViewBindingManager._find_oldest_binding_view] "
                           f"选择视图进行替换: {view_id}")
                return view_id
        
        return None
    
    def _execute_binding(self, view_id: str, series_id: str) -> bool:
        """执行绑定操作"""
        logger.debug(f"[SeriesViewBindingManager._execute_binding] "
                    f"执行绑定: view_id={view_id}, series_id={series_id}")
        
        try:
            # 获取当前绑定
            current_binding = self._series_manager.get_view_binding(view_id)
            previous_series_id = current_binding.series_id if current_binding else None
            
            # 执行绑定
            success = self._series_manager.bind_series_to_view(view_id, series_id)
            
            if success:
                # 记录操作
                operation_type = "replace" if previous_series_id else "bind"
                self._record_binding_operation(operation_type, view_id, series_id, previous_series_id)
                
                logger.debug(f"[SeriesViewBindingManager._execute_binding] "
                           f"绑定执行成功: {operation_type}")
            
            return success
            
        except Exception as e:
            logger.error(f"[SeriesViewBindingManager._execute_binding] "
                        f"绑定执行失败: {e}", exc_info=True)
            return False
    
    def _record_binding_operation(self, operation_type: str, view_id: str, 
                                series_id: Optional[str], 
                                previous_series_id: Optional[str] = None) -> None:
        """记录绑定操作"""
        operation = BindingOperation(
            operation_type=operation_type,
            view_id=view_id,
            series_id=series_id,
            previous_series_id=previous_series_id
        )
        
        self._binding_history.append(operation)
        
        # 限制历史记录大小
        if len(self._binding_history) > self._max_history_size:
            self._binding_history.pop(0)
    
    def _on_series_added(self, series_id: str) -> None:
        """处理序列添加事件"""
        logger.debug(f"[SeriesViewBindingManager._on_series_added] 处理序列添加: {series_id}")
        
        # 不在序列添加时自动分配，让用户手动控制
        # 如果需要自动分配，用户可以点击"自动分配"按钮
        logger.debug(f"[SeriesViewBindingManager._on_series_added] 跳过自动分配，等待用户手动操作")
    
    def _on_layout_changed(self, layout: Tuple[int, int]) -> None:
        """处理布局变更事件"""
        logger.debug(f"[SeriesViewBindingManager._on_layout_changed] 处理布局变更: {layout}")
        
        # 布局变更后的绑定已经由 MultiSeriesManager 处理
        # 这里可以添加额外的逻辑，如通知用户等
        pass
    
    # 查询方法
    
    def get_binding_history(self) -> List[BindingOperation]:
        """获取绑定历史记录"""
        return self._binding_history.copy()
    
    def get_binding_strategy(self) -> BindingStrategy:
        """获取当前绑定策略"""
        return self._binding_strategy
    
    def get_sort_order(self) -> SortOrder:
        """获取当前排序顺序"""
        return self._sort_order 
    
    def get_first_bound_view(self) -> Optional[str]:
        """获取第一个有绑定的视图ID
        
        Returns:
            第一个有绑定的视图ID，如果没有则返回None
        """
        logger.debug("[SeriesViewBindingManager.get_first_bound_view] 查找第一个有绑定的视图")
        
        for view_id in self._series_manager.get_all_view_ids():
            binding = self._series_manager.get_view_binding(view_id)
            if binding and binding.series_id:
                logger.debug(f"[SeriesViewBindingManager.get_first_bound_view] 找到第一个有绑定的视图: {view_id}")
                return view_id
        
        logger.debug("[SeriesViewBindingManager.get_first_bound_view] 没有找到有绑定的视图")
        return None 