"""
多序列管理器模块

负责管理多个DICOM序列的数据、绑定关系和布局状态。
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from PySide6.QtCore import QObject, Signal

from medimager.core.image_data_model import ImageDataModel
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


class ViewPosition(Enum):
    """视图位置枚举"""
    TOP_LEFT = (0, 0)
    TOP_CENTER = (0, 1)
    TOP_RIGHT = (0, 2)
    TOP_FAR_RIGHT = (0, 3)
    MIDDLE_LEFT = (1, 0)
    MIDDLE_CENTER = (1, 1)
    MIDDLE_RIGHT = (1, 2)
    MIDDLE_FAR_RIGHT = (1, 3)
    BOTTOM_LEFT = (2, 0)
    BOTTOM_CENTER = (2, 1)
    BOTTOM_RIGHT = (2, 2)
    BOTTOM_FAR_RIGHT = (2, 3)


@dataclass
class SeriesInfo:
    """序列信息数据类"""
    series_id: str
    patient_name: str = ""
    patient_id: str = ""
    study_description: str = ""
    series_description: str = ""
    modality: str = ""
    acquisition_date: str = ""
    acquisition_time: str = ""
    slice_count: int = 0
    series_number: str = ""
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    
    # 运行时状态
    is_loaded: bool = False
    file_paths: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """数据类初始化后的处理"""
        logger.debug(f"[SeriesInfo.__post_init__] 创建序列信息: series_id={self.series_id}, "
                    f"patient_name={self.patient_name}, modality={self.modality}")


@dataclass
class ViewBinding:
    """视图绑定信息"""
    view_id: str
    position: ViewPosition
    series_id: Optional[str] = None
    is_active: bool = False
    
    def __post_init__(self):
        """数据类初始化后的处理"""
        logger.debug(f"[ViewBinding.__post_init__] 创建视图绑定: view_id={self.view_id}, "
                    f"position={self.position}, series_id={self.series_id}")


class MultiSeriesManager(QObject):
    """多序列管理器
    
    负责管理所有已加载的DICOM序列数据，处理序列与视图的绑定关系，
    并提供统一的接口来操作序列数据。
    
    Signals:
        series_added (str): 新序列添加时发出，参数为序列ID
        series_removed (str): 序列移除时发出，参数为序列ID
        series_loaded (str): 序列加载完成时发出，参数为序列ID
        binding_changed (str, str): 绑定关系变化时发出，参数为视图ID和序列ID
        active_view_changed (str): 活动视图变化时发出，参数为视图ID
        layout_changed (tuple): 布局变化时发出，参数为(行数, 列数)
    """
    
    # 信号定义
    series_added = Signal(str)  # series_id
    series_removed = Signal(str)  # series_id
    series_loaded = Signal(str)  # series_id
    binding_changed = Signal(str, str)  # view_id, series_id
    active_view_changed = Signal(str)  # view_id
    layout_changed = Signal(tuple)  # (rows, cols)
    
    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化多序列管理器
        
        Args:
            parent: 父对象
        """
        super().__init__(parent)
        logger.debug("[MultiSeriesManager.__init__] 开始初始化多序列管理器")
        
        # 序列数据存储
        self._series_info: Dict[str, SeriesInfo] = {}
        self._series_models: Dict[str, ImageDataModel] = {}
        
        # 视图绑定管理
        self._view_bindings: Dict[str, ViewBinding] = {}
        self._series_to_views: Dict[str, Set[str]] = {}  # 一个序列可能绑定多个视图
        
        # 布局状态
        self._current_layout: Tuple[int, int] = (1, 1)  # (rows, cols)
        self._active_view_id: Optional[str] = None
        
        # 生成默认视图
        self._initialize_default_views()
        
        logger.info("[MultiSeriesManager.__init__] 多序列管理器初始化完成")
    
    def _initialize_default_views(self) -> None:
        """初始化默认视图配置"""
        logger.debug("[MultiSeriesManager._initialize_default_views] 开始初始化默认视图")
        
        # 创建默认的1x1布局视图，使用可预测的ID
        default_view_id = "view_0_0"
        default_binding = ViewBinding(
            view_id=default_view_id,
            position=ViewPosition.TOP_LEFT,
            is_active=True
        )
        
        self._view_bindings[default_view_id] = default_binding
        self._active_view_id = default_view_id
        
        logger.debug(f"[MultiSeriesManager._initialize_default_views] 创建默认视图: {default_view_id}")
        logger.info("[MultiSeriesManager._initialize_default_views] 默认视图初始化完成")
    
    def add_series(self, series_info: SeriesInfo) -> str:
        """添加新序列
        
        Args:
            series_info: 序列信息
            
        Returns:
            序列ID
        """
        logger.debug(f"[MultiSeriesManager.add_series] 开始添加序列: "
                    f"patient_name={series_info.patient_name}, "
                    f"series_description={series_info.series_description}")
        
        try:
            series_id = series_info.series_id
            
            if series_id in self._series_info:
                logger.warning(f"[MultiSeriesManager.add_series] 序列已存在: {series_id}")
                return series_id
            
            # 存储序列信息
            self._series_info[series_id] = series_info
            self._series_to_views[series_id] = set()
            
            logger.info(f"[MultiSeriesManager.add_series] 序列添加成功: {series_id}")
            self.series_added.emit(series_id)
            
            return series_id
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.add_series] 添加序列失败: {e}", exc_info=True)
            raise
    
    def remove_series(self, series_id: str) -> bool:
        """移除序列
        
        Args:
            series_id: 序列ID
            
        Returns:
            是否成功移除
        """
        logger.debug(f"[MultiSeriesManager.remove_series] 开始移除序列: {series_id}")
        
        try:
            if series_id not in self._series_info:
                logger.warning(f"[MultiSeriesManager.remove_series] 序列不存在: {series_id}")
                return False
            
            # 解除所有视图绑定
            bound_views = self._series_to_views.get(series_id, set()).copy()
            for view_id in bound_views:
                self.unbind_series_from_view(view_id)
            
            # 移除序列数据
            del self._series_info[series_id]
            if series_id in self._series_models:
                del self._series_models[series_id]
            if series_id in self._series_to_views:
                del self._series_to_views[series_id]
            
            logger.info(f"[MultiSeriesManager.remove_series] 序列移除成功: {series_id}")
            self.series_removed.emit(series_id)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.remove_series] 移除序列失败: {e}", exc_info=True)
            return False
    
    def load_series_data(self, series_id: str, image_model: ImageDataModel) -> bool:
        """加载序列数据
        
        Args:
            series_id: 序列ID
            image_model: 图像数据模型
            
        Returns:
            是否成功加载
        """
        logger.debug(f"[MultiSeriesManager.load_series_data] 开始加载序列数据: {series_id}")
        
        try:
            if series_id not in self._series_info:
                logger.error(f"[MultiSeriesManager.load_series_data] 序列不存在: {series_id}")
                return False
            
            # 存储数据模型
            self._series_models[series_id] = image_model
            
            # 更新序列信息
            series_info = self._series_info[series_id]
            series_info.is_loaded = True
            
            logger.info(f"[MultiSeriesManager.load_series_data] 序列数据加载完成: {series_id}")
            self.series_loaded.emit(series_id)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.load_series_data] 加载序列数据失败: {e}", exc_info=True)
            return False
    
    def bind_series_to_view(self, view_id: str, series_id: str) -> bool:
        """将序列绑定到视图
        
        Args:
            view_id: 视图ID
            series_id: 序列ID
            
        Returns:
            是否成功绑定
        """
        logger.debug(f"[MultiSeriesManager.bind_series_to_view] 开始绑定: "
                    f"view_id={view_id}, series_id={series_id}")
        
        try:
            if view_id not in self._view_bindings:
                logger.error(f"[MultiSeriesManager.bind_series_to_view] 视图不存在: {view_id}")
                return False
                
            if series_id not in self._series_info:
                logger.error(f"[MultiSeriesManager.bind_series_to_view] 序列不存在: {series_id}")
                return False
            
            # 解除视图的原有绑定
            old_binding = self._view_bindings[view_id]
            if old_binding.series_id:
                old_series_id = old_binding.series_id
                self._series_to_views[old_series_id].discard(view_id)
                logger.debug(f"[MultiSeriesManager.bind_series_to_view] 解除原绑定: "
                           f"view_id={view_id}, old_series_id={old_series_id}")
            
            # 建立新绑定
            old_binding.series_id = series_id
            self._series_to_views[series_id].add(view_id)
            
            # 清理序列模型中的ROI数据，确保每次绑定都是干净的状态
            series_model = self._series_models.get(series_id)
            if series_model and hasattr(series_model, 'clear_all_rois'):
                series_model.clear_all_rois()
                logger.debug(f"[MultiSeriesManager.bind_series_to_view] 清理序列ROI数据: {series_id}")
            
            logger.info(f"[MultiSeriesManager.bind_series_to_view] 绑定成功: "
                       f"view_id={view_id}, series_id={series_id}")
            self.binding_changed.emit(view_id, series_id)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.bind_series_to_view] 绑定失败: {e}", exc_info=True)
            return False
    
    def unbind_series_from_view(self, view_id: str) -> bool:
        """解除视图的序列绑定
        
        Args:
            view_id: 视图ID
            
        Returns:
            是否成功解除绑定
        """
        logger.debug(f"[MultiSeriesManager.unbind_series_from_view] 开始解除绑定: view_id={view_id}")
        
        try:
            if view_id not in self._view_bindings:
                logger.warning(f"[MultiSeriesManager.unbind_series_from_view] 视图不存在: {view_id}")
                return False
            
            binding = self._view_bindings[view_id]
            if not binding.series_id:
                logger.debug(f"[MultiSeriesManager.unbind_series_from_view] 视图未绑定序列: {view_id}")
                return True
            
            # 解除绑定
            series_id = binding.series_id
            binding.series_id = None
            if series_id in self._series_to_views:
                self._series_to_views[series_id].discard(view_id)
            
            logger.info(f"[MultiSeriesManager.unbind_series_from_view] 解除绑定成功: "
                       f"view_id={view_id}, series_id={series_id}")
            self.binding_changed.emit(view_id, "")
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.unbind_series_from_view] 解除绑定失败: {e}", exc_info=True)
            return False
    
    def set_layout(self, rows: int, cols: int) -> bool:
        """设置视图布局
        
        Args:
            rows: 行数
            cols: 列数
            
        Returns:
            是否成功设置
        """
        logger.debug(f"[MultiSeriesManager.set_layout] 开始设置布局: rows={rows}, cols={cols}")
        
        try:
            if rows < 1 or rows > 3 or cols < 1 or cols > 4:
                logger.error(f"[MultiSeriesManager.set_layout] 无效的布局参数: rows={rows}, cols={cols}")
                return False
            
            old_layout = self._current_layout
            self._current_layout = (rows, cols)
            
            # 重新配置视图
            self._reconfigure_views(rows, cols)
            
            logger.info(f"[MultiSeriesManager.set_layout] 布局设置成功: "
                       f"{old_layout} -> {self._current_layout}")
            self.layout_changed.emit(self._current_layout)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.set_layout] 设置布局失败: {e}", exc_info=True)
            return False
    
    def _reconfigure_views(self, rows: int, cols: int) -> None:
        """重新配置视图"""
        logger.debug(f"[MultiSeriesManager._reconfigure_views] 开始重新配置视图: rows={rows}, cols={cols}")
        
        # 保存现有绑定
        existing_bindings = {}
        for view_id, binding in self._view_bindings.items():
            if binding.series_id:
                existing_bindings[binding.position] = binding.series_id
        
        # 清空现有视图
        self._view_bindings.clear()
        
        # 创建新视图配置
        positions = [ViewPosition((r, c)) for r in range(rows) for c in range(cols)]
        new_active_view = None
        
        for i, position in enumerate(positions):
            # 使用可预测的视图ID
            view_id = f"view_{position.value[0]}_{position.value[1]}"
            
            # 尝试恢复原有绑定
            series_id = existing_bindings.get(position)
            
            binding = ViewBinding(
                view_id=view_id,
                position=position,
                series_id=series_id,
                is_active=(i == 0)  # 第一个视图设为活动状态
            )
            
            self._view_bindings[view_id] = binding
            
            if i == 0:
                new_active_view = view_id
            
            # 更新序列到视图的映射
            if series_id:
                if series_id not in self._series_to_views:
                    self._series_to_views[series_id] = set()
                self._series_to_views[series_id].add(view_id)
        
        # 更新活动视图
        if new_active_view:
            self._active_view_id = new_active_view
            self.active_view_changed.emit(new_active_view)
        
        logger.debug(f"[MultiSeriesManager._reconfigure_views] 视图重新配置完成: "
                    f"创建了{len(positions)}个视图")
    
    def set_active_view(self, view_id: str) -> bool:
        """设置活动视图
        
        Args:
            view_id: 视图ID
            
        Returns:
            是否成功设置
        """
        logger.debug(f"[MultiSeriesManager.set_active_view] 设置活动视图: {view_id}")
        
        try:
            if view_id not in self._view_bindings:
                logger.error(f"[MultiSeriesManager.set_active_view] 视图不存在: {view_id}")
                return False
            
            # 更新活动状态
            old_active_view = self._active_view_id
            for binding in self._view_bindings.values():
                binding.is_active = (binding.view_id == view_id)
            
            self._active_view_id = view_id
            
            logger.info(f"[MultiSeriesManager.set_active_view] 活动视图变更: "
                       f"{old_active_view} -> {view_id}")
            self.active_view_changed.emit(view_id)
            
            return True
            
        except Exception as e:
            logger.error(f"[MultiSeriesManager.set_active_view] 设置活动视图失败: {e}", exc_info=True)
            return False
    
    # 查询方法
    
    def get_series_info(self, series_id: str) -> Optional[SeriesInfo]:
        """获取序列信息"""
        return self._series_info.get(series_id)
    
    def get_series_model(self, series_id: str) -> Optional[ImageDataModel]:
        """获取序列数据模型"""
        return self._series_models.get(series_id)
    
    def get_view_binding(self, view_id: str) -> Optional[ViewBinding]:
        """获取视图绑定信息"""
        return self._view_bindings.get(view_id)
    
    def get_all_series_ids(self) -> List[str]:
        """获取所有序列ID"""
        return list(self._series_info.keys())
    
    def get_all_view_ids(self) -> List[str]:
        """获取所有视图ID"""
        return list(self._view_bindings.keys())
    
    def get_active_view_id(self) -> Optional[str]:
        """获取活动视图ID"""
        return self._active_view_id
    
    def get_current_layout(self) -> Tuple[int, int]:
        """获取当前布局"""
        return self._current_layout
    
    def get_bound_views_for_series(self, series_id: str) -> Set[str]:
        """获取绑定到指定序列的所有视图ID"""
        return self._series_to_views.get(series_id, set()).copy()
    
    def get_series_count(self) -> int:
        """获取序列总数"""
        return len(self._series_info)
    
    def get_loaded_series_count(self) -> int:
        """获取已加载序列数"""
        return sum(1 for info in self._series_info.values() if info.is_loaded) 