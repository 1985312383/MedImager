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
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.parse

class TSTranslator:
    """TS文件翻译器 - 增强版，支持医学术语专业翻译"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # 医学影像术语词典
        self.medical_terms = self._load_medical_dictionary()
        
        # 翻译缓存
        self.translation_cache = {}
        
        # 加载翻译缓存
        self._load_translation_cache()
        
    def _load_medical_dictionary(self) -> Dict[str, str]:
        """从JSON文件加载医学术语词典"""
        medical_terms = {}
        
        # 尝试从JSON文件加载
        json_file = Path(__file__).parent / 'medical_terms.json'
        if json_file.exists():
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    terms_data = json.load(f)
                    
                # 合并所有分类的术语
                for category, terms in terms_data.items():
                    medical_terms.update(terms)
                    
                print(f"从JSON文件加载医学术语: {len(medical_terms)} 个术语")
                return medical_terms
                
            except Exception as e:
                print(f"加载医学术语JSON文件失败: {e}")
                
        # 如果JSON文件不存在或加载失败，使用默认术语
        print("使用默认医学术语词典")
        return {
            # 基础DICOM术语
            'DICOM': 'DICOM',
            'DICOM文件': 'DICOM File',
            '窗宽': 'Window Width',
            '窗位': 'Window Level',
            '像素': 'Pixel',
            '切片': 'Slice',
            '序列': 'Series',
            'ROI': 'ROI',
            '测量': 'Measurement',
            '标注': 'Annotation',
            'CT': 'CT',
            'MRI': 'MRI',
            '对比度': 'Contrast',
            '亮度': 'Brightness',
            '工具栏': 'Toolbar',
            '菜单栏': 'Menu Bar',
            '打开': 'Open',
            '保存': 'Save',
            '文件': 'File',
            '编辑': 'Edit',
            '查看': 'View',
            '工具': 'Tools',
        }
        
    def _load_translation_cache(self) -> None:
        """加载翻译缓存"""
        cache_file = Path(__file__).parent / 'translation_cache.json'
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self.translation_cache = json.load(f)
                print(f"加载翻译缓存: {len(self.translation_cache)} 条记录")
            except Exception as e:
                print(f"加载翻译缓存失败: {e}")
                
    def _save_translation_cache(self) -> None:
        """保存翻译缓存"""
        cache_file = Path(__file__).parent / 'translation_cache.json'
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.translation_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存翻译缓存失败: {e}")
            
    def _preprocess_text(self, text: str) -> Tuple[str, Dict[str, str]]:
        """预处理文本，提取医学术语"""
        # 保存原始文本中的医学术语
        term_mapping = {}
        processed_text = text
        
        # 按长度排序，优先匹配长术语
        sorted_terms = sorted(self.medical_terms.items(), key=lambda x: len(x[0]), reverse=True)
        
        for zh_term, en_term in sorted_terms:
            if zh_term in processed_text:
                # 使用占位符替换术语
                placeholder = f"__TERM_{len(term_mapping)}__"
                term_mapping[placeholder] = en_term
                processed_text = processed_text.replace(zh_term, placeholder)
                
        return processed_text, term_mapping
        
    def _postprocess_text(self, translated_text: str, term_mapping: Dict[str, str]) -> str:
        """后处理文本，恢复医学术语"""
        result = translated_text
        for placeholder, en_term in term_mapping.items():
            result = result.replace(placeholder, en_term)
        return result
        
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
            
    def translate_with_medical_context(self, text: str) -> str:
        """医学上下文感知翻译函数"""
        # 检查缓存
        if text in self.translation_cache:
            print(f"使用缓存翻译: {text[:30]}...")
            return self.translation_cache[text]
            
        # 预处理：提取医学术语
        processed_text, term_mapping = self._preprocess_text(text)
        
        # 如果文本完全由术语组成，直接返回
        if not processed_text.strip() or processed_text.strip().startswith('__TERM_'):
            result = self._postprocess_text(processed_text, term_mapping)
            self.translation_cache[text] = result
            return result
            
        # 检查是否为纯医学术语（无需翻译）
        if self._is_pure_medical_term(text):
            self.translation_cache[text] = text
            return text
            
        # 多源翻译对比
        translations = []
        
        # 1. Google Translate
        google_result = self.translate_text(processed_text)
        if google_result and google_result != processed_text:
            translations.append(('Google', google_result))
            
        # 2. MyMemory API
        mymemory_result = self._translate_with_mymemory(processed_text)
        if mymemory_result and mymemory_result != processed_text:
            translations.append(('MyMemory', mymemory_result))
            
        # 3. DeepL API (如果可用)
        deepl_result = self._translate_with_deepl(processed_text)
        if deepl_result and deepl_result != processed_text:
            translations.append(('DeepL', deepl_result))
            
        # 选择最佳翻译
        best_translation = self._select_best_translation(processed_text, translations)
        
        # 后处理：恢复医学术语
        final_result = self._postprocess_text(best_translation, term_mapping)
        
        # 智能后处理：修正常见翻译错误
        final_result = self._post_process_medical_translation(final_result)
        
        # 缓存结果
        self.translation_cache[text] = final_result
        
        return final_result
        
    def _is_pure_medical_term(self, text: str) -> bool:
        """检查是否为纯医学术语（如DICOM、CT、MRI等）"""
        pure_terms = ['DICOM', 'CT', 'MRI', 'PET', 'SPECT', 'ROI', 'MPR', 'MIP', 'MinIP']
        return text.strip() in pure_terms
        
    def _post_process_medical_translation(self, translation: str) -> str:
        """智能后处理医学翻译"""
        # 修正常见的翻译错误
        corrections = {
            'window width': 'Window Width',
            'window level': 'Window Level', 
            'dicom': 'DICOM',
            'roi': 'ROI',
            'ct': 'CT',
            'mri': 'MRI',
            'pet': 'PET',
            'spect': 'SPECT',
            'mpr': 'MPR',
            'mip': 'MIP',
            'minip': 'MinIP',
            'x-ray': 'X-ray',
            '3d': '3D',
            '2d': '2D',
        }
        
        result = translation
        for wrong, correct in corrections.items():
            # 使用正则表达式进行单词边界匹配
            pattern = r'\b' + re.escape(wrong) + r'\b'
            result = re.sub(pattern, correct, result, flags=re.IGNORECASE)
            
        return result
        
    def _translate_with_mymemory(self, text: str) -> Optional[str]:
        """使用MyMemory API翻译"""
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
                return result['responseData']['translatedText']
            return None
                
        except Exception as e:
            print(f"MyMemory翻译错误: {e}")
            return None
            
    def _translate_with_deepl(self, text: str) -> Optional[str]:
        """使用DeepL API翻译（需要API密钥）"""
        # 这里可以添加DeepL API调用
        # 由于需要API密钥，暂时返回None
        return None
        
    def _select_best_translation(self, original: str, translations: List[Tuple[str, str]]) -> str:
        """选择最佳翻译结果"""
        if not translations:
            return original
            
        # 如果只有一个翻译，直接返回
        if len(translations) == 1:
            return translations[0][1]
            
        # 简单的评分机制：优先选择包含更多专业术语的翻译
        best_score = -1
        best_translation = translations[0][1]
        
        for source, translation in translations:
            score = self._score_translation(translation)
            print(f"{source} 翻译评分: {score} - {translation[:50]}...")
            
            if score > best_score:
                best_score = score
                best_translation = translation
                
        return best_translation
        
    def _score_translation(self, translation: str) -> float:
        """为翻译结果评分"""
        score = 0.0
        
        # 检查是否包含医学术语（权重较高）
        for en_term in self.medical_terms.values():
            if en_term.lower() in translation.lower():
                score += 2.0  # 医学术语匹配权重更高
                
        # 检查专业术语的完整性
        medical_keywords = ['DICOM', 'ROI', 'CT', 'MRI', 'Pixel', 'Window', 'Slice', 'Series']
        for keyword in medical_keywords:
            if keyword.lower() in translation.lower():
                score += 1.5
                
        # 检查大小写规范性
        if translation and translation[0].isupper():
            score += 0.2
            
        # 检查标点符号
        if translation.endswith(('.', '!', '?', ':', ';')):
            score += 0.1
            
        # 检查是否保持了原文的格式（如括号、冒号等）
        format_chars = ['(', ')', ':', '-', '/']
        for char in format_chars:
            if char in translation:
                score += 0.1
                
        # 惩罚过于简单的翻译
        if len(translation.split()) < 2 and len(translation) > 10:
            score -= 0.5
            
        return score
            
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
            translated_text = self.translate_with_medical_context(original_text)
            
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
                        
                        translated_text = self.translate_with_medical_context(original_text)
                        translation_elem.text = translated_text
                        
                        # 添加延迟
                        time.sleep(0.5)
                        
        # 保存英文TS文件
        tree.write(en_ts_file, encoding='utf-8', xml_declaration=True)
        # 保存翻译缓存
        self._save_translation_cache()
        
        print(f"英文TS文件创建完成: {en_ts_file}")
        print(f"共翻译了 {translation_count} 个文本")
        print(f"翻译缓存已保存，包含 {len(self.translation_cache)} 条记录")

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