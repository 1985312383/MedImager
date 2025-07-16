#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国际化检查脚本
检查UI代码中包含中文字符串但未使用self.tr()的代码行
"""

import os
import re
from pathlib import Path

def contains_chinese(text):
    """检查文本是否包含中文字符"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))

def is_ui_text(line):
    """检查是否为需要国际化的UI文本"""
    stripped = line.strip()
    
    # 跳过空行
    if not stripped:
        return False
        
    # 跳过注释行
    if stripped.startswith('#'):
        return False
        
    # 跳过文档字符串
    if '"""' in stripped or "'''" in stripped:
        return False
        
    # 跳过所有日志相关的行
    if 'logger.' in stripped or 'logging.' in stripped:
        return False
        
    # 跳过f字符串格式的日志（包含方括号的通常是日志）
    if re.search(r'f".*\[.*\].*"', stripped):
        return False
        
    # 跳过普通字符串格式的日志
    if re.search(r'".*\[.*\].*"', stripped):
        return False
        
    # 跳过函数/类定义和参数说明
    if re.match(r'\s*(def |class |Args:|Returns?:|Raises?:|Note:|Example:|Parameters?:)', stripped):
        return False
        
    # 跳过变量赋值中的注释性文本
    if re.match(r'\s*\w+\s*=.*#', stripped):
        return False
        
    # 跳过CSS样式注释
    if re.match(r'\s*/\*.*\*/', stripped):
        return False
        
    # 只检查可能包含UI文本的行
    ui_patterns = [
        r'setText\(',
        r'setWindowTitle\(',
        r'setToolTip\(',
        r'setStatusTip\(',
        r'setPlaceholderText\(',
        r'addAction\(',
        r'QAction\(',
        r'QLabel\(',
        r'QPushButton\(',
        r'QMessageBox\.',
        r'QInputDialog\.',
        r'QFileDialog\.',
        r'setTabText\(',
        r'addTab\(',
        r'setHeaderLabels\(',
        r'QTreeWidgetItem\(',
        r'QListWidgetItem\(',
        r'QTableWidgetItem\(',
        r'raise.*Exception\(',
        r'raise.*Error\(',
    ]
    
    for pattern in ui_patterns:
        if re.search(pattern, stripped):
            return True
            
    return False

def has_tr_wrapper(line):
    """检查行是否已经使用了self.tr()包装"""
    return 'self.tr(' in line or 'tr(' in line

def check_file_i18n(file_path):
    """检查单个文件的国际化情况"""
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line_num, line in enumerate(lines, 1):
            # 检查是否为UI文本
            if is_ui_text(line):
                # 检查是否包含中文
                if contains_chinese(line):
                    # 检查是否已经使用了tr包装
                    if not has_tr_wrapper(line):
                        issues.append({
                            'line_num': line_num,
                            'line': line.strip(),
                            'file': file_path
                        })
                    
    except Exception as e:
        print(f"读取文件失败 {file_path}: {e}")
        
    return issues

def check_directory_i18n(directory):
    """检查目录下所有Python文件的国际化情况"""
    all_issues = []
    
    for root, dirs, files in os.walk(directory):
        # 跳过一些不需要检查的目录
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.pytest_cache', 'logs', 'tests']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                issues = check_file_i18n(file_path)
                all_issues.extend(issues)
                
    return all_issues

def main():
    """主函数"""
    # 检查medimager目录 - 修改为相对于父目录的路径
    medimager_dir = Path(__file__).parent.parent / 'medimager'
    
    if not medimager_dir.exists():
        print(f"目录不存在: {medimager_dir}")
        return
        
    print(f"正在检查UI目录: {medimager_dir}")
    print("="*60)
    
    issues = check_directory_i18n(medimager_dir)
    
    if not issues:
        print("[OK] 未发现需要国际化的UI中文字符串")
        return
        
    print(f"🔍 发现 {len(issues)} 个需要国际化的UI中文字符串:")
    print()
    
    # 按文件分组显示
    current_file = None
    for issue in issues:
        if issue['file'] != current_file:
            current_file = issue['file']
            print(f" {os.path.relpath(current_file, medimager_dir)}")
            
        print(f"  第 {issue['line_num']} 行: {issue['line']}")
        print()

if __name__ == '__main__':
    main()