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

MedImager is an open-source medical image viewer and analysis tool with a long-term goal of approaching RadiAnt-class reading workflows. Version 2.6 turns the patient-space 2D/MPR core into a discoverable visual study workbench: it adds a start center, read-only DICOMDIR browsing, a filterable series navigator, transactional layout presets, Settings Center 2.0, privacy presentation, and three deterministic offline example studies.

> [!WARNING]
> **Research and teaching use only — not diagnostic grade.** MedImager has not completed DICOM GSDF conformance or calibrated diagnostic-display validation. Do not use it for primary diagnosis or other clinical decisions.

## 1. Project Vision

Create a pragmatic open-source viewer that can grow toward RadiAnt-grade workflows. MedImager 2.6 combines geometry-validated orthogonal MPR with local-media study discovery and a practical cross-series reading flow. PACS, oblique reconstruction, 3D rendering, fusion, and diagnostic-grade validation remain future work.

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

### ✅ V2.4 - Patient-Space Volume and Orthogonal MPR
- [x] Geometry-validated axial, coronal, and sagittal reconstruction.
- [x] Linked 3D cursor and true orthogonal localizer lines.
- [x] Asynchronous volume building with cancellation and memory preflight.
- [x] Patient-space DICOM LPS annotation schema v2.

### ✅ V2.5 - Study Workspace and Cross-Series Reading
- [x] Stable Patient → Study → Series inspection navigator with background thumbnails.
- [x] Millimetre-based LPS slice synchronization, true cross-series localizer lines, and shared 3D cursor.
- [x] Study overview, CT comparison, MR neuro, and current-series MPR hanging presets.
- [x] Per-study restoration of layout, binding, display, and synchronization state.
- [x] Active-study load ordering, persistent thumbnail cache, and neighboring-slice prefetch.

### ✅ V2.6 - Visual Study Workbench and Example Center
- [x] Start center for DICOM folders, multiple folders, DICOMDIR media, ordinary images, privacy-aware recent studies, and sample studies.
- [x] Read-only DICOMDIR Patient → Study → Series selection with safe media-root path validation and visible issue reporting.
- [x] Searchable/filterable compact series navigator, multi-select comparison, clinical layout gallery, and geometry-only user layouts.
- [x] Adaptive 24 px reading toolbar and expanded orthogonal MPR controls with per-plane position, linked state, and 3-column/1+2 layouts.
- [x] Typed Settings Center 2.0, workspace schema v2, screen privacy presentation, and whitelist-based cache cleanup.
- [x] Deterministic CT Multiphase, MR Brain, and Geometry Lab studies generated asynchronously without bundling DICOM pixels.

### Next Roadmap - RadiAnt-Class Workflow
- [ ] **3D Volume Rendering:** Basic 3D visualization of DICOM series.
- [ ] **Image Fusion:** Overlay two different series (e.g., PET/CT).
- [x] **DICOMDIR:** Read-only local-media browsing and study/series selection (v2.6).
- [ ] **PACS:** DICOM network query/retrieve.
- [x] **Hanging Protocols:** Study-scoped CT/MR/overview presets with state restoration and a visual gallery (v2.6).
- [ ] **Plugin System:** Allow users to extend features via custom Python scripts for research.

## 3. Tech Stack

* **Language:** Python 3.11+
* **GUI Framework:** PySide6 (LGPL)
* **DICOM Parsing:** pydicom
* **Numerical/Image Processing:** NumPy and SimpleITK
* **2D Visualization:** Qt Graphics View Framework
* **Packaging:** PyInstaller
* **i18n:** YAML source catalogs compiled to JSON runtime catalogs

## 4. Project Structure

The project follows an MVC-like pattern to separate data logic, UI, and user interaction.

```
MedImager/
├── medimager/
│   ├── main.py                 # Application entry point
│   ├── app_info.py             # Version, build, and About metadata
│   ├── core/                   # UI-independent DICOM, geometry, state, and source services
│   │   ├── dicom_parser.py     # DICOM series loading via pydicom
│   │   ├── dicomdir_index.py   # Safe read-only DICOMDIR indexing
│   │   ├── local_source.py     # Typed local-source controller and recent studies
│   │   ├── layout_presets.py   # Transactional built-in and user layouts
│   │   ├── settings_registry.py# Typed settings and apply policies
│   │   ├── storage_cleanup.py  # Whitelist-based cache/recovery cleanup
│   │   ├── study_model.py      # Stable Patient → Study → Series hierarchy
│   │   ├── sync_manager.py     # Patient-space cross-view synchronization
│   │   └── volume_geometry.py  # Volume geometry and MPR resampling
│   ├── demo/                   # Offline catalog, deterministic generator, manifest, and service
│   ├── i18n/                   # YAML sources and compiled JSON runtime catalogs
│   ├── icons/                  # Theme-aware SVG resources and application artwork
│   ├── performance/            # Reproducible loading/rendering baselines
│   ├── themes/                 # UI, ROI, and measurement TOML themes
│   ├── ui/
│   │   ├── main_window.py      # Workspace stack and application orchestration
│   │   ├── main_toolbar.py     # Adaptive reading toolbar
│   │   ├── start_center.py     # Study launch center
│   │   ├── media_browser.py    # Read-only local-media selector
│   │   ├── mpr_workspace.py    # Orthogonal MPR console
│   │   ├── multi_viewer_grid.py# 2D grid and special layouts
│   │   ├── panels/             # Series navigator and DICOM tags
│   │   ├── dialogs/            # Settings and workflow dialogs
│   │   ├── tools/              # Pointer, ROI, distance, and angle tools
│   │   └── widgets/            # Reusable view and layout widgets
│   └── utils/                  # Settings, themes, resources, logging, and i18n
├── tests/                      # Unit, integration, UI, geometry, and release tests
├── translation_tools/          # YAML validation and JSON catalog compiler
├── MedImager.spec              # PyInstaller build definition
├── pyproject.toml              # Package metadata and dependencies
└── uv.lock                     # Reproducible dependency lock
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

    Open a local source directly, or launch a deterministic example for UI automation:
    ```bash
    uv run python medimager/main.py "D:\DICOM\Study"
    uv run python medimager/main.py --demo ct_multiphase
    # --demo also accepts mr_brain and geometry_lab
    ```

    Run the full test suite:
    ```bash
    uv run pytest
    ```

    Record the release-scale v2.6 MPR baseline (512×512×500 CT):
    ```bash
    uv run python -m medimager.performance.baseline --slices 500 --rows 512 --cols 512 --repeats 1 --output performance_baseline_v2.6.json
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

    Main viewport controls:

    | Action | Mouse / shortcut |
    | --- | --- |
    | Select, move, or edit ROI/distance/angle annotations | Pointer tool + left drag; drag a selected anchor to resize |
    | Browse slices | Mouse wheel, `Page Up` / `Page Down`; `Home` / `End` for first / last |
    | Pan | Pan toolbar mode + left drag, or `Shift` + left drag in Pointer mode |
    | Zoom | Zoom toolbar mode + left drag, or `Ctrl` + mouse wheel |
    | Window width/level | W/L toolbar mode + left drag, or choose a DICOM/preset window |
    | Cine play/pause | `Space` |
    | Fit / actual pixels | `F` / `1` |
    | Cancel current creation or interaction | `Esc` |
    | Save / Save As / Save all annotations | `Ctrl+S` / `Ctrl+Shift+S` / `Ctrl+Alt+S` |

    Annotation edits are tracked per series. Sidecar JSON is associated with the source series, and a crash-recovery draft can be restored on the next application launch. Removing a dirty series offers **Save and remove**, **Discard and remove**, or **Cancel**.

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
