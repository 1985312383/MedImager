#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强主窗口测试脚本
测试新的增强主窗口及其集成的多序列管理功能
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    
    from medimager.ui.main_window import MainWindow
    from medimager.utils.logger import get_logger
    
    logger = get_logger(__name__)
    
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖项都已正确安装")
    sys.exit(1)


def test_main_window():
    """测试增强主窗口的基本功能"""
    logger.info("[test_main_window] 开始测试增强主窗口")
    
    try:
        # 创建应用程序
        app = QApplication(sys.argv)
        
        # 创建增强主窗口
        main_window = MainWindow()
        logger.info("[test_main_window] 增强主窗口创建成功")
        
        # 验证核心组件
        assert hasattr(main_window, 'series_manager'), "应有多序列管理器"
        assert hasattr(main_window, 'binding_manager'), "应有绑定管理器"
        assert hasattr(main_window, 'enhanced_series_panel'), "应有增强序列面板"
        assert hasattr(main_window, 'multi_viewer_grid'), "应有多视图网格"
        
        # 验证初始状态
        assert main_window.series_manager.get_series_count() == 0, "初始序列数量应为0"
        assert main_window.series_manager.get_current_layout() == (1, 1), "初始布局应为1x1"
        
        # 显示主窗口
        main_window.show()
        logger.info("[test_main_window] 主窗口显示成功")
        
        # 测试布局变更
        logger.debug("[test_main_window] 测试布局变更")
        main_window._set_layout(2, 2)
        assert main_window.series_manager.get_current_layout() == (2, 2), "布局应变更为2x2"
        
        # 设置定时器自动关闭
        timer = QTimer()
        timer.timeout.connect(main_window.close)
        timer.start(3000)  # 3秒后自动关闭
        
        logger.info("[test_main_window] 增强主窗口测试通过")
        
        # 运行事件循环
        app.exec_()
        
        return True
        
    except Exception as e:
        logger.error(f"[test_main_window] 测试失败: {e}", exc_info=True)
        return False


def main():
    """主测试函数"""
    print("="*60)
    print("增强主窗口测试")
    print("="*60)
    
    try:
        print("\n1. 测试增强主窗口基本功能...")
        success = test_main_window()
        
        if success:
            print("✅ 增强主窗口测试通过")
            print("\n" + "="*60)
            print("测试完成！✓")
            print("="*60)
            return 0
        else:
            print("❌ 增强主窗口测试失败")
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        logger.error(f"[main] 主测试失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
