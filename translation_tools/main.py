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
import locale
import codecs

# 设置控制台编码
if sys.platform == 'win32':
    # Windows下设置控制台编码为UTF-8
    try:
        # 尝试设置控制台代码页为UTF-8
        os.system('chcp 65001 >nul 2>&1')
        # 重新配置stdout和stderr
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())
    except:
        # 如果失败，使用系统默认编码
        pass



def run_script(script_name: str, description: str, args: list = None) -> bool:
    """
    运行指定的脚本
    
    Args:
        script_name: 脚本文件名
        description: 脚本描述
        args: 额外的命令行参数
        
    Returns:
        bool: 是否成功运行
    """
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Script: {script_name}")
    if args:
        print(f"Args: {' '.join(args)}")
    print(f"{'='*60}")
    
    script_path = Path(__file__).parent / script_name
    
    if not script_path.exists():
        print(f"Error: Script file not found {script_path}")
        return False
    
    try:
        # 构建命令
        cmd = [sys.executable, str(script_path)]
        if args:
            cmd.extend(args)
        
        # 运行脚本 - 实时显示输出
        # 设置环境变量确保子进程使用UTF-8编码
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        if sys.platform == 'win32':
            env['PYTHONUTF8'] = '1'
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        
        # 实时读取并显示输出
        output_lines = []
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                try:
                    # 尝试正确显示输出
                    print(output.rstrip())
                except UnicodeEncodeError:
                    # 如果编码失败，使用替代字符
                    print(output.encode('utf-8', errors='replace').decode('utf-8').rstrip())
                output_lines.append(output)
        
        # 等待进程完成
        return_code = process.poll()
        
        if return_code == 0:
            print(f"[OK] {description} 完成")
            return True
        else:
            print(f"[FAIL] {description} failed (exit code: {return_code})")
            return False
            
    except Exception as e:
        print(f"Error running script: {e}")
        return False

def main():
    """
    主函数 - 按顺序运行所有翻译工具
    """
    print("MedImager Translation Toolchain")
    print("=" * 60)
    print("This tool will run the following scripts in order:")
    print("1. Check i18n issues")
    print("2. Auto generate translation files")
    print("3. Translate TS files")
    print("4. Compile translation files")
    print("\nStarting process...")
    
    # 定义要运行的脚本列表 (脚本名, 描述, 参数列表)
    # 构建源文件的绝对路径
    source_ts_file = Path(__file__).parent.parent / 'medimager' / 'translations' / 'zh_CN.ts'

    scripts = [
         ("check_i18n.py", "检查国际化问题", None),
         ("auto_translation_generator.py", "自动生成翻译文件", None),
         ("translate_ts.py", "翻译TS文件", [str(source_ts_file), "--all"]),
         ("compile_translations.py", "编译翻译文件", None)
     ]
    
    success_count = 0
    total_count = len(scripts)
    
    start_time = time.time()
    
    # 按顺序运行每个脚本
    for i, (script_name, description, args) in enumerate(scripts, 1):
        print(f"\n[{i}/{total_count}] Starting: {description}")
        
        if run_script(script_name, description, args):
            success_count += 1
        else:
            print(f"\nWarning: {description} execution failed")
            user_input = input("Continue with next script? (y/n): ").strip().lower()
            if user_input not in ['y', 'yes']:
                print("User chose to stop execution")
                break
        
        # 在脚本之间添加短暂延迟
        if i < total_count:
            time.sleep(1)
    
    end_time = time.time()
    duration = end_time - start_time
    
    # 输出总结
    print(f"\n{'='*60}")
    print("Execution Summary")
    print(f"{'='*60}")
    print(f"Total scripts: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")
    print(f"Total time: {duration:.2f} seconds")
    
    if success_count == total_count:
        print("\n[SUCCESS] All translation tools executed successfully!")
        print("\nTranslation files are ready for use in the application.")
        print("\nGenerated files:")
        
        # 检查生成的文件
        translations_dir = Path(__file__).parent.parent / "medimager" / "translations"
        if translations_dir.exists():
            for file_path in translations_dir.glob("*.ts"):
                print(f"  - {file_path.name}")
            for file_path in translations_dir.glob("*.qm"):
                print(f"  - {file_path.name}")
    else:
        print("\n[WARNING] Some tools failed to execute. Please check error messages and re-run.")
    
    print("\nPress any key to exit...")
    input()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nUser interrupted execution")
    except Exception as e:
        print(f"\n\nUnexpected error during execution: {e}")
        import traceback
        traceback.print_exc()