@echo off
chcp 65001 >nul
echo.
echo ========================================
echo    MedImager 自动化发布脚本
echo ========================================
echo.

:: 检查是否在正确的目录
if not exist "medimager\main.py" (
    echo ❌ 错误: 请在项目根目录下运行此脚本
    echo    当前目录: %CD%
    echo    需要包含: medimager\main.py
    pause
    exit /b 1
)

:: 运行 Python 发布脚本
echo 🚀 开始自动化发布流程...
echo.
uv run python build_release.py

:: 检查执行结果
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ 发布流程完成!
    echo 📁 请检查生成的发布文件
) else (
    echo.
    echo ❌ 发布流程失败
    echo 💡 请检查错误信息并重试
)

echo.
echo 按任意键退出...
pause >nul