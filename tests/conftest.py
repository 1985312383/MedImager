#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest配置文件

为测试套件提供共享的fixtures和配置
"""

import sys
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def qapp():
    """创建QApplication实例的fixture"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # 测试结束后不需要显式退出，pytest会处理


@pytest.fixture(scope="function")
def temp_dicom_data():
    """提供临时DICOM测试数据的fixture"""
    # 返回测试DICOM文件路径
    test_data_dir = Path(__file__).parent / "dcm"
    return {
        "gammex_phantom": test_data_dir / "gammex_phantom",
        "water_phantom": test_data_dir / "water_phantom"
    }


@pytest.fixture(scope="function")
def mock_series_info():
    """提供模拟序列信息的fixture"""
    from medimager.core.multi_series_manager import SeriesInfo
    
    return SeriesInfo(
        series_id="test_series_001",
        patient_name="测试患者",
        patient_id="P001",
        series_description="测试序列",
        modality="CT",
        series_number="1",
        slice_count=10
    )