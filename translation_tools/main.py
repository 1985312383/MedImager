#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译工具主程序
按顺序运行所有翻译相关的工具脚本

运行顺序:
1. check_i18n.py - 检查国际化问题
2. auto_translation_generator.py - 自动生成翻译文件
3. translate_ts.py - 翻译TS文件
4. compile_translations.py - 编译翻译文件
"""

import os
import sys
import subprocess
from pathlib import Path
import time

def run_script(script_name: str, description: str) -> bool:
    """
    运行指定的脚本
    
    Args:
        script_name: 脚本文件名
        description: 脚本描述
        
    Returns:
        bool: 是否成功运行
    """
    print(f"\n{'='*60}")
    print(f"正在运行: {description}")
    print(f"脚本: {script_name}")
    print(f"{'='*60}")
    
    script_path = Path(__file__).parent / script_name
    
    if not script_path.exists():
        print(f"错误: 找不到脚本文件 {script_path}")
        return False
    
    try:
        # 运行脚本
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'  # 处理编码错误
        )
        
        # 输出结果
        if result.stdout:
            print("输出:")
            print(result.stdout)
        
        if result.stderr:
            print("错误信息:")
            print(result.stderr)
        
        if result.returncode == 0:
            print(f"[OK] {description} 完成")
            return True
        else:
            print(f"[FAIL] {description} 失败 (退出码: {result.returncode})")
            return False
            
    except Exception as e:
        print(f"运行脚本时出错: {e}")
        return False

def main():
    """
    主函数 - 按顺序运行所有翻译工具
    """
    print("MedImager 翻译工具链")
    print("=" * 60)
    print("这个工具将按顺序运行以下脚本:")
    print("1. 检查国际化问题")
    print("2. 自动生成翻译文件")
    print("3. 翻译TS文件")
    print("4. 编译翻译文件")
    print("\n开始处理...")
    
    # 定义要运行的脚本列表
    scripts = [
        ("check_i18n.py", "检查国际化问题"),
        ("auto_translation_generator.py", "自动生成翻译文件"),
        ("translate_ts.py", "翻译TS文件"),
        ("compile_translations.py", "编译翻译文件")
    ]
    
    success_count = 0
    total_count = len(scripts)
    
    start_time = time.time()
    
    # 按顺序运行每个脚本
    for i, (script_name, description) in enumerate(scripts, 1):
        print(f"\n[{i}/{total_count}] 开始执行: {description}")
        
        if run_script(script_name, description):
            success_count += 1
        else:
            print(f"\n警告: {description} 执行失败")
            user_input = input("是否继续执行下一个脚本? (y/n): ").strip().lower()
            if user_input not in ['y', 'yes', '是']:
                print("用户选择停止执行")
                break
        
        # 在脚本之间添加短暂延迟
        if i < total_count:
            time.sleep(1)
    
    end_time = time.time()
    duration = end_time - start_time
    
    # 输出总结
    print(f"\n{'='*60}")
    print("执行总结")
    print(f"{'='*60}")
    print(f"总计脚本: {total_count}")
    print(f"成功执行: {success_count}")
    print(f"失败数量: {total_count - success_count}")
    print(f"总耗时: {duration:.2f} 秒")
    
    if success_count == total_count:
        print("\n[SUCCESS] 所有翻译工具都成功执行完成!")
        print("\n翻译文件已准备就绪，可以在应用程序中使用。")
        print("\n生成的文件:")
        
        # 检查生成的文件
        translations_dir = Path(__file__).parent.parent / "medimager" / "translations"
        if translations_dir.exists():
            for file_path in translations_dir.glob("*.ts"):
                print(f"  - {file_path.name}")
            for file_path in translations_dir.glob("*.qm"):
                print(f"  - {file_path.name}")
    else:
        print("\n[WARNING] 部分工具执行失败，请检查错误信息并重新运行。")
    
    print("\n按任意键退出...")
    input()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断执行")
    except Exception as e:
        print(f"\n\n执行过程中出现未预期的错误: {e}")
        import traceback
        traceback.print_exc()