#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步功能测试模块

包含核心同步功能测试和UI同步功能测试
"""

import sys
import os
import unittest
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    
    from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
    from medimager.core.sync_manager import SyncManager, SyncMode, SyncGroup
    from medimager.ui.main_window import MainWindow
    from medimager.utils.logger import get_logger
    
    logger = get_logger(__name__)
    
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖项都已正确安装")
    sys.exit(1)


class TestCoreSyncFunctionality(unittest.TestCase):
    """核心同步功能测试"""
    
    def setUp(self):
        """测试前准备"""
        self.series_manager = None
        self.sync_manager = None
    
    def test_multi_series_manager_creation(self):
        """测试多序列管理器创建"""
        self.series_manager = MultiSeriesManager()
        self.assertIsNotNone(self.series_manager)
        logger.info("✓ 多序列管理器创建成功")
    
    def test_sync_manager_creation(self):
        """测试同步管理器创建"""
        self.series_manager = MultiSeriesManager()
        self.sync_manager = SyncManager(self.series_manager)
        self.assertIsNotNone(self.sync_manager)
        logger.info("✓ 同步管理器创建成功")
    
    def test_sync_modes(self):
        """测试同步模式设置"""
        self.series_manager = MultiSeriesManager()
        self.sync_manager = SyncManager(self.series_manager)
        
        # 测试基本同步模式
        self.sync_manager.set_sync_mode(SyncMode.BASIC)
        current_mode = self.sync_manager.get_sync_mode()
        self.assertEqual(current_mode, SyncMode.BASIC)
        logger.info(f"✓ 基本同步模式设置成功: {current_mode}")
        
        # 测试窗宽窗位同步模式
        self.sync_manager.set_sync_mode(SyncMode.WINDOW_LEVEL)
        current_mode = self.sync_manager.get_sync_mode()
        self.assertEqual(current_mode, SyncMode.WINDOW_LEVEL)
        logger.info(f"✓ 窗宽窗位同步模式设置成功: {current_mode}")
    
    def test_sync_groups(self):
        """测试同步分组设置"""
        self.series_manager = MultiSeriesManager()
        self.sync_manager = SyncManager(self.series_manager)
        
        # 测试全部视图同步
        self.sync_manager.set_sync_group(SyncGroup.ALL_VIEWS)
        current_group = self.sync_manager.get_sync_group()
        self.assertEqual(current_group, SyncGroup.ALL_VIEWS)
        logger.info(f"✓ 全部视图同步分组设置成功: {current_group}")
    
    def test_series_operations(self):
        """测试序列操作"""
        self.series_manager = MultiSeriesManager()
        
        # 创建测试序列
        test_series = SeriesInfo(
            series_id="test_001",
            patient_name="测试患者",
            series_description="测试序列",
            modality="CT",
            series_number="1"
        )
        
        # 添加序列
        series_id = self.series_manager.add_series(test_series)
        self.assertEqual(series_id, "test_001")
        self.assertEqual(self.series_manager.get_series_count(), 1)
        logger.info("✓ 序列添加成功")
        
        # 测试布局设置
        success = self.series_manager.set_layout(2, 2)
        self.assertTrue(success)
        current_layout = self.series_manager.get_current_layout()
        self.assertEqual(current_layout, (2, 2))
        logger.info(f"✓ 布局设置成功: {current_layout}")


class TestUISyncFunctionality(unittest.TestCase):
    """UI同步功能测试"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()
    
    def setUp(self):
        """测试前准备"""
        self.main_window = None
    
    def tearDown(self):
        """测试后清理"""
        if self.main_window:
            self.main_window.close()
            self.main_window = None
    
    def test_main_window_creation(self):
        """测试主窗口创建"""
        self.main_window = MainWindow()
        self.assertIsNotNone(self.main_window)
        self.assertIsNotNone(self.main_window.sync_manager)
        logger.info("✓ 主窗口创建成功")
    
    def test_sync_manager_integration(self):
        """测试同步管理器集成"""
        self.main_window = MainWindow()
        
        # 测试同步模式设置
        self.main_window.sync_manager.set_sync_mode(SyncMode.WINDOW_LEVEL)
        current_mode = self.main_window.sync_manager.get_sync_mode()
        self.assertEqual(current_mode, SyncMode.WINDOW_LEVEL)
        logger.info("✓ 主窗口同步模式设置成功")
    
    def test_layout_and_sync(self):
        """测试布局设置和同步"""
        self.main_window = MainWindow()
        
        # 设置布局
        self.main_window._set_layout((2, 2))
        
        # 验证布局
        current_layout = self.main_window.series_manager.get_current_layout()
        self.assertEqual(current_layout, (2, 2))
        
        # 验证视图数量
        view_frames = self.main_window.multi_viewer_grid.get_all_view_frames()
        self.assertEqual(len(view_frames), 4)
        logger.info("✓ 布局设置和视图创建成功")


def run_core_sync_tests():
    """运行核心同步功能测试"""
    print("\n" + "="*60)
    print("核心同步功能测试")
    print("="*60)
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCoreSyncFunctionality)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


def run_ui_sync_tests():
    """运行UI同步功能测试"""
    print("\n" + "="*60)
    print("UI同步功能测试")
    print("="*60)
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUISyncFunctionality)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


def main():
    """主测试函数"""
    print("="*60)
    print("同步功能完整测试套件")
    print("="*60)
    
    try:
        # 运行核心功能测试
        core_success = run_core_sync_tests()
        
        # 运行UI功能测试
        ui_success = run_ui_sync_tests()
        
        # 总结测试结果
        if core_success and ui_success:
            print("\n" + "="*60)
            print("🎉 所有同步功能测试通过！")
            print("="*60)
            print("\n已验证的功能：")
            print("- ✅ 多序列管理器")
            print("- ✅ 同步管理器")
            print("- ✅ 同步模式设置")
            print("- ✅ 同步分组设置")
            print("- ✅ 主窗口集成")
            print("- ✅ 布局管理")
            return 0
        else:
            print("\n" + "="*60)
            print("❌ 部分测试失败")
            print("="*60)
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试执行失败: {e}")
        logger.error(f"[main] 测试执行失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)