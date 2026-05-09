<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**A Modern, Cross-Platform DICOM Viewer & Image Analysis Tool**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

**English** | [简体中文](README_zh.md) | [Deutsch](README_de.md) | [Español](README_es.md) | [Français](README_fr.md)

</div>

MedImager is an open-source medical image viewer and analysis tool with a long-term goal of approaching RadiAnt-class reading workflows. Version 2.0 consolidates the completed 1.0 and 1.x work into a reliable 2D DICOM foundation: multi-series viewing, measurement and ROI analysis, professional synthetic DICOM coverage, annotation persistence, and repeatable performance baselines.

## 1. Project Vision

Create a pragmatic open-source viewer that can grow toward RadiAnt-grade workflows. MedImager 2.0 is ready as the stable 2D foundation release; later versions should build on that base with MPR, DICOMDIR/PACS, hanging protocols, and advanced clinical-style workflows.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Core Features

### ✅ V2.0 - 2D DICOM Foundation (READY)
- [x] **File Handling:**
    - [x] Open and parse DICOM series from folders.
    - [x] Open single image files (PNG, JPG, BMP).
    - [x] DICOM tag viewer.
- [x] **Image Display:**
    - [x] Smooth pan and zoom 2D viewer.
    - [x] Multi-viewport for image comparison with flexible layouts.
    - [x] Display patient info and image overlays (scale, orientation marker).
- [x] **Image Interaction Tools:**
    - [x] **Windowing:** Interactive adjustment of HU window width/level (WW/WL) with toolbar presets.
    - [x] **Measurement Tools:**
        - [x] Ruler tool for distance measurement.
        - [x] Angle measurement tool.
        - [x] Ellipse/rectangle/circle ROI tools.
    - [x] **ROI Analysis:** Calculate statistics within ROI (mean, std, area, max/min HU).
    - [x] **Image Transforms:** Flip (horizontal/vertical), rotate (90° left/right), invert, with per-view state.
    - [x] **Cine Playback:** Auto-play through slices with adjustable FPS.
    - [x] **Image Export:** Export current view to PNG/JPG, or copy to clipboard.
- [x] **Advanced Features:**
    - [x] **Multi-Series Management:** Load and manage multiple DICOM series simultaneously.
    - [x] **Series-View Binding:** Flexible binding system with auto-assignment and manual control.
    - [x] **Synchronization:** Cross-viewport sync for position, pan, zoom, and window/level.
    - [x] **Layout System:** Grid layouts (1×1 to 3×4) and special layouts (vertical/horizontal split, triple column).
- [x] **User Interface:**
    - [x] Modern multilingual interface (Chinese/English).
    - [x] Customizable theme system (light/dark themes) with real-time switching.
    - [x] Complete settings system with tool appearance customization.
    - [x] Unified toolbar with theme-adaptive icons.
    - [x] Dockable panel layout.
- [x] **DICOM Correctness and Quality Baseline:**
    - [x] Professional synthetic DICOM test set covering CT/MR/CR/US/PET, missing tags, reverse ordering, oblique geometry, multi-frame data, compressed transfer syntaxes, and PixelSpacing variants.
    - [x] Parser robustness for decoder dependencies, multi-frame grayscale expansion, inconsistent geometry warnings, and unsupported DICOM variants.
    - [x] Large-series loading, window/level display, cache-hit display, and QImage conversion performance baselines.
    - [x] Versioned JSON annotation persistence for ROI, distance measurement, and angle measurement annotations.

### Next Roadmap - RadiAnt-Class Workflow
- [ ] **Multi-Planar Reconstruction (MPR):** View axial, sagittal, and coronal planes from 3D volume data.
- [ ] **3D Volume Rendering:** Basic 3D visualization of DICOM series.
- [ ] **Image Fusion:** Overlay two different series (e.g., PET/CT).
- [ ] **DICOMDIR / PACS:** Local media browsing and DICOM network query/retrieve after the 2D parser baseline is stable.
- [ ] **Hanging Protocols:** Save and restore practical reading layouts for repeated study review.
- [ ] **Plugin System:** Allow users to extend features via custom Python scripts for research.

## 3. Tech Stack

* **Language:** Python 3.11+
* **GUI Framework:** PySide6 (LGPL)
* **DICOM Parsing:** pydicom
* **Numerical/Image Processing:** NumPy
* **2D Visualization:** Qt Graphics View Framework
* **Packaging:** PyInstaller
* **i18n:** YAML source catalogs compiled to JSON runtime catalogs

## 4. Project Structure

The project follows an MVC-like pattern to separate data logic, UI, and user interaction.

```
medimager/
├── main.py                 # Application entry point
├── icons/                  # UI icons and SVG resources
├── i18n/                   # YAML source catalogs and compiled JSON runtime catalogs
├── themes/                 # Theme configuration files
│   ├── ui/                 # UI themes (dark.toml, light.toml)
│   ├── roi/                # ROI appearance themes
│   └── measurement/        # Measurement tool themes
│
├── core/                   # Core logic, UI-independent (MVC Model)
│   ├── __init__.py
│   ├── dicom_parser.py     # DICOM loading/parsing via pydicom
│   ├── image_data_model.py # Data model for single image or DICOM series
│   ├── multi_series_manager.py # Multi-series management and layout control
│   ├── series_view_binding.py  # Series-view binding management
│   ├── sync_manager.py     # Cross-viewport synchronization
│   ├── roi.py              # ROI shapes and logic
│   └── analysis.py         # Statistical calculations (HU stats, etc.)
│
├── ui/                     # All UI components (MVC View & Controller)
│   ├── __init__.py
│   ├── main_window.py      # Main window with multi-series support
│   ├── main_toolbar.py     # Unified toolbar management (tools, layout, sync)
│   ├── image_viewer.py     # Core 2D image viewer (QGraphicsView)
│   ├── viewport.py         # Standalone viewport with image_viewer
│   ├── multi_viewer_grid.py# Multi-viewport grid layout manager
│   ├── panels/             # Dockable panels
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Multi-series management panel
│   │   └── dicom_tag_panel.py  # DICOM tag panel
│   ├── tools/              # Interactive tool implementations
│   │   ├── __init__.py
│   │   ├── base_tool.py        # Abstract base class for tools
│   │   ├── default_tool.py     # Default pointer/pan/zoom/window tool
│   │   ├── roi_tool.py         # ROI tools (ellipse, rectangle, circle)
│   │   ├── measurement_tool.py # Distance measurement tool
│   │   └── angle_tool.py       # Angle measurement tool
│   ├── dialogs/            # Dialog windows
│   │   ├── custom_wl_dialog.py # Custom window/level dialog
│   │   └── settings_dialog.py  # Application settings dialog
│   └── widgets/            # Custom UI widgets
│       ├── __init__.py
│       ├── magnifier.py        # Magnifier widget
│       ├── roi_stats_box.py    # ROI statistics display
│       ├── layout_grid_selector.py # Layout selection widget
│       └── panel_toggle_strip.py   # Panel toggle strip widget
│
├── utils/                  # General utilities (MVC Model Support)
│   ├── __init__.py
│   ├── logger.py           # Global logging configuration
│   ├── settings.py         # User settings management
│   ├── theme_manager.py    # Theme system with icon management
│   ├── resource_path.py    # Resource/icon path resolution
│   └── i18n.py             # Internationalization utilities
│
├── tests/                  # Unit/integration tests
│   ├── __init__.py
│   ├── dcm/                # Test DICOM data
│   ├── scripts/            # Test data generation scripts
│   ├── test_dicom_parser.py
│   ├── test_roi.py
│   └── test_multi_series_components.py
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

4.  **Run the performance baseline (developers):**
    ```bash
    uv run python -m medimager.performance.baseline \
      --slices 300 \
      --rows 512 \
      --cols 512 \
      --repeats 3 \
      --display-samples 64 \
      --output performance_baseline.json
    ```
    This creates a synthetic de-identified DICOM series and records series loading, window/level display, cache-hit display, and QImage conversion timings. Unit tests intentionally do not enforce hard performance thresholds to avoid machine-specific failures; save the JSON before releases for cross-version comparison.

5.  **Update translations (developers):**
    ```bash
    # Edit medimager/i18n/locales/*.yml first, then rebuild runtime catalogs.
    python translation_tools/main.py
    ```
    UI code should use stable keys via `t("...")`. The old Qt `.ts/.qm` chain is not used.

---

## 🤝 Contributing

Contributions are welcome! Whether you're fixing a bug, adding a feature, or improving documentation, your help is appreciated. Please feel free to open an issue or submit a pull request.

## 📄 License

This project is licensed under the GNU GENERAL PUBLIC LICENSE. See the [LICENSE](LICENSE) file for details.

---

## Contributors

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")
