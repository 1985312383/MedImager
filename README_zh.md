![MedImager Banner](medimager/icons/banner.png)

<div align="center">

[English](README.md) | **简体中文**

</div>

# MedImager - 一款现代化的 DICOM 查看器与图像分析工具

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
    - [ ] 支持多视窗进行图像对比。
    - [ ] 显示患者信息和图像叠加层 (比例尺, 方向标记)。
- [x] **图像交互工具**:
    - [x] **窗宽窗位 (Windowing)**: 交互式调整 HU 值的窗宽/窗位 (WW/WL)。
    - [x] **测量工具**:
        - [x] 标尺工具，用于测量距离。
        - [x] 椭圆/矩形 ROI 工具。
    - [x] **ROI 分析**: 计算 ROI 内的统计数据 (平均值, 标准差, 面积, 最大/最小 HU 值)。

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
├── requirements.txt          # Python 依赖项
└── README.md                 # 英文版文档 (待创建)
```

## 5. 使用方法

1.  **克隆仓库:**
    ```bash
    git clone <your-repo-url>
    cd MedImager
    ```

2.  **创建并激活虚拟环境:**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS / Linux
    source venv/bin/activate
    ```

3.  **安装依赖:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **运行程序:**
    ```bash
    python medimager/main.py  # 推荐方式
    ```
    或者
    ```bash
    python -m medimager.main  # 开发方法
    ```

---
*初始 `requirements.txt` 文件内容:*

```
PySide6
pydicom
numpy
scipy
scikit-image
pyinstaller
# vtk # 当开始开发 3D 功能时再添加
```

---


## 贡献者

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")