<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**一款现代化的、跨平台的 DICOM 查看器与图像分析工具**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.9+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

[English](README.md) | **简体中文**

</div>

MedImager 是一款功能强大、用户友好、支持学术研究的开源医学图像查看器。它旨在通过提供流畅的图像交互、多格式支持（DICOM, PNG 等）以及先进的分析功能，来服务于学术研究和临床工作流程。

<div align="center">

![MedImager Demo](preview.png)

</div>

## 1. 项目愿景

创建一款功能强大、用户友好、支持学术研究的开源医学图像查看器。本项目旨在通过提供流畅的图像交互、多格式支持（DICOM, PNG 等）以及先进的分析功能，来服务于学术研究和临床工作流程，打造一款能与 RadiAnt 对标的开源替代品。

## 2. 核心功能 (开发路线图)

### V1.0 - 核心功能
- [x] **文件处理**:
    - [x] 从文件夹中打开和解析 DICOM 序列。
    - [x] 打开单张图像文件 (PNG, JPG, BMP)。
    - [x] DICOM 标签查看器。
- [x] **图像显示**:
    - [x] 支持流畅平移和缩放的 2D 查看器。
    - [x] 支持多视窗进行图像对比。
    - [x] 显示患者信息和图像叠加层 (比例尺, 方向标记)。
- [x] **图像交互工具**:
    - [x] **窗宽窗位 (Windowing)**: 交互式调整 HU 值的窗宽/窗位 (WW/WL)。
    - [x] **测量工具**:
        - [x] 标尺工具，用于测量距离。
        - [x] 椭圆/矩形 ROI 工具。
    - [x] **ROI 分析**: 计算 ROI 内的统计数据 (平均值, 标准差, 面积, 最大/最小 HU 值)。
- [x] **用户界面**:
    - [x] 现代化的多语言界面 (中文/英文)。
    - [x] 可自定义的主题系统 (亮色/暗色主题)。
    - [x] 完整的设置系统，支持工具外观自定义。
    - [x] 可停靠的面板布局。

### V2.0 - 高级功能
- [ ] **多平面重建 (MPR)**: 从 3D 容积数据中查看轴状面、矢状面和冠状面。
- [ ] **3D 容积渲染**: 对 DICOM 序列进行基本的 3D 可视化。
- [ ] **图像融合**: 叠加两个不同的序列 (例如 PET/CT)。
- [ ] **标注与导出**:
    - [ ] 保存标注信息 (ROIs, 测量结果)。
    - [ ] 将带有标注的视图导出为 PNG/JPG 图像。
- [ ] **插件系统**: 允许用户通过自定义 Python 脚本扩展功能，以促进学术研究。

## 3. 技术栈

* **编程语言**: Python 3.9+
* **GUI 框架**: PySide6 (LGPL 许可证)
* **DICOM 解析**: pydicom
* **数值与图像处理**: NumPy, SciPy, scikit-image
* **2D/3D 可视化**: Qt Graphics View Framework (用于 2D), VTK 9+ (用于 3D)
* **打包工具**: PyInstaller
* **多语言支持**: Qt Linguist (`pylupdate6`, `lrelease`)

## 4. 项目架构

项目遵循类似模型-视图-控制器 (MVC) 的设计模式，以分离数据逻辑、用户界面和用户交互。

```
medimager/
├── main.py                 # 应用程序入口点
├── icons/                    # 存放 UI 图标
├── translations/             # 存放翻译文件 (.ts, .qm)
│
├── core/                     # 核心逻辑，不依赖任何 UI
│   ├── __init__.py
│   ├── dicom_parser.py       # 使用 pydicom 处理 DICOM 文件的加载和解析
│   ├── image_data_model.py   # 单张图像或 DICOM 序列的数据模型
│   ├── roi.py                # 定义 ROI 形状和其计算逻辑
│   └── analysis.py           # 处理统计计算 (HU 值统计等)
│
├── ui/                       # 所有与 UI 相关的组件 (基于 PySide6)
│   ├── __init__.py
│   ├── main_window.py        # 主程序窗口、布局、菜单和工具栏
│   ├── image_viewer.py       # 核心的 2D 图像显示控件 (基于 QGraphicsView)
│   ├── viewport.py           # 包含一个 image_viewer 的独立视窗
│   ├── panels/                 # 可停靠的面板
│   │   ├── __init__.py
│   │   ├── series_panel.py     # 用于显示已加载序列和缩略图的面板
│   │   ├── dicom_tag_panel.py  # 用于显示 DICOM 标签的面板
│   │   └── analysis_panel.py   # 用于显示 ROI 分析结果的面板
│   └── tools/                  # 交互工具的 UI 实现
│       ├── __init__.py
│       ├── base_tool.py        # 所有工具的抽象基类
│       ├── pan_zoom_tool.py    # 平移缩放工具
│       ├── window_level_tool.py# 窗宽窗位工具
│       ├── measurement_tool.py # 测量工具
│
├── utils/                    # 通用工具函数和类
│   ├── __init__.py
│   ├── logger.py             # 配置全局日志记录
│   └── settings.py           # 处理用户偏好设置的保存与加载
│
├── tests/                    # 单元测试和集成测试
│   ├── __init__.py
│   ├── test_dicom_parser.py
│   └── test_roi.py
│
├── pyproject.toml            # 项目元数据和依赖项
└── README.md                 # 英文版文档
```

## 5. 使用方法

首先，请确保您已安装 [uv](https://github.com/astral-sh/uv)。它是一个非常快的 Python 包安装和解析工具。

1.  **克隆仓库:**
    ```bash
    git clone https://github.com/1985312383/MedImager.git
    cd MedImager
    ```

2.  **设置环境并安装依赖:**
    ```bash
    # 创建虚拟环境并从 pyproject.toml 同步依赖
    uv venv
    uv sync
    ```

3.  **运行程序:**
    ```bash
    # `uv run` 会自动使用 .venv 环境，无需手动激活，
    # 这样可以避免影响当前终端环境。
    uv run python medimager/main.py
    ```
    对于希望激活环境进行开发的开发者：
    ```bash
    # 激活虚拟环境:
    # Windows
    .venv\\Scripts\\activate
    # macOS / Linux
    source .venv/bin/activate
    
    # 之后就可以直接运行命令:
    python medimager/main.py
    ```

---

## 🤝 贡献

欢迎各种形式的贡献！无论是修复 Bug、添加新功能，还是改进文档，我们都非常欢迎。请随时开启一个 Issue 或提交一个 Pull Request。

## 📄 许可证

本项目基于 GNU 通用公共许可证 (GNU GENERAL PUBLIC LICENSE)。详情请参阅 [LICENSE](LICENSE) 文件。

---

## 贡献者

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")