#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译文件编译脚本
将现有的 .ts 文件编译为 .qm 文件
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil


def find_qt_tool(tool_name: str) -> str:
    """在常见的 PySide6 和系统路径中查找 Qt 工具 (lrelease)"""
    # 1. 检查 PySide6 的安装路径
    try:
        import PySide6
        pyside6_dir = Path(PySide6.__file__).parent
        tool_path = pyside6_dir / tool_name
        if tool_path.exists():
            return str(tool_path)
    except ImportError:
        pass

    # 2. 检查系统 PATH
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path

    # 3. 在 Python Scripts 目录中查找 (Windows)
    if sys.platform == "win32":
        scripts_dir = Path(sys.prefix) / "Scripts"
        tool_path = scripts_dir / tool_name
        if tool_path.exists():
            return str(tool_path)

    return None


def compile_ts_to_qm(ts_file: Path, lrelease_path: str) -> bool:
    """使用 lrelease 将 .ts 文件编译为 .qm 文件"""
    qm_file = ts_file.with_suffix('.qm')
    command = [lrelease_path, str(ts_file), "-qm", str(qm_file)]
    
    try:
        print(f"编译: {ts_file.name} -> {qm_file.name}")
        result = subprocess.run(
            command, 
            check=True, 
            capture_output=True, 
            text=True, 
            encoding='utf-8',
            errors='ignore'  # 忽略编码错误
        )
        if result.returncode == 0:
            print(f"[OK] 编译成功: {ts_file.name} -> {qm_file.name}")
            return True
        else:
            print(f"[FAIL] 编译失败: {ts_file.name}")
            if result.stderr:
                print(f"  错误: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"[ERROR] 错误: 未找到 'lrelease' 工具。请确保它在系统PATH中或PySide6已正确安装。")
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] 编译命令执行失败: {ts_file.name}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"  错误: {e.stderr}")
        return False
    except Exception as e:
        print(f"[ERROR] 发生未知错误: {e}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("MedImager 翻译文件编译工具")
    print("=" * 60)
    
    # 翻译文件目录 - 修改为相对于父目录的路径
    translations_dir = Path(__file__).parent.parent / "medimager" / "translations"
    
    if not translations_dir.exists():
        print(f"错误: 翻译目录不存在: {translations_dir}")
        return
    
    # 查找所有 .ts 文件
    ts_files = list(translations_dir.glob("*.ts"))
    
    if not ts_files:
        print(f"错误: 在目录 {translations_dir} 中未找到 .ts 文件")
        return
    
    print(f"找到 {len(ts_files)} 个 .ts 文件:")
    for ts_file in ts_files:
        print(f"  - {ts_file.name}")
    
    # 查找 lrelease 工具
    lrelease_path = find_qt_tool("lrelease.exe" if sys.platform == "win32" else "lrelease")
    if not lrelease_path:
        print("\n错误: 未能找到 'lrelease' 工具。")
        print("请确保 PySide6 已安装，或将 Qt bin 目录添加到系统 PATH。")
        return

    print(f"\n[OK] 使用 lrelease 工具: {lrelease_path}")
    
    print("\n开始编译...")
    print("-" * 40)
    
    success_count = 0
    failed_files = []
    
    for ts_file in ts_files:
        if compile_ts_to_qm(ts_file, lrelease_path):
            success_count += 1
        else:
            failed_files.append(ts_file.name)
    
    print("-" * 40)
    print(f"编译完成!")
    print(f"总计: {len(ts_files)} 个文件")
    print(f"成功: {success_count} 个文件")
    print(f"失败: {len(failed_files)} 个文件")
    
    if failed_files:
        print(f"\n失败的文件:")
        for failed_file in failed_files:
            print(f"  - {failed_file}")
    
    # 显示编译后的文件
    qm_files = list(translations_dir.glob("*.qm"))
    if qm_files:
        print(f"\n编译后的 .qm 文件:")
        for qm_file in qm_files:
            print(f"  - {qm_file.name}")
    
    print("\n" + "=" * 60)
    print("使用说明:")
    print("=" * 60)
    print("1. 确保应用程序能正确加载 .qm 文件")
    print("2. 在应用程序中测试多语言功能")
    print("3. 如需更新翻译，请修改 .ts 文件后重新编译")
    
    if success_count == len(ts_files):
        print("\n[SUCCESS] 所有翻译文件编译成功!")
    else:
        print(f"\n[WARNING] 有 {len(failed_files)} 个文件编译失败，请检查错误信息")


if __name__ == "__main__":
    main()