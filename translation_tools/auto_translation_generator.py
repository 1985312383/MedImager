#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文翻译模板生成器

遍历 medimager 目录下所有 Python 文件，提取 self.tr() 中的中文字符串，
并按照 zh_CN.ts 的 XML 格式自动生成中文翻译模板文件。
确保上下文与 self.tr() 方法匹配。
配合 translate_ts.py 工具可翻译为其他语言。
"""

import os
import re
import ast
from xml.etree import ElementTree as ET
from xml.dom import minidom
from typing import Dict, List, Set, Tuple
from pathlib import Path

def is_chinese(text: str) -> bool:
    """检查字符串是否包含中文字符"""
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
    return bool(chinese_pattern.search(text))

def extract_f_string_text(joined_str_node):
    """从 f 字符串 AST 节点中提取文本内容"""
    parts = []
    placeholder_count = 1
    
    for value in joined_str_node.values:
        if isinstance(value, ast.Str):
            parts.append(value.s)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            # 对于格式化值，使用Qt兼容的占位符格式 %1, %2, %3...
            parts.append(f"%{placeholder_count}")
            placeholder_count += 1
    
    return ''.join(parts)

def extract_class_tr_strings(file_path: str) -> Dict[str, List[str]]:
    """从单个 Python 文件中提取每个类的 self.tr() 中的中文字符串"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"读取文件失败 {file_path}: {e}")
        return {}
    
    result = {}
    
    # 使用 AST 解析，更准确地提取类和方法
    try:
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                tr_strings = []
                
                # 遍历类中的所有节点
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        # 检查是否是 self.tr() 调用
                        if (isinstance(child.func, ast.Attribute) and 
                            isinstance(child.func.value, ast.Name) and 
                            child.func.value.id == 'self' and 
                            child.func.attr == 'tr'):
                            
                            # 提取字符串参数
                            for arg in child.args:
                                if isinstance(arg, ast.Str):
                                    if is_chinese(arg.s):
                                        tr_strings.append(arg.s)
                                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                    if is_chinese(arg.value):
                                        tr_strings.append(arg.value)
                                elif isinstance(arg, ast.JoinedStr):
                                    # 处理 f 字符串
                                    f_string_text = extract_f_string_text(arg)
                                    if f_string_text and is_chinese(f_string_text):
                                        tr_strings.append(f_string_text)
                
                if tr_strings:
                    # 去重
                    tr_strings = list(set(tr_strings))
                    result[class_name] = tr_strings
                    print(f"  类 {class_name}: 找到 {len(tr_strings)} 个翻译字符串")
                    
    except SyntaxError as e:
        print(f"解析文件失败 {file_path}: {e}")
        # 如果 AST 解析失败，回退到正则表达式
        return extract_tr_strings_regex(file_path)
    
    return result

def extract_tr_strings_regex(file_path: str) -> Dict[str, List[str]]:
    """使用正则表达式提取 self.tr() 字符串（备用方法）"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"读取文件失败 {file_path}: {e}")
        return {}
    
    result = {}
    
    # 提取类定义及其内容
    class_pattern = re.compile(r'class\s+(\w+)\s*\([^)]*\):(.*?)(?=\nclass|\nif\s+__name__|\Z)', re.DOTALL)
    
    for match in class_pattern.finditer(content):
        class_name = match.group(1)
        class_content = match.group(2)
        
        # 在类内容中查找 self.tr() 调用
        tr_pattern = re.compile(r'self\.tr\s*\(\s*[\'"]([^\'"]*)[\'"].*?\)', re.DOTALL)
        tr_strings = []
        
        for tr_match in tr_pattern.finditer(class_content):
            text = tr_match.group(1)
            if is_chinese(text):
                tr_strings.append(text)
        
        if tr_strings:
            # 去重
            tr_strings = list(set(tr_strings))
            result[class_name] = tr_strings
            print(f"  类 {class_name}: 找到 {len(tr_strings)} 个翻译字符串")
    
    return result

def scan_medimager_directory() -> Dict[str, Dict[str, List[str]]]:
    """扫描 medimager 目录下所有 Python 文件"""
    results = {}
    medimager_path = Path(__file__).parent.parent / 'medimager'
    
    if not medimager_path.exists():
        print(f"错误：找不到 {medimager_path} 目录")
        return results
    
    print("正在扫描 medimager 目录...")
    
    for root, dirs, files in os.walk(medimager_path):
        # 跳过不需要的目录
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'logs', 'tests']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, medimager_path.parent)
                
                print(f"\n检查文件: {relative_path}")
                
                extracted = extract_class_tr_strings(file_path)
                if extracted:
                    results[relative_path] = extracted
                    print(f"  [OK] 从 {relative_path} 提取到翻译字符串")
                else:
                    print(f"  - 未找到翻译字符串")
    
    return results

def create_ts_xml(translation_data: Dict[str, Dict[str, List[str]]]) -> str:
    """创建 TS 格式的 XML 内容"""
    # 创建根元素
    root = ET.Element('TS')
    root.set('version', '2.1')
    root.set('language', 'zh_CN')
    
    # 按类名组织数据（确保上下文正确）
    all_contexts = {}
    
    for file_path, contexts in translation_data.items():
        for class_name, strings in contexts.items():
            if class_name not in all_contexts:
                all_contexts[class_name] = {}
            
            for string in strings:
                if string not in all_contexts[class_name]:
                    all_contexts[class_name][string] = []
                all_contexts[class_name][string].append(file_path)
    
    # 创建 XML 结构
    for class_name, strings_dict in sorted(all_contexts.items()):
        # 创建 context 元素
        context_elem = ET.SubElement(root, 'context')
        
        # 添加 name 元素
        name_elem = ET.SubElement(context_elem, 'name')
        name_elem.text = class_name
        
        # 为每个字符串创建 message 元素
        for string, file_paths in sorted(strings_dict.items()):
            message_elem = ET.SubElement(context_elem, 'message')
            
            # 添加 location 元素（使用第一个文件位置）
            location_elem = ET.SubElement(message_elem, 'location')
            location_elem.set('filename', file_paths[0].replace('\\', '/'))
            
            # 添加 source 元素
            source_elem = ET.SubElement(message_elem, 'source')
            source_elem.text = string
            
            # 添加 translation 元素（默认使用原文）
            translation_elem = ET.SubElement(message_elem, 'translation')
            translation_elem.text = string
    
    # 转换为格式良好的 XML
    rough_string = ET.tostring(root, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent='    ')
    
    # 移除空行
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    return '\n'.join(lines)



def write_ts_files(xml_content: str):
    """写入中文 TS 文件"""
    base_path = Path(__file__).parent.parent / 'medimager' / 'translations'
    
    # 确保目录存在
    os.makedirs(base_path, exist_ok=True)
    
    # 写入中文 TS 文件
    zh_ts_path = base_path / 'zh_CN.ts'
    try:
        with open(zh_ts_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print(f"[OK] 生成中文翻译模板文件: {zh_ts_path}")
    except Exception as e:
        print(f"写入中文文件失败: {e}")
        return

def main():
    """主函数"""
    print("=" * 70)
    print("MedImager 中文翻译模板生成器")
    print("=" * 70)
    print("功能：")
    print("1. 使用 AST 解析准确提取 self.tr() 字符串")
    print("2. 按类名正确设置翻译上下文")
    print("3. 生成中文 TS 模板文件")
    print("4. 配合 translate_ts.py 工具翻译其他语言")
    print("=" * 70)
    
    # 扫描并提取翻译字符串
    translation_data = scan_medimager_directory()
    
    if not translation_data:
        print("\n❌ 未找到需要翻译的中文字符串")
        print("请检查是否在代码中使用了 self.tr('中文字符串') 的格式")
        return
    
    # 统计信息
    total_files = len(translation_data)
    total_classes = sum(len(contexts) for contexts in translation_data.values())
    total_strings = sum(len(strings) for contexts in translation_data.values() 
                       for strings in contexts.values())
    
    print(f"\n[SCAN] 扫描结果:")
    print(f"  - 扫描文件数: {total_files}")
    print(f"  - 发现类数: {total_classes}")
    print(f"  - 翻译字符串数: {total_strings}")
    
    # 显示详细信息
    print(f"\n[DETAIL] 详细信息:")
    for file_path, contexts in translation_data.items():
        print(f"  {file_path}:")
        for class_name, strings in contexts.items():
            print(f"    {class_name}: {len(strings)} 个字符串")
            for string in strings[:3]:  # 只显示前3个
                print(f"      - {string[:50]}...")
            if len(strings) > 3:
                print(f"      ... 还有 {len(strings) - 3} 个")
    
    # 生成 XML 内容
    print(f"\n[GENERATE] 正在生成翻译文件...")
    xml_content = create_ts_xml(translation_data)
    
    # 写入文件
    write_ts_files(xml_content)
    
    print(f"\n[SUCCESS] 中文翻译模板生成完成！")
    print("=" * 70)

if __name__ == '__main__':
    main()