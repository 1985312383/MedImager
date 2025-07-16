#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译TS文件工具
将zh_CN.ts文件中的translation字段翻译成英文
"""

import xml.etree.ElementTree as ET
import requests
import time
import re
from pathlib import Path
from typing import Dict, List, Optional
import urllib.parse

class TSTranslator:
    """TS文件翻译器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def translate_text(self, text: str, source_lang: str = 'zh', target_lang: str = 'en') -> Optional[str]:
        """使用Google Translate免费API翻译文本"""
        try:
            # 清理文本，移除多余的空白字符
            text = text.strip()
            if not text:
                return text
                
            # 构建请求URL
            base_url = 'https://translate.googleapis.com/translate_a/single'
            params = {
                'client': 'gtx',
                'sl': source_lang,
                'tl': target_lang,
                'dt': 't',
                'q': text
            }
            
            # 发送请求
            response = self.session.get(base_url, params=params, timeout=10)
            response.raise_for_status()
            
            # 解析响应
            result = response.json()
            if result and len(result) > 0 and len(result[0]) > 0:
                translated_text = result[0][0][0]
                return translated_text
            else:
                print(f"翻译失败: {text}")
                return text
                
        except Exception as e:
            print(f"翻译错误 '{text}': {e}")
            return text
            
    def translate_with_fallback(self, text: str) -> str:
        """带备用方案的翻译函数"""
        # 首先尝试Google Translate
        translated = self.translate_text(text)
        if translated and translated != text:
            return translated
            
        # 如果Google Translate失败，尝试使用MyMemory API
        try:
            url = 'https://api.mymemory.translated.net/get'
            params = {
                'q': text,
                'langpair': 'zh|en'
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            if result.get('responseStatus') == 200:
                translated_text = result['responseData']['translatedText']
                return translated_text
            else:
                print(f"MyMemory翻译失败: {text}")
                return text
                
        except Exception as e:
            print(f"MyMemory翻译错误 '{text}': {e}")
            return text
            
    def parse_ts_file(self, ts_file_path: str) -> ET.ElementTree:
        """解析TS文件"""
        try:
            tree = ET.parse(ts_file_path)
            return tree
        except Exception as e:
            print(f"解析TS文件失败: {e}")
            raise
            
    def extract_translations(self, tree: ET.ElementTree) -> List[Dict]:
        """提取需要翻译的文本"""
        translations = []
        root = tree.getroot()
        
        for context in root.findall('context'):
            context_name = context.find('name').text if context.find('name') is not None else 'Unknown'
            
            for message in context.findall('message'):
                source_elem = message.find('source')
                translation_elem = message.find('translation')
                
                if source_elem is not None and translation_elem is not None:
                    source_text = source_elem.text or ''
                    translation_text = translation_elem.text or ''
                    
                    # 只翻译中文文本
                    if self.contains_chinese(translation_text):
                        translations.append({
                            'context': context_name,
                            'source': source_text,
                            'translation': translation_text,
                            'element': translation_elem
                        })
                        
        return translations
        
    def contains_chinese(self, text: str) -> bool:
        """检查文本是否包含中文字符"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))
        
    def translate_ts_file(self, input_file: str, output_file: str = None) -> None:
        """翻译TS文件"""
        if output_file is None:
            # 生成输出文件名
            input_path = Path(input_file)
            output_file = str(input_path.parent / f"{input_path.stem}_en{input_path.suffix}")
            
        print(f"开始翻译: {input_file}")
        print(f"输出文件: {output_file}")
        
        # 解析TS文件
        tree = self.parse_ts_file(input_file)
        
        # 提取需要翻译的文本
        translations = self.extract_translations(tree)
        print(f"找到 {len(translations)} 个需要翻译的文本")
        
        # 翻译文本
        for i, item in enumerate(translations, 1):
            original_text = item['translation']
            print(f"[{i}/{len(translations)}] 翻译: {original_text[:50]}...")
            
            # 翻译文本
            translated_text = self.translate_with_fallback(original_text)
            
            # 更新XML元素
            item['element'].text = translated_text
            
            # 添加延迟避免请求过于频繁
            time.sleep(0.5)
            
        # 保存翻译后的文件
        tree.write(output_file, encoding='utf-8', xml_declaration=True)
        print(f"翻译完成，已保存到: {output_file}")
        
    def create_english_ts(self, zh_ts_file: str, en_ts_file: str = None) -> None:
        """创建英文TS文件"""
        if en_ts_file is None:
            zh_path = Path(zh_ts_file)
            en_ts_file = str(zh_path.parent / "en_US.ts")
            
        print(f"创建英文TS文件: {zh_ts_file} -> {en_ts_file}")
        
        # 解析中文TS文件
        tree = self.parse_ts_file(zh_ts_file)
        root = tree.getroot()
        
        # 修改语言属性
        root.set('language', 'en_US')
        
        # 翻译所有translation字段
        translation_count = 0
        for context in root.findall('context'):
            for message in context.findall('message'):
                translation_elem = message.find('translation')
                if translation_elem is not None and translation_elem.text:
                    original_text = translation_elem.text
                    if self.contains_chinese(original_text):
                        translation_count += 1
                        print(f"[{translation_count}] 翻译: {original_text[:50]}...")
                        
                        translated_text = self.translate_with_fallback(original_text)
                        translation_elem.text = translated_text
                        
                        # 添加延迟
                        time.sleep(0.5)
                        
        # 保存英文TS文件
        tree.write(en_ts_file, encoding='utf-8', xml_declaration=True)
        print(f"英文TS文件创建完成: {en_ts_file}")
        print(f"共翻译了 {translation_count} 个文本")

def main():
    """主函数"""
    # TS文件路径 - 修改为相对于父目录的路径
    base_path = Path(__file__).parent.parent
    zh_ts_file = str(base_path / "medimager" / "translations" / "zh_CN.ts")
    en_ts_file = str(base_path / "medimager" / "translations" / "en_US.ts")
    
    # 检查文件是否存在
    if not Path(zh_ts_file).exists():
        print(f"错误: 找不到文件 {zh_ts_file}")
        return
        
    # 创建翻译器
    translator = TSTranslator()
    
    try:
        # 创建英文TS文件
        translator.create_english_ts(zh_ts_file, en_ts_file)
        print("\n翻译完成！")
        print(f"英文TS文件已保存到: {en_ts_file}")
        
    except Exception as e:
        print(f"翻译过程中出错: {e}")
        
if __name__ == '__main__':
    main()