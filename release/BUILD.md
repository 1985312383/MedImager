# MedImager 打包文档

本文档说明如何为 MedImager 项目设置开发环境和进行应用程序打包。

## 开发环境设置

### 1. 安装 uv 包管理器

首先确保已安装 uv 包管理器：

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 克隆项目并设置环境

```bash
# 克隆项目
git clone <repository-url>
cd MedImager

# 使用 uv 安装完整开发环境（包括开发依赖）
uv sync --dev

# 激活虚拟环境（跨平台）
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
# 或者直接使用 uv run 命令无需手动激活
```

### 3. 运行开发版本

```bash
# 直接运行
uv run python medimager/main.py

# 或者激活环境后运行
python medimager/main.py
```

## 应用程序打包

### 前置要求

1. **UPX 压缩工具**（可选，用于减小可执行文件大小）
   - 下载地址：https://github.com/upx/upx/releases
   - 解压到合适位置，记录路径

2. **确保开发环境已正确设置**
   ```bash
   uv sync --dev
   ```

### 打包命令

使用以下命令进行打包：

```bash
# Windows 命令
uv run pyinstaller ^
  --noconfirm ^
  --onefile ^   # --onedir
  --windowed ^   # --console 
  --name "MedImager" ^
  --icon "medimager/icons/favicon.ico" ^
  --upx-dir "{UPX_PATH}" ^
  --clean ^
  --add-data "medimager;medimager/" ^
  "medimager/main.py"

# Linux/macOS 命令
uv run pyinstaller \
  --noconfirm \
  --onefile \   # --onedir
  --windowed \   # --console 
  --name "MedImager" \
  --icon "medimager/icons/favicon.ico" \
  --upx-dir "{UPX_PATH}" \
  --clean \
  --add-data "medimager:medimager/" \
  "medimager/main.py"
```

### 参数说明

- `--noconfirm`: 自动确认覆盖现有文件
- `--onedir`: 创建包含所有依赖的目录（而非单文件）
- `--console`: 保留控制台窗口（用于调试）
- `--name`: 指定可执行文件名称（避免默认的 main.exe）
- `--icon`: 指定应用程序图标（相对路径）
- `--upx-dir`: UPX 压缩工具路径，请替换 `{UPX_PATH}` 为实际路径（可选）
- `--clean`: 清理临时文件
- `--add-data`: 添加资源文件到打包结果（Windows使用分号`;`分隔，Linux/macOS使用冒号`:`分隔）

### 打包输出

打包完成后，可执行文件位于：
```
# Windows
dist/MedImager/MedImager.exe

# Linux/macOS
dist/MedImager/MedImager
```

### 注意事项

1. **路径配置**：
   - 命令使用相对路径，请在项目根目录下执行
   - 将 `{UPX_PATH}` 替换为实际的 UPX 工具路径，例如：
     - Windows: `C:\tools\upx-4.2.1-win64`
     - Linux: `/usr/local/bin/upx` 或 `/opt/upx`
     - macOS: `/usr/local/bin/upx` 或通过 Homebrew 安装的路径
     - 如果没有 UPX，可以移除 `--upx-dir` 参数

2. **可执行文件命名**：
   - 使用 `--name "MedImager"` 参数将生成 `MedImager.exe`
   - 避免了默认的 `main.exe` 命名

3. **资源文件**：`--add-data` 参数确保所有必要的资源文件（图标、测试数据等）都被包含在打包结果中

4. **依赖管理**：项目使用 `pyproject.toml` 管理依赖，开发依赖和打包工具已分离

5. **测试打包结果**：
   ```bash
   # Windows
   .\dist\MedImager\MedImager.exe
   
   # Linux/macOS
   ./dist/MedImager/MedImager
   ```

## 故障排除

### 常见问题

1. **找不到资源文件**
   - 确保 `--add-data` 参数正确
   - 检查代码中的资源路径处理

2. **缺少依赖**
   - 运行 `uv sync --dev` 确保所有依赖已安装
   - 检查 PyInstaller 的隐藏导入

3. **UPX 压缩失败**
   - 检查 UPX 工具路径是否正确
   - 可以移除 `--upx-dir` 参数跳过压缩

### 调试模式

如需调试打包问题，可以添加以下参数：

```bash
# Windows
uv run pyinstaller ^
  --debug=all ^
  --log-level=DEBUG ^
  # ... 其他参数

# Linux/macOS
uv run pyinstaller \
  --debug=all \
  --log-level=DEBUG \
  # ... 其他参数
```

## 自动化发布流程

### GitHub Actions 自动发布（推荐）

项目配置了 GitHub Actions 工作流，支持自动化构建和发布：

#### 方式一：标签触发
```bash
# 创建并推送版本标签
git tag v1.0.0
git push origin v1.0.0
```

#### 方式二：手动触发
1. 在 GitHub 仓库页面点击 "Actions" 标签
2. 选择 "Build and Release MedImager" 工作流
3. 点击 "Run workflow"
4. 输入版本号（如 v1.0.0）
5. 选择是否标记为预览版本

工作流将自动完成：
- 设置 Python 3.11 环境
- 安装 uv 和项目依赖
- 下载 UPX 工具
- 构建单文件应用程序（无控制台）
- 创建发布包和 GitHub Release
- 自动标记为 Preview Release

### 本地快速发布

推荐使用自动化脚本进行发布：

```bash
# 运行自动化发布脚本
uv run python release/build_release.py
```

### UPX 压缩配置

脚本支持两种 UPX 配置方式：

**方式1: 预设路径（推荐用于自动化构建）**
- 编辑 `release/build_release.py` 中的 `find_upx_path()` 函数
- 设置 `upx_path` 变量为您的 UPX 安装路径
- 例如：`upx_path = 'C:\\tools\\upx-4.2.1-win64'`

**方式2: 交互式输入（推荐用于手动构建）**
- 保持 `upx_path = None`
- 运行脚本时会自动提示配置 UPX
- 支持实时下载指导和路径验证

### 发布流程特性

脚本将自动完成：
1. 清理旧的构建文件
2. 交互式 UPX 配置（如未预设）
3. 使用 PyInstaller 打包单文件应用程序（无控制台）
4. 智能 UPX 压缩（可选）
5. 创建发布目录和 ZIP 包
6. 生成版本信息文件

### 发布包内容

自动化脚本生成的发布包包含：
- `MedImager.exe`（Windows）或 `MedImager`（Linux/macOS）- 主程序（单文件，无控制台）
- `README.md` / `README_zh.md` - 使用说明
- `LICENSE` - 许可证文件
- `BUILD.md` - 构建文档
- `VERSION.txt` - 版本信息

### 发布到 GitHub

1. 运行自动化脚本后，获得 ZIP 发布包
2. 在 GitHub 仓库创建新的 Release
3. 上传 ZIP 文件作为 Release Asset
4. 标记为 "Pre-release" （预览版本）
5. 填写 Release Notes

### 手动发布配置

如需手动控制发布过程，可以使用以下命令构建无控制台版本：

```bash
# Windows
uv run pyinstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "MedImager" ^
  --icon "medimager/icons/favicon.ico" ^
  --upx-dir "{UPX_PATH}" ^
  --clean ^
  --add-data "medimager;medimager/" ^
  "medimager/main.py"

# Linux/macOS
uv run pyinstaller \
  --noconfirm \
  --onefile \
  --windowed \
  --name "MedImager" \
  --icon "medimager/icons/favicon.ico" \
  --upx-dir "{UPX_PATH}" \
  --clean \
  --add-data "medimager:medimager/" \
  "medimager/main.py"
```

关键差异：
- `--onefile`: 生成单个可执行文件
- `--windowed`: 无控制台窗口（替代 `--console`）

## 发布准备

打包完成后，建议进行以下测试：

1. 在干净的系统上测试运行
2. 验证所有功能正常工作
3. 检查资源文件加载
4. 测试 DICOM 文件加载功能
5. 确认无控制台窗口干扰

---

更多信息请参考：
- [PyInstaller 官方文档](https://pyinstaller.readthedocs.io/)
- [uv 包管理器文档](https://docs.astral.sh/uv/)