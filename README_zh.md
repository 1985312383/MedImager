<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**一款现代化的、跨平台的 DICOM 查看器与图像分析工具**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

[English](README.md) | **简体中文** | [Deutsch](README_de.md) | [Español](README_es.md) | [Français](README_fr.md)

</div>

MedImager 是一款开源医学影像查看与分析工具，长期目标是逐步接近 RadiAnt 级阅片工作流。当前 1.x 阶段优先夯实可靠的 2D DICOM 基础、专业测试覆盖、标注持久化和性能基线，再继续推进 MPR、DICOMDIR/PACS、挂片布局等高级工作流能力。

<div align="center">

![MedImager Demo](preview.png)

</div>

## 1. 项目愿景

创建一款可逐步成长到 RadiAnt 级工作流的开源医学影像查看器。当前版本优先投入 DICOM 正确性、可复现测试、2D 交互质量、测量可靠性、标注持久化和性能优化，为后续 MPR、DICOMDIR/PACS、挂片布局和更完整的阅片工作流打基础。

## 2. 核心功能 (开发路线图)

### ✅ V1.0 - 核心功能 (已完成)
- [x] **文件处理**:
    - [x] 从文件夹中打开和解析 DICOM 序列。
    - [x] 打开单张图像文件 (PNG, JPG, BMP)。
    - [x] DICOM 标签查看器。
- [x] **图像显示**:
    - [x] 支持流畅平移和缩放的 2D 查看器。
    - [x] 支持灵活布局的多视窗图像对比。
    - [x] 显示患者信息和图像叠加层 (比例尺, 方向标记)。
- [x] **图像交互工具**:
    - [x] **窗宽窗位 (Windowing)**: 交互式调整 HU 值的窗宽/窗位 (WW/WL)，工具栏内置预设。
    - [x] **测量工具**:
        - [x] 标尺工具，用于测量距离。
        - [x] 角度测量工具。
        - [x] 椭圆/矩形/圆形 ROI 工具。
    - [x] **ROI 分析**: 计算 ROI 内的统计数据 (平均值, 标准差, 面积, 最大/最小 HU 值)。
    - [x] **图像变换**: 翻转 (水平/垂直)、旋转 (左旋/右旋90°)、反色，每个视图独立状态。
    - [x] **Cine 播放**: 自动播放序列切片，支持可调帧率。
    - [x] **图像导出**: 导出当前视图为 PNG/JPG，或复制到剪贴板。
- [x] **高级功能**:
    - [x] **多序列管理**: 同时加载和管理多个 DICOM 序列。
    - [x] **序列-视图绑定**: 灵活的绑定系统，支持自动分配和手动控制。
    - [x] **跨视图同步**: 位置、平移、缩放和窗宽窗位的跨视图同步。
    - [x] **布局系统**: 网格布局 (1×1 到 3×4) 和特殊布局 (垂直/水平分割, 三列布局)。
- [x] **用户界面**:
    - [x] 现代化的多语言界面 (中文/英文)。
    - [x] 可自定义的主题系统 (亮色/暗色主题) 支持实时切换。
    - [x] 完整的设置系统，支持工具外观自定义。
    - [x] 统一的工具栏，支持主题自适应图标。
    - [x] 可停靠的面板布局。

### V1.x - DICOM 正确性与测试基线
- [x] **专业合成 DICOM 测试集**: 覆盖 CT/MR/CR/US/PET、缺失标签、反向排序、非轴位几何、多 frame、压缩传输语法和 PixelSpacing 差异。
- [x] **解析器稳健性**: 明确解码插件依赖、多 frame 灰度展开、不一致几何 warning、以及不支持 DICOM 变体的错误提示。
- [x] **性能基线**: 建立大序列加载、窗宽窗位显示、缓存命中和 QImage 转换性能基准。

### V2.0 - 高级功能
- [ ] **多平面重建 (MPR)**: 从 3D 容积数据中查看轴状面、矢状面和冠状面。
- [ ] **3D 容积渲染**: 对 DICOM 序列进行基本的 3D 可视化。
- [ ] **图像融合**: 叠加两个不同的序列 (例如 PET/CT)。
- [x] **标注持久化**: 以版本化 JSON 保存和重新加载 ROI、距离测量和角度测量。
- [ ] **DICOMDIR / PACS**: 在 2D 解析基线稳定后，支持本地介质浏览和 DICOM 网络查询/取回。
- [ ] **挂片布局**: 保存和恢复面向重复阅片流程的实用布局。
- [ ] **插件系统**: 允许用户通过自定义 Python 脚本扩展功能，以促进学术研究。

## 3. 技术栈

* **编程语言**: Python 3.11+
* **GUI 框架**: PySide6 (LGPL 许可证)
* **DICOM 解析**: pydicom
* **数值与图像处理**: NumPy
* **2D 可视化**: Qt Graphics View Framework
* **打包工具**: PyInstaller
* **多语言支持**: Qt Linguist (`pylupdate6`, `lrelease`)

## 4. 项目架构

项目遵循类似模型-视图-控制器 (MVC) 的设计模式，以分离数据逻辑、用户界面和用户交互。

```
medimager/
├── main.py                     # 应用程序入口点
├── icons/                      # 存放 UI 图标
├── translations/               # 存放翻译文件 (.ts, .qm)
├── themes/                     # 主题配置文件
│   ├── ui/                     # UI 主题 (亮色/暗色)
│   ├── roi/                    # ROI 主题
│   └── measurement/            # 测量工具主题
│
├── core/                       # 核心逻辑，不依赖任何 UI
│   ├── __init__.py
│   ├── dicom_parser.py         # 使用 pydicom 处理 DICOM 文件的加载和解析
│   ├── image_data_model.py     # 单张图像或 DICOM 序列的数据模型
│   ├── multi_series_manager.py # 多序列管理器
│   ├── series_view_binding.py  # 序列-视图绑定管理
│   ├── sync_manager.py         # 跨视图同步管理
│   ├── roi.py                  # 定义 ROI 形状和其计算逻辑
│   └── analysis.py             # 处理统计计算 (HU 值统计等)
│
├── ui/                         # 所有与 UI 相关的组件 (基于 PySide6)
│   ├── __init__.py
│   ├── main_window.py          # 主程序窗口、布局、菜单和工具栏
│   ├── main_toolbar.py         # 统一的主工具栏
│   ├── image_viewer.py         # 核心的 2D 图像显示控件 (基于 QGraphicsView)
│   ├── viewport.py             # 包含一个 image_viewer 的独立视窗
│   ├── multi_viewer_grid.py    # 多视图网格布局管理
│   ├── panels/                 # 可停靠的面板
│   │   ├── __init__.py
│   │   ├── series_panel.py     # 用于显示已加载序列和缩略图的面板
│   │   └── dicom_tag_panel.py  # 用于显示 DICOM 标签的面板
│   ├── tools/                  # 交互工具的 UI 实现
│   │   ├── __init__.py
│   │   ├── base_tool.py        # 所有工具的抽象基类
│   │   ├── default_tool.py     # 默认平移缩放和窗宽窗位工具
│   │   ├── measurement_tool.py # 测量工具
│   │   ├── angle_tool.py       # 角度测量工具
│   │   └── roi_tool.py         # ROI 工具
│   ├── widgets/                # 可重用的UI组件
│   │   ├── __init__.py
│   │   ├── layout_grid_selector.py # 布局选择器组件
│   │   ├── magnifier.py        # 放大镜组件
│   │   ├── roi_stats_box.py    # ROI 统计显示组件
│   │   └── panel_toggle_strip.py   # 面板切换条组件
│   └── dialogs/                # 对话框
│       ├── custom_wl_dialog.py # 自定义窗宽窗位对话框
│       └── settings_dialog.py  # 设置对话框
│
├── utils/                      # 通用工具函数和类
│   ├── __init__.py
│   ├── logger.py               # 配置全局日志记录
│   ├── settings.py             # 处理用户偏好设置的保存与加载
│   ├── theme_manager.py        # 主题管理器
│   ├── resource_path.py        # 资源/图标路径解析
│   └── i18n.py                 # 国际化支持
│
├── tests/                      # 单元测试和集成测试
│   ├── __init__.py
│   ├── test_dicom_parser.py
│   ├── test_roi.py
│   └── dcm/                    # 测试用DICOM文件
│       ├── water_phantom/
│       └── gammex_phantom/
│
├── pyproject.toml              # 项目元数据和依赖项
└── README.md                   # 英文版文档
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

4.  **运行性能基准（开发者）:**
    ```bash
    uv run python -m medimager.performance.baseline \
      --slices 300 \
      --rows 512 \
      --cols 512 \
      --repeats 3 \
      --display-samples 64 \
      --output performance_baseline.json
    ```
    该命令会生成合成去标识 DICOM 大序列，并记录序列加载、窗宽窗位显示、缓存命中显示和 QImage 转换耗时。默认不在单元测试中设置硬性性能阈值，避免不同机器产生误报；release 前可保存 JSON 结果用于跨版本对比。

---

## 🤝 贡献

欢迎各种形式的贡献！无论是修复 Bug、添加新功能，还是改进文档，我们都非常欢迎。请随时开启一个 Issue 或提交一个 Pull Request。

## 📄 许可证

本项目基于 GNU 通用公共许可证 (GNU GENERAL PUBLIC LICENSE)。详情请参阅 [LICENSE](LICENSE) 文件。

---

## 贡献者

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")
