
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

## 5. 多语言支持 (i18n) 设计

为确保应用具备良好的国际化能力，我们采用 PySide6 官方推荐的 `Qt Linguist` 工作流。

1.  **代码实现**: 所有需要翻译的面向用户的字符串，都必须使用 `self.tr("Your Text Here")` 进行包裹。`tr()` 是 `QObject` 的一个方法，它能标记需要被翻译的文本。
2.  **生成翻译文件**: 在项目根目录运行 `pylupdate6 medimager -ts medimager/translations/zh_CN.ts` 命令，它会扫描整个 `medimager` 目录下的 Python 文件，并把所有 `tr()` 包裹的字符串提取出来，生成 `zh_CN.ts` 文件。
3.  **人工翻译**: 使用 Qt 官方提供的 `Qt Linguist` 图形化工具打开 `.ts` 文件，为每一条原文条目填入对应的译文。
4.  **编译翻译文件**: 翻译完成后，使用 `lrelease medimager/translations/zh_CN.ts` 命令，将 `.ts` 文件编译成程序可直接加载的二进制 `.qm` 文件。
5.  **加载翻译**: 在 `main.py` 中，根据用户选择的语言或系统默认语言，使用 `QTranslator` 类加载对应的 `.qm` 文件，即可实现界面的动态翻译。

## 6. 详细模块设计

### 6.1. `main.py` (应用程序入口)
*   **职责**: 初始化 `QApplication`，加载全局配置（如日志、设置），加载多语言翻译文件，创建并显示 `MainWindow`。
*   **关键逻辑**:
    *   `main()`:
        *   创建 `QApplication` 实例。
        *   创建 `QTranslator` 实例。
        *   根据 `settings.py` 中的语言设置，加载对应的 `.qm` 文件 (e.g., `translations/zh_CN.qm`) 并安装到 `QApplication`。
        *   实例化 `MainWindow`。
        *   显示主窗口并启动事件循环。

### 6.2. `core/image_data_model.py` (数据模型)
*   **职责**: 作为单个图像序列（如一个CT扫描）的独立数据容器。完全独立于UI，只负责数据的存储、处理和状态维护。
*   **`ImageDataModel` 类**:
    *   **属性**:
        *   `dicom_files: list[pydicom.FileDataset]`: 存储原始的pydicom文件对象列表。
        *   `pixel_array: np.ndarray`: 存储原始的、完整的像素数据 (3D or 2D)。
        *   `dicom_header: dict`: 存储关键的、常用的DICOM元数据。
        *   `current_slice_index: int`: 当前显示的切片索引。
        *   `window_width: int`: 当前窗宽。
        *   `window_level: int`: 当前窗位。
        *   `rois: list[ROI]`: 包含的ROI对象列表。
        *   `selected_indices: set[int]`: 当前多选的ROI索引集合。
    *   **方法**:
        *   `load_dicom_series(file_paths: list[str])`: 从文件路径加载DICOM序列。
        *   `get_display_slice() -> np.ndarray`: 根据 `current_slice_index` 获取当前切片。
        *   `apply_window_level(slice_data: np.ndarray) -> np.ndarray`: 将窗宽窗位应用到切片数据，返回8位灰度图数据。
        *   `set_window(width: int, level: int)`: 设置窗宽窗位，并发出信号。
        *   `select_roi(idx: int, multi: bool = False)`: 支持Ctrl多选、单选、取消选中。
        *   `clear_selection()`: 清除所有选中ROI。
    *   **信号**:
        *   `image_loaded()`: 当新的图像数据加载完成时发出。
        *   `data_changed()`: 当模型的数据（如窗宽窗位、ROI等）发生变化时发出，通知视图更新。

### 6.3. `core/roi.py` (ROI形状与几何逻辑)
*   **职责**: 定义通用的ROI基类（BaseROI），支持多种形状（圆、椭圆、矩形等），并实现锚点、命中测试、移动、缩放等通用接口。
*   **设计亮点**:
    *   `BaseROI` 提供统一的锚点、选中、多选、命中测试、拖拽缩放等接口，便于扩展新形状。
    *   每个ROI子类（如CircleROI、EllipseROI）实现自己的几何逻辑和锚点行为。
    *   支持"锚点拖拽"时只影响当前锚点和对角锚点，保证交互直观。

### 6.4. `ui/image_viewer.py` (核心图像视图)
*   **职责**: 作为"视图"，只负责高效地渲染 `ImageDataModel` 提供的数据，并将用户输入（鼠标事件）传递给当前激活的工具。
*   **`ImageViewer(QGraphicsView)` 类**:
    *   **内部组件**:
        *   `QGraphicsScene`: 图形场景。
        *   `QGraphicsPixmapItem`: 用于显示图像的图元。
        *   放大镜、十字光标等辅助控件。
    *   **逻辑**:
        *   `set_model(model: ImageDataModel)`: 关联一个数据模型。连接模型的 `data_changed` 信号到自己的 `_update_view` 槽。
        *   `set_tool(tool: BaseTool)`: 设置当前激活的工具，所有鼠标/滚轮事件都委托给工具处理。
        *   `drawForeground`: 绘制所有ROI及其锚点，选中ROI高亮显示。
        *   `zoom_in/zoom_out`: 支持缩放并实时发射缩放信号，界面可显示当前缩放比例。
        *   完全解耦业务逻辑与UI，所有数据变更通过信号驱动。

### 6.5. `ui/tools/*.py` (交互工具架构)
*   **职责**: 实现具体的交互逻辑，采用"状态模式"。每个工具都是一个独立的状态对象，便于扩展和维护。
*   **`BaseTool` (抽象基类)**:
    *   定义所有工具的通用接口，如 `activate(viewer)`, `deactivate()`, `mousePressEvent(...)` 等。
*   **`DefaultTool(BaseTool)`**:
    *   默认工具，支持平移、缩放、窗宽窗位、ROI选择/多选、ROI拖动、锚点缩放等复合交互。
    *   鼠标左键点击ROI支持Ctrl多选，拖动锚点时只影响两个点，保证锚点不乱跑。
    *   鼠标滚轮/右键缩放时，缩放值实时更新。
*   **其它工具（如ROI绘制、测量等）**:
    *   可按需扩展，互斥激活，便于后续支持更多交互类型。

### 6.6. `ui/main_window.py` (主窗口)
*   **职责**: 应用程序的"指挥中心"。负责创建和布局所有UI组件（菜单栏、工具栏、状态栏、面板、视口），并协调它们之间的交互。
*   **`MainWindow` 类**:
    *   **UI组件**:
        *   `QMenuBar`, `QToolBar`, `QStatusBar`
        *   停靠面板 (e.g., `SeriesPanel`, `DicomTagPanel`, `AnalysisPanel`)
        *   中央布局管理器，用于容纳一个或多个 `Viewport`。
    *   **逻辑**:
        *   `_init_menus()` / `_init_toolbars()`: 创建 `QAction` 并连接到对应的槽函数。
        *   管理当前激活的工具，工具栏按钮互斥，切换时自动更新 `ImageViewer` 的工具状态。
        *   响应模型信号，自动刷新视图和状态栏。

### 6.7. `ui/panels/` (功能面板)
*   **职责**: 提供序列浏览、DICOM标签查看、ROI分析等功能的可停靠面板。
*   **设计**:
    *   每个面板为独立模块，便于扩展和维护。
    *   通过信号与主窗口和数据模型解耦。

### 6.8. `utils/` (通用工具模块)
*   **职责**: 提供日志、设置、国际化等通用功能。
*   **模块**:
    *   `logger.py`: 全局日志记录，便于调试和问题追踪。
    *   `settings.py`: 用户偏好设置的保存与加载，基于`QSettings`。
    *   `i18n.py`: 国际化支持，集成Qt Linguist工作流。

## 7. 开发入门

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
    python medimager/main.py
    ```
    或者
    ```
    python -m medimager.main
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