#!/usr/bin/env python3
"""
MedImager 自动化发布脚本

此脚本自动化构建 MedImager 的发布版本，包括：
1. 清理旧的构建文件
2. 使用 PyInstaller 打包应用程序
3. 创建发布包
4. 生成版本信息
"""

import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime
import toml


def get_project_info():
    """从 pyproject.toml 获取项目信息"""
    try:
        with open('pyproject.toml', 'r', encoding='utf-8') as f:
            config = toml.load(f)
        
        project = config.get('project', {})
        return {
            'name': project.get('name', 'medimager'),
            'version': project.get('version', '1.0.0'),
            'description': project.get('description', '')
        }
    except Exception as e:
        print(f"警告: 无法读取项目信息: {e}")
        return {'name': 'medimager', 'version': '1.0.0', 'description': ''}


def clean_build_dirs():
    """清理构建目录"""
    print("🧹 清理构建目录...")
    dirs_to_clean = ['build', 'dist', '__pycache__']
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"   删除: {dir_name}")
    
    # 清理 .spec 文件
    for spec_file in Path('.').glob('*.spec'):
        spec_file.unlink()
        print(f"   删除: {spec_file}")


def find_upx_path():
    """尝试找到 UPX 工具路径"""
    common_paths = [
        'C:\\tools\\upx',
        'C:\\upx',
        'D:\\tools\\upx',
        'E:\\tools\\upx'
    ]
    
    # 检查常见路径
    for base_path in common_paths:
        if os.path.exists(base_path):
            # 查找版本目录
            for item in os.listdir(base_path):
                full_path = os.path.join(base_path, item)
                if os.path.isdir(full_path) and 'upx' in item.lower():
                    return full_path
    
    # 检查当前目录
    for item in os.listdir('.'):
        if os.path.isdir(item) and 'upx' in item.lower():
            return os.path.abspath(item)
    
    return None


def build_application(project_info, use_upx=True):
    """构建应用程序"""
    print("🔨 开始构建应用程序...")
    
    # 基础命令
    cmd = [
        'uv', 'run', 'pyinstaller',
        '--noconfirm',
        '--onefile',  # 单文件模式
        '--windowed',  # 无控制台窗口
        '--name', 'MedImager',
        '--icon', 'medimager/icons/favicon.ico',
        '--clean',
        '--add-data', 'medimager;medimager/',
        'medimager/main.py'
    ]
    
    # 尝试添加 UPX 压缩
    if use_upx:
        upx_path = find_upx_path()
        if upx_path:
            cmd.extend(['--upx-dir', upx_path])
            print(f"   使用 UPX 压缩: {upx_path}")
        else:
            print("   警告: 未找到 UPX 工具，跳过压缩")
    
    print(f"   执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ 构建成功!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 构建失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False


def create_release_package(project_info):
    """创建发布包"""
    print("📦 创建发布包...")
    
    version = project_info['version']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 创建发布目录
    release_dir = f"release_v{version}_{timestamp}"
    os.makedirs(release_dir, exist_ok=True)
    
    # 复制可执行文件
    exe_src = 'dist/MedImager.exe'
    exe_dst = f"{release_dir}/MedImager.exe"
    
    if os.path.exists(exe_src):
        shutil.copy2(exe_src, exe_dst)
        print(f"   复制可执行文件: {exe_dst}")
    else:
        print(f"❌ 找不到可执行文件: {exe_src}")
        return None
    
    # 复制文档文件
    docs_to_copy = ['README.md', 'README_zh.md', 'LICENSE', 'BUILD.md']
    for doc in docs_to_copy:
        if os.path.exists(doc):
            shutil.copy2(doc, release_dir)
            print(f"   复制文档: {doc}")
    
    # 创建版本信息文件
    version_info = f"""MedImager v{version} - Preview Release

构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
描述: {project_info['description']}

这是一个预览版本，可能包含未完全测试的功能。
如有问题请反馈到项目仓库。

使用方法:
1. 直接运行 MedImager.exe
2. 支持拖拽 DICOM 文件或文件夹
3. 详细使用说明请参考 README.md
"""
    
    with open(f"{release_dir}/VERSION.txt", 'w', encoding='utf-8') as f:
        f.write(version_info)
    
    # 创建 ZIP 包
    zip_name = f"MedImager_v{version}_preview_{timestamp}.zip"
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(release_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arc_name = os.path.relpath(file_path, release_dir)
                zipf.write(file_path, arc_name)
    
    print(f"✅ 发布包创建完成: {zip_name}")
    return zip_name, release_dir


def main():
    """主函数"""
    print("🚀 MedImager 自动化发布流程")
    print("=" * 50)
    
    # 检查是否在项目根目录
    if not os.path.exists('medimager/main.py'):
        print("❌ 请在项目根目录下运行此脚本")
        sys.exit(1)
    
    # 获取项目信息
    project_info = get_project_info()
    print(f"📋 项目: {project_info['name']} v{project_info['version']}")
    
    try:
        # 1. 清理构建目录
        clean_build_dirs()
        
        # 2. 构建应用程序
        if not build_application(project_info):
            print("❌ 构建失败，终止发布流程")
            sys.exit(1)
        
        # 3. 创建发布包
        result = create_release_package(project_info)
        if result:
            zip_name, release_dir = result
            print("\n🎉 发布流程完成!")
            print(f"📁 发布目录: {release_dir}")
            print(f"📦 发布包: {zip_name}")
            print("\n📝 下一步:")
            print("1. 测试可执行文件")
            print("2. 上传到 GitHub Releases")
            print("3. 标记为 Preview Release")
        else:
            print("❌ 创建发布包失败")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()