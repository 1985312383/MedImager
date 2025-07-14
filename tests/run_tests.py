#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试运行脚本

用于CI/CD流程中运行所有测试并生成覆盖度报告
"""

import sys
import os
import subprocess
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_pytest_with_coverage():
    """使用pytest运行测试并生成覆盖度报告"""
    print("="*60)
    print("运行测试套件 - 包含代码覆盖度分析")
    print("="*60)
    
    # 切换到项目根目录
    os.chdir(project_root)
    
    # pytest命令参数
    pytest_args = [
        "python", "-m", "pytest",
        "tests/",  # 测试目录
        "-v",  # 详细输出
        "--tb=short",  # 简短的traceback
        "--cov=medimager",  # 覆盖度分析目标包
        "--cov-report=html:htmlcov",  # HTML覆盖度报告
        "--cov-report=term-missing",  # 终端显示缺失行
        "--cov-report=xml:coverage.xml",  # XML覆盖度报告（用于CI）
        "--cov-fail-under=70",  # 覆盖度低于70%时失败
        "--durations=10",  # 显示最慢的10个测试
    ]
    
    try:
        # 运行pytest
        result = subprocess.run(pytest_args, capture_output=False, text=True)
        
        if result.returncode == 0:
            print("\n" + "="*60)
            print("🎉 所有测试通过！")
            print("="*60)
            print("\n覆盖度报告已生成：")
            print("- HTML报告: htmlcov/index.html")
            print("- XML报告: coverage.xml")
        else:
            print("\n" + "="*60)
            print("❌ 测试失败或覆盖度不足")
            print("="*60)
        
        return result.returncode
        
    except FileNotFoundError:
        print("❌ 错误：未找到pytest。请确保已安装pytest和pytest-cov：")
        print("pip install pytest pytest-cov")
        return 1
    except Exception as e:
        print(f"❌ 运行测试时发生错误: {e}")
        return 1


def run_individual_tests():
    """运行单个测试文件（用于调试）"""
    print("\n" + "="*60)
    print("运行单个测试文件")
    print("="*60)
    
    test_files = [
        "test_sync.py",
        "test_main_window.py",
        "test_multi_series_components.py"
    ]
    
    results = {}
    
    for test_file in test_files:
        test_path = project_root / "tests" / test_file
        if test_path.exists():
            print(f"\n运行 {test_file}...")
            try:
                result = subprocess.run(
                    ["python", str(test_path)],
                    cwd=project_root,
                    capture_output=True,
                    text=True
                )
                results[test_file] = result.returncode == 0
                if result.returncode == 0:
                    print(f"✅ {test_file} 通过")
                else:
                    print(f"❌ {test_file} 失败")
                    if result.stderr:
                        print(f"错误信息: {result.stderr}")
            except Exception as e:
                print(f"❌ 运行 {test_file} 时发生错误: {e}")
                results[test_file] = False
        else:
            print(f"⚠️  {test_file} 不存在")
            results[test_file] = False
    
    # 总结结果
    print("\n" + "="*60)
    print("单个测试结果总结")
    print("="*60)
    for test_file, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_file}: {status}")
    
    return all(results.values())


def main():
    """主函数"""
    print("MedImager 测试套件")
    print("="*60)
    
    # 检查是否安装了pytest
    try:
        subprocess.run(["python", "-m", "pytest", "--version"], 
                      capture_output=True, check=True)
        use_pytest = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  未检测到pytest，将使用单个测试文件运行模式")
        use_pytest = False
    
    if use_pytest:
        # 使用pytest运行（推荐用于CI/CD）
        exit_code = run_pytest_with_coverage()
    else:
        # 使用单个文件运行（备用方案）
        success = run_individual_tests()
        exit_code = 0 if success else 1
    
    return exit_code


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)