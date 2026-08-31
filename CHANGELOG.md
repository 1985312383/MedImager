# Changelog

## 2.6.0 - 2026-08-31

### Visual study workbench
- Added a first-run study center for DICOM folders, multiple folders, DICOMDIR media, ordinary images, privacy-aware recent studies, and three offline example studies.
- Added a read-only Patient → Study → Series DICOMDIR browser with explicit reporting for invalid records, missing references, unsupported objects, and unsafe media paths.
- Reworked the series navigator around a filterable Qt item model with compact/card density, loading and orientation filters, binding badges, and one-click comparison layouts for up to twelve series.
- Added a transactional layout gallery with clinical presets, special layouts, splitter-ratio persistence, favorites/recent choices, and geometry-only user presets.

### Reading controls, settings, and privacy
- Grouped the 24 px adaptive toolbar into browse, measure, compare, and advanced workflows, with density, labels, visibility, and group-order preferences.
- Unified toolbar controls as orientation-aware square tiles, centered custom widgets on a shared vertical axis, reflowed Cine controls, and separated active-tool, toggle, and synchronization state styling across light and dark themes.
- Expanded orthogonal MPR with color-and-line-style plane identity, per-plane position controls, three-column and 1+2 arrangements, linked state, and compact viewport shortcuts.
- Added a typed settings registry and staged Settings Center 2.0 flow with search, per-page defaults, apply policies, storage usage, and safe atomic settings import/export.
- Added persistent screen privacy presentation, session aliases, DICOM tag copy protection, and whitelist-based cache cleanup that preserves workspaces, drafts, and annotation sidecars.

### Offline examples and quality
- Added deterministic CT Multiphase, MR Brain, and Geometry Lab studies generated asynchronously from fixed seeds and de-identified UUID5-derived DICOM UIDs.
- Added validated, atomic example caching without shipping patient pixels in the installer; cached studies can be regenerated or cleared independently.
- Upgraded workspace and recent-study persistence schemas while avoiding raw patient identifiers and DICOM UIDs in saved navigation metadata.
- Added five-language UI coverage plus focused DICOMDIR, local-source, settings, privacy, layout, example-data, visual-regression, and packaging checks.

## 2.5.0 - 2026-08-30

### Study workspace and navigation
- Added a stable Patient → Study → Series inspection model and a default study browser with dates, modality summaries, protocol/body-part metadata, orientation, thumbnails, drag binding, and double-click assignment.
- Added study-scoped hanging protocols for overview, CT phase comparison, MR T1/T2/FLAIR/DWI, and the current-series MPR workflow.
- Added per-study restoration of layout, series bindings, active pane, synchronization mode, slice, WL/WW, zoom, pan, invert, and interpolation state.

### Patient-space synchronization
- Upgraded automatic slice synchronization to preserve millimetre-based LPS matching across reversed ordering and anisotropic series.
- Replaced full-pane cursor crosshairs with geometrically clipped image-plane intersection lines and a shared patient-space 3D cursor.
- Refuses automatic spatial linkage when patient identity or Frame of Reference is missing/incompatible; independent display state remains available when position sync is off.

### Performance, privacy, and quality
- Moved thumbnail VOI rendering and resize work off the GUI thread, with bounded persistent thumbnail caching.
- Added active-study diagnostic load ordering and background ±2-slice display prefetch through the shared render LRU.
- Removed patient names from series-manager logs and keyed saved workspaces by a hash of Study Instance UID.
- Added focused hierarchy, hanging-protocol, localizer geometry, cache, prefetch, and thumbnail regressions in addition to the existing v2.4 MPR suite.

## 2.4.0 - 2026-08-29

### Features
- Added a patient-space volume geometry model with explicit voxel-to-LPS transforms and structured compatibility diagnostics.
- Added asynchronous axial, coronal, and sagittal MPR reconstruction powered by SimpleITK.
- Added a main-window MPR workspace with linked 3D cursor, true orthogonal localizer lines, wheel navigation, cancel support, and viewport maximization.
- Added a pure RenderRequest/RenderedFrame display pipeline shared by 2D and MPR rendering.
- Upgraded annotation persistence to patient-space DICOM LPS schema v2; legacy schema v1 files are rejected without mutation.

### Correctness and safety
- Rejects MPR for duplicate/missing/non-uniform slices, gantry tilt, mixed orientations, mixed temporal/stack dimensions, color data, and unsupported modalities.
- Adds memory preflight, background cancellation, malformed-coordinate validation, geometry golden tests, and packaging support for SimpleITK.

## 2.3.0 - 2026-08-28

### 特性
- 2.0 合并 1.0 与 1.x 成果，形成稳定的 2D DICOM 基线版本
- 支持 DICOM 文件/文件夹加载、普通图片加载、多序列管理、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出、当前切片图像导出和标注持久化
- 内置专业合成 DICOM 测试覆盖与大序列加载/显示性能基准
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v2.2.0 到 v2.3.0

- 50a62bf feat: modernize DICOM viewing and annotation workflows (1985312383)

## 2.2.0 - 2026-05-09

### 特性
- 2.0 合并 1.0 与 1.x 成果，形成稳定的 2D DICOM 基线版本
- 支持 DICOM 文件/文件夹加载、普通图片加载、多序列管理、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出、当前切片图像导出和标注持久化
- 内置专业合成 DICOM 测试覆盖与大序列加载/显示性能基准
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v2.1.0 到 v2.2.0

- 70536c7 Switch i18n to YAML/JSON catalogs (1985312383)

## 2.1.0 - 2026-05-08

### 特性
- 2.0 合并 1.0 与 1.x 成果，形成稳定的 2D DICOM 基线版本
- 支持 DICOM 文件/文件夹加载、普通图片加载、多序列管理、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出、当前切片图像导出和标注持久化
- 内置专业合成 DICOM 测试覆盖与大序列加载/显示性能基准
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v2.0.0 到 v2.1.0

- 2aeeb4f Add configurable settings, theme colors, and ROI visuals (柯慕灵)
- 9c0ea69 Support non-rectangular layout presets and theming (柯慕灵)
- d483374 Update banner.png (柯慕灵)

## 2.0.0 - 2026-05-08

### 特性
- 2.0 合并 1.0 与 1.x 成果，形成稳定的 2D DICOM 基线版本
- 支持 DICOM 文件/文件夹加载、普通图片加载、多序列管理、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出、当前切片图像导出和标注持久化
- 内置专业合成 DICOM 测试覆盖与大序列加载/显示性能基准
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v1.2.1 到 v2.0.0

- c8c8c84 Update README files for v2.0 baseline (柯慕灵)
- 49f7445 Sync view bindings and slice selection; add tests (柯慕灵)
- 49835af Add annotation persistence and performance baseline (柯慕灵)

## 1.2.1 - 2026-05-08

### 特性
- 研究与教学用途的基础 2D DICOM 查看器
- 支持 DICOM 文件/文件夹加载、普通图片加载、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出和当前切片图像导出
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v1.2.0 到 v1.2.1

- a21eead Merge branch 'main' of https://github.com/1985312383/MedImager (柯慕灵)
- 9249f23 Update release.yml (柯慕灵)
- 99708ff docs: update changelog for v1.2.0 (github-actions[bot])
- 0a6eb3f Delete build-release.yml (柯慕灵)

## 1.2.0 - 2026-05-08

### 特性
- 研究与教学用途的基础 2D DICOM 查看器
- 支持 DICOM 文件/文件夹加载、普通图片加载、多视图显示和基础测量
- 支持 ROI 统计、窗宽窗位、当前视图截图导出和当前切片图像导出
- Release 构建会在关于对话框中显示版本、项目地址和最近一次 release changelog

### 使用方法
1. 下载并解压 ZIP 文件
2. 运行 `MedImager.exe`
3. 通过菜单打开 DICOM 文件、DICOM 文件夹或普通图片
4. 使用窗宽窗位、ROI、测量和导出工具完成基础查看与分析

### 本次 Release Commit 记录
从 v1.1.0 到 v1.2.0

System.Object[]

## 1.1.0 - 2026-02-15

### 特性
- 增加角度测量、视图转换、工具UI等功能

### 修复

### 使用方法
1. 启动 MedImager。
2. 打开 DICOM 文件、DICOM 文件夹或普通图片文件。
3. 使用窗宽窗位、ROI、测量、导出等工具完成基础查看和分析。
