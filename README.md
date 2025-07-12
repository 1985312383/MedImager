<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**A Modern, Cross-Platform DICOM Viewer & Image Analysis Tool**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.9+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

**English** | [简体中文](README_zh.md)

</div>

MedImager is a powerful, user-friendly, and research-oriented open-source medical image viewer. It aims to provide smooth image interaction, multi-format support (DICOM, PNG, etc.), and advanced analysis features for academic and clinical workflows.

## 1. Project Vision

Create a powerful, user-friendly, and research-oriented open-source medical image viewer. MedImager aims to provide smooth image interaction, multi-format support (DICOM, PNG, etc.), and advanced analysis features for academic and clinical workflows, aspiring to be an open-source alternative to RadiAnt.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Core Features (Roadmap)

### V1.0 - Core Features
- [x] **File Handling:**
    - [x] Open and parse DICOM series from folders.
    - [x] Open single image files (PNG, JPG, BMP).
    - [x] DICOM tag viewer.
- [x] **Image Display:**
    - [x] Smooth pan and zoom 2D viewer.
    - [x] Multi-viewport for image comparison.
    - [x] Display patient info and image overlays (scale, orientation marker).
- [x] **Image Interaction Tools:**
    - [x] **Windowing:** Interactive adjustment of HU window width/level (WW/WL).
    - [x] **Measurement Tools:**
        - [x] Ruler tool for distance measurement.
        - [x] Ellipse/rectangle ROI tools.
    - [x] **ROI Analysis:** Calculate statistics within ROI (mean, std, area, max/min HU).
- [x] **User Interface:**
    - [x] Modern multilingual interface (Chinese/English).
    - [x] Customizable theme system (light/dark themes).
    - [x] Complete settings system with tool appearance customization.
    - [x] Dockable panel layout.

### V2.0 - Advanced Features
- [ ] **Multi-Planar Reconstruction (MPR):** View axial, sagittal, and coronal planes from 3D volume data.
- [ ] **3D Volume Rendering:** Basic 3D visualization of DICOM series.
- [ ] **Image Fusion:** Overlay two different series (e.g., PET/CT).
- [ ] **Annotation & Export:**
    - [ ] Save annotation info (ROIs, measurements).
    - [ ] Export annotated views as PNG/JPG images.
- [ ] **Plugin System:** Allow users to extend features via custom Python scripts for research.

## 3. Tech Stack

* **Language:** Python 3.9+
* **GUI Framework:** PySide6 (LGPL)
* **DICOM Parsing:** pydicom
* **Numerical/Image Processing:** NumPy, SciPy, scikit-image
* **2D/3D Visualization:** Qt Graphics View Framework (2D), VTK 9+ (3D)
* **Packaging:** PyInstaller
* **i18n:** Qt Linguist (`pylupdate6`, `lrelease`)

## 4. Project Structure

The project follows an MVC-like pattern to separate data logic, UI, and user interaction.

```
medimager/
├── main.py                 # Application entry point
├── icons/                  # UI icons
├── translations/           # Translation files (.ts, .qm)
│
├── core/                   # Core logic, UI-independent
│   ├── __init__.py
│   ├── dicom_parser.py     # DICOM loading/parsing via pydicom
│   ├── image_data_model.py # Data model for single image or DICOM series
│   ├── roi.py              # ROI shapes and logic
│   └── analysis.py         # Statistical calculations (HU stats, etc.)
│
├── ui/                     # All UI components (PySide6)
│   ├── __init__.py
│   ├── main_window.py      # Main window, layout, menus, toolbar
│   ├── image_viewer.py     # Core 2D image viewer (QGraphicsView)
│   ├── viewport.py         # Standalone viewport with image_viewer
│   ├── panels/             # Dockable panels
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Loaded series/thumbnails panel
│   │   ├── dicom_tag_panel.py  # DICOM tag panel
│   │   └── analysis_panel.py   # ROI analysis panel
│   └── tools/              # Interactive tool UI implementations
│       ├── __init__.py
│       ├── base_tool.py        # Abstract base class for tools
│       ├── pan_zoom_tool.py    # Pan/zoom tool
│       ├── window_level_tool.py# Window/level tool
│       ├── measurement_tool.py # Measurement tool
│
├── utils/                  # General utilities
│   ├── __init__.py
│   ├── logger.py           # Global logging config
│   └── settings.py         # User settings save/load
│
├── tests/                  # Unit/integration tests
│   ├── __init__.py
│   ├── test_dicom_parser.py
│   └── test_roi.py
│
├── pyproject.toml          # Project metadata and dependencies
└── README_zh.md            # Chinese documentation
```

## 5. Usage

First, ensure you have [uv](https://github.com/astral-sh/uv) installed. It is an extremely fast Python package installer and resolver.

1.  **Clone the repo:**
    ```bash
    git clone https://github.com/1985312383/MedImager.git
    cd MedImager
    ```

2.  **Setup Environment and Install Dependencies:**
    ```bash
    # Create a virtual environment and sync dependencies from pyproject.toml
    uv venv
    uv sync
    ```

3.  **Run the app:**
    ```bash
    # `uv run` executes the command within the project's virtual environment,
    # avoiding the need to activate it in your shell.
    uv run python medimager/main.py
    ```
    For developers who prefer an active environment:
    ```bash
    # To activate the environment in your current shell:
    # Windows
    .venv\\Scripts\\activate
    # macOS / Linux
    source .venv/bin/activate
    
    # Then you can run commands directly:
    python medimager/main.py
    ```

---

## 🤝 Contributing

Contributions are welcome! Whether you're fixing a bug, adding a feature, or improving documentation, your help is appreciated. Please feel free to open an issue or submit a pull request.

## 📄 License

This project is licensed under the GNU GENERAL PUBLIC LICENSE. See the [LICENSE](LICENSE) file for details.

---

## Contributors

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")