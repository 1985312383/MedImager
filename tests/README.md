# MedImager 测试套件

本目录包含 MedImager 项目的所有测试文件，统一管理以便于 CI/CD 流程中的代码覆盖度分析。

## 目录结构

```
tests/
├── __init__.py                     # Python包初始化文件
├── conftest.py                     # pytest配置和共享fixtures
├── run_tests.py                    # 测试运行脚本
├── README.md                       # 本说明文件
├── test_sync.py                    # 同步功能测试（合并版）
├── test_main_window.py             # 主窗口测试
├── test_multi_series_components.py # 多序列组件测试
├── test_dicom_parser.py            # DICOM解析测试
└── test_roi.py                     # ROI工具测试

```

## 测试文件说明

### test_sync.py
合并了原来的 `simple_sync_test.py` 和 `test_sync_fix.py`，包含：
- 核心同步功能测试（MultiSeriesManager, SyncManager）
- UI同步功能测试（主窗口集成测试）
- 同步模式和分组测试

### test_main_window.py
测试增强主窗口的基本功能：
- 主窗口创建和初始化
- 核心组件验证
- 布局变更测试

### test_multi_series_components.py
测试多序列管理组件：
- MultiSeriesManager 功能
- SeriesViewBindingManager 功能
- 序列绑定和布局管理

### test_dicom_parser.py
DICOM解析模块测试（待完善）

### test_roi.py
ROI工具模块测试（待完善）

## 运行测试

### 方法1：使用测试运行脚本（推荐）

```bash
# 在项目根目录下运行
python tests/run_tests.py
```

这个脚本会：
- 自动检测是否安装了pytest
- 如果有pytest，运行完整的测试套件并生成覆盖度报告
- 如果没有pytest，逐个运行测试文件

### 方法2：使用pytest（需要安装pytest）

```bash
# 安装依赖
pip install pytest pytest-cov

# 运行所有测试
pytest tests/ -v

# 运行测试并生成覆盖度报告
pytest tests/ --cov=medimager --cov-report=html --cov-report=term-missing

# 运行特定测试文件
pytest tests/test_sync.py -v
```

### 方法3：直接运行单个测试文件

```bash
# 在项目根目录下
python tests/test_sync.py
python tests/test_main_window.py
python tests/test_multi_series_components.py
```

## CI/CD 集成

### GitHub Actions 示例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov
    - name: Run tests
      run: python tests/run_tests.py
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### 覆盖度报告

运行测试后会生成以下覆盖度报告：
- `htmlcov/index.html` - HTML格式的详细覆盖度报告
- `coverage.xml` - XML格式的覆盖度报告（用于CI系统）
- 终端输出 - 显示覆盖度百分比和缺失的代码行

## 测试数据

### DICOM测试数据
- `dcm/gammex_phantom/` - Gammex体模的DICOM切片
- `dcm/water_phantom/` - 水体模的DICOM切片

这些测试数据由 `scripts/` 目录下的脚本生成，用于测试DICOM解析和图像处理功能。

## 开发指南

### 添加新测试

1. 在 `tests/` 目录下创建新的测试文件，命名格式为 `test_*.py`
2. 在文件开头添加正确的导入路径：
   ```python
   import sys
   from pathlib import Path
   
   # 添加项目根目录到 Python 路径
   project_root = Path(__file__).parent.parent
   sys.path.insert(0, str(project_root))
   ```
3. 使用 `conftest.py` 中定义的fixtures
4. 遵循pytest的命名约定

### 测试最佳实践

- 使用描述性的测试函数名
- 每个测试函数只测试一个功能点
- 使用适当的断言消息
- 清理测试产生的副作用
- 使用mock对象避免依赖外部资源

## 故障排除

### 常见问题

1. **导入错误**：确保项目根目录在Python路径中
2. **Qt应用程序错误**：确保在测试中正确初始化QApplication
3. **DICOM文件缺失**：检查测试数据是否存在于 `dcm/` 目录
4. **覆盖度过低**：检查是否有未测试的代码路径

### 调试技巧

- 使用 `pytest -s` 显示print输出
- 使用 `pytest --pdb` 在失败时进入调试器
- 使用 `pytest -k "test_name"` 运行特定测试
- 查看详细的覆盖度报告找出未覆盖的代码