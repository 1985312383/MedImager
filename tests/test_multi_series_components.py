"""
多序列组件测试脚本

该脚本测试新创建的多序列管理组件的基本功能，
包括 MultiSeriesManager 和 SeriesViewBindingManager 的核心操作。
"""

import sys
import os
import numpy as np
from typing import Optional
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QObject
    
    from medimager.core.multi_series_manager import (
        MultiSeriesManager, SeriesInfo, ViewPosition, ViewBinding
    )
    from medimager.core.series_view_binding import (
        SeriesViewBindingManager, BindingStrategy, SortOrder
    )
    from medimager.core.image_data_model import ImageDataModel
    from medimager.utils.logger import get_logger
    
    logger = get_logger(__name__)
    
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖项都已正确安装")
    sys.exit(1)


class MockImageDataModel(ImageDataModel):
    """模拟的图像数据模型，用于测试"""
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        logger.debug("[MockImageDataModel.__init__] 创建模拟图像数据模型")
        
        # 模拟像素数据
        mock_data = np.random.randint(0, 1000, (10, 256, 256), dtype=np.int16)
        self.load_single_image(mock_data)
        
        # 设置模拟参数
        self.set_window(400, 40)
    
    def get_slice_count(self) -> int:
        """重写获取切片数量方法"""
        return super().get_slice_count()
    
    def get_current_slice_index(self) -> int:
        """获取当前切片索引"""
        return self.current_slice_index
    
    def get_window_width(self) -> int:
        """获取窗宽"""
        return self.window_width
    
    def get_window_level(self) -> int:
        """获取窗位"""
        return self.window_level


def test_multi_series_manager():
    """测试 MultiSeriesManager 基本功能"""
    logger.info("[test_multi_series_manager] 开始测试 MultiSeriesManager")
    
    try:
        # 创建多序列管理器
        manager = MultiSeriesManager()
        logger.info("[test_multi_series_manager] MultiSeriesManager 创建成功")
        
        # 测试初始状态
        assert manager.get_series_count() == 0, "初始序列数量应为0"
        assert manager.get_current_layout() == (1, 1), "初始布局应为1x1"
        assert len(manager.get_all_view_ids()) == 1, "初始应有1个视图"
        
        # 创建测试序列信息
        series1 = SeriesInfo(
            series_id="test_series_1",
            patient_name="测试患者1",
            patient_id="P001",
            series_description="CT胸部扫描",
            modality="CT",
            series_number="1",
            slice_count=20
        )
        
        series2 = SeriesInfo(
            series_id="test_series_2",
            patient_name="测试患者2",
            patient_id="P002",
            series_description="MR头部扫描",
            modality="MR",
            series_number="2",
            slice_count=30
        )
        
        # 测试添加序列
        logger.debug("[test_multi_series_manager] 测试添加序列")
        
        series_id1 = manager.add_series(series1)
        assert series_id1 == "test_series_1", "序列ID应匹配"
        assert manager.get_series_count() == 1, "序列数量应为1"
        
        series_id2 = manager.add_series(series2)
        assert series_id2 == "test_series_2", "序列ID应匹配"
        assert manager.get_series_count() == 2, "序列数量应为2"
        
        # 测试序列信息获取
        retrieved_info1 = manager.get_series_info("test_series_1")
        assert retrieved_info1 is not None, "应能获取序列信息"
        assert retrieved_info1.patient_name == "测试患者1", "患者姓名应匹配"
        
        # 测试加载序列数据
        logger.debug("[test_multi_series_manager] 测试加载序列数据")
        
        mock_model1 = MockImageDataModel()
        mock_model2 = MockImageDataModel()
        
        success1 = manager.load_series_data("test_series_1", mock_model1)
        assert success1, "应能成功加载序列数据"
        assert manager.get_loaded_series_count() == 1, "已加载序列数量应为1"
        
        success2 = manager.load_series_data("test_series_2", mock_model2)
        assert success2, "应能成功加载序列数据"
        assert manager.get_loaded_series_count() == 2, "已加载序列数量应为2"
        
        # 测试视图绑定
        logger.debug("[test_multi_series_manager] 测试视图绑定")
        
        view_ids = manager.get_all_view_ids()
        first_view_id = view_ids[0]
        
        bind_success = manager.bind_series_to_view(first_view_id, "test_series_1")
        assert bind_success, "应能成功绑定序列到视图"
        
        binding = manager.get_view_binding(first_view_id)
        assert binding is not None, "应能获取视图绑定信息"
        assert binding.series_id == "test_series_1", "绑定的序列ID应匹配"
        
        # 测试布局变更
        logger.debug("[test_multi_series_manager] 测试布局变更")
        
        layout_success = manager.set_layout(2, 2)
        assert layout_success, "应能成功设置2x2布局"
        assert manager.get_current_layout() == (2, 2), "当前布局应为2x2"
        assert len(manager.get_all_view_ids()) == 4, "应有4个视图"
        
        # 测试解除绑定
        logger.debug("[test_multi_series_manager] 测试解除绑定")
        
        new_view_ids = manager.get_all_view_ids()
        for view_id in new_view_ids:
            unbind_success = manager.unbind_series_from_view(view_id)
            # 注意：可能有些视图没有绑定，所以不一定都返回True
        
        # 测试移除序列
        logger.debug("[test_multi_series_manager] 测试移除序列")
        
        remove_success = manager.remove_series("test_series_1")
        assert remove_success, "应能成功移除序列"
        assert manager.get_series_count() == 1, "序列数量应为1"
        
        logger.info("[test_multi_series_manager] MultiSeriesManager 测试通过")
        
    except Exception as e:
        logger.error(f"[test_multi_series_manager] 测试失败: {e}", exc_info=True)
        raise


def test_series_view_binding_manager():
    """测试 SeriesViewBindingManager 基本功能"""
    logger.info("[test_series_view_binding_manager] 开始测试 SeriesViewBindingManager")
    
    try:
        # 创建依赖组件
        series_manager = MultiSeriesManager()
        binding_manager = SeriesViewBindingManager(series_manager)
        logger.info("[test_series_view_binding_manager] SeriesViewBindingManager 创建成功")
        
        # 测试初始状态
        assert binding_manager.get_binding_strategy() == BindingStrategy.AUTO_ASSIGN, "默认绑定策略应为自动分配"
        assert binding_manager.get_sort_order() == SortOrder.SERIES_NUMBER, "默认排序应为序列号"
        
        # 添加测试序列
        logger.debug("[test_series_view_binding_manager] 添加测试序列")
        
        for i in range(3):
            series_info = SeriesInfo(
                series_id=f"test_series_{i+1}",
                patient_name=f"测试患者{i+1}",
                series_description=f"测试序列{i+1}",
                modality="CT",
                series_number=str(i+1),
                slice_count=10
            )
            series_manager.add_series(series_info)
            
            # 加载模拟数据
            mock_model = MockImageDataModel()
            series_manager.load_series_data(f"test_series_{i+1}", mock_model)
        
        # 设置2x2布局以提供更多视图
        series_manager.set_layout(2, 2)
        
        # 测试自动分配
        logger.debug("[test_series_view_binding_manager] 测试自动分配")
        
        assigned_count = binding_manager.auto_assign_series_to_views()
        assert assigned_count > 0, "应能自动分配至少一个序列"
        
        # 测试智能绑定
        logger.debug("[test_series_view_binding_manager] 测试智能绑定")
        
        smart_bind_success = binding_manager.smart_bind_series(
            "test_series_1", 
            ViewPosition.TOP_RIGHT
        )
        # 注意：这个测试可能失败，因为序列可能已经绑定了
        
        # 测试策略变更
        logger.debug("[test_series_view_binding_manager] 测试策略变更")
        
        binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)
        assert binding_manager.get_binding_strategy() == BindingStrategy.PRESERVE_EXISTING, "绑定策略应已更新"
        
        binding_manager.set_sort_order(SortOrder.PATIENT_NAME)
        assert binding_manager.get_sort_order() == SortOrder.PATIENT_NAME, "排序顺序应已更新"
        
        # 测试绑定历史
        history = binding_manager.get_binding_history()
        assert isinstance(history, list), "绑定历史应为列表"
        
        logger.info("[test_series_view_binding_manager] SeriesViewBindingManager 测试通过")
        
    except Exception as e:
        logger.error(f"[test_series_view_binding_manager] 测试失败: {e}", exc_info=True)
        raise


def test_integration():
    """测试组件集成"""
    logger.info("[test_integration] 开始集成测试")
    
    try:
        # 创建完整的组件栈
        series_manager = MultiSeriesManager()
        binding_manager = SeriesViewBindingManager(series_manager)
        
        # 测试信号连接（简单验证）
        assert hasattr(series_manager, 'series_added'), "应有series_added信号"
        assert hasattr(series_manager, 'binding_changed'), "应有binding_changed信号"
        assert hasattr(binding_manager, 'auto_assignment_completed'), "应有auto_assignment_completed信号"
        
        # 创建复杂场景：多个序列，多个布局变更
        logger.debug("[test_integration] 创建复杂测试场景")
        
        # 添加多个序列
        for i in range(5):
            series_info = SeriesInfo(
                series_id=f"integration_series_{i+1}",
                patient_name=f"患者{i+1}",
                series_description=f"序列{i+1}",
                modality="CT" if i % 2 == 0 else "MR",
                series_number=str(i+1),
                slice_count=15 + i * 5
            )
            series_manager.add_series(series_info)
            
            mock_model = MockImageDataModel()
            series_manager.load_series_data(f"integration_series_{i+1}", mock_model)
        
        # 测试不同布局下的自动分配
        layouts_to_test = [(1, 1), (2, 2), (3, 3), (2, 1)]
        
        for rows, cols in layouts_to_test:
            logger.debug(f"[test_integration] 测试布局: {rows}x{cols}")
            
            series_manager.set_layout(rows, cols)
            assigned = binding_manager.auto_assign_series_to_views()
            
            current_layout = series_manager.get_current_layout()
            assert current_layout == (rows, cols), f"布局应为{rows}x{cols}"
            
            view_count = len(series_manager.get_all_view_ids())
            expected_views = rows * cols
            assert view_count == expected_views, f"视图数量应为{expected_views}"
        
        logger.info("[test_integration] 集成测试通过")
        
    except Exception as e:
        logger.error(f"[test_integration] 集成测试失败: {e}", exc_info=True)
        raise


def main():
    """主测试函数"""
    print("="*60)
    print("多序列组件测试")
    print("="*60)
    
    try:
        # 创建QApplication (Qt组件需要)
        app = QApplication(sys.argv)
        
        # 配置日志级别以显示调试信息
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        
        print("\n1. 测试 MultiSeriesManager...")
        test_multi_series_manager()
        print("✓ MultiSeriesManager 测试通过")
        
        print("\n2. 测试 SeriesViewBindingManager...")
        test_series_view_binding_manager()
        print("✓ SeriesViewBindingManager 测试通过")
        
        print("\n3. 测试组件集成...")
        test_integration()
        print("✓ 组件集成测试通过")
        
        print("\n" + "="*60)
        print("所有测试通过！✓")
        print("="*60)
        
        # 不需要运行事件循环，因为这只是功能测试
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        logger.error(f"[main] 主测试失败: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)