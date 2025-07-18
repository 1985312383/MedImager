#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的TS文件翻译工具
专门用于将zh_CN.ts快速翻译为其他语言
"""

import os
import xml.etree.ElementTree as ET
from lara_sdk import Translator, Credentials
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

class FastTSTranslator:
    """快速TS文件翻译器"""
    
    def __init__(self, target_languages=None):
        # 所有支持的语言（使用ISO标准语言代码）
        self.all_languages = {
            'en_US': 'English', 'fr_FR': 'French', 'ru_RU': 'Russian', 'de_DE': 'German',
            'ja_JP': 'Japanese', 'ko_KR': 'Korean', 'es_ES': 'Spanish', 'it_IT': 'Italian', 'pt_PT': 'Portuguese'
        }
        
        # 语言代码到翻译API代码的映射
        self.lang_code_mapping = {
            'en_US': 'en', 'fr_FR': 'fr', 'ru_RU': 'ru', 'de_DE': 'de',
            'ja_JP': 'ja', 'ko_KR': 'ko', 'es_ES': 'es', 'it_IT': 'it', 'pt_PT': 'pt'
        }
        
        # 默认翻译的语言列表（可在此配置）
        self.default_target_languages = ['en_US', 'fr_FR', 'de_DE', 'es_ES']  # 可修改此列表选择需要的语言
        
        # 使用指定的语言或默认语言
        if target_languages:
            self.languages = {k: v for k, v in self.all_languages.items() if k in target_languages}
        else:
            self.languages = {k: v for k, v in self.all_languages.items() if k in self.default_target_languages}
        # Lara SDK 配置 - 请在此处填写您的密钥
        self.lara_access_key_id = ""
        self.lara_access_key_secret = ""

        if not self.lara_access_key_id or not self.lara_access_key_secret:
            print("\n[Error] 请在脚本中设置 lara_access_key_id 和 lara_access_key_secret")
            self.translator = None
        else:
            try:
                credentials = Credentials(access_key_id=self.lara_access_key_id, access_key_secret=self.lara_access_key_secret)
                self.translator = Translator(credentials)
            except Exception as e:
                print(f"\n[Error] Failed to initialize Lara Translator: {e}")
                self.translator = None

    def translate_text(self, text, target_lang):
        """翻译单个文本（主要用于测试或单次翻译）"""
        if not text or not self.translator:
            return text
        return self.translate_batch([text], target_lang)[0]
    
    def _clean_translation(self, translated, original):
        """清理翻译结果"""
        if not translated:
            return original
        
        # 移除多余的空格
        translated = ' '.join(translated.split())
        
        # 保持原文的标点符号格式
        if original.endswith(':') and not translated.endswith(':'):
            translated += ':'
        if original.endswith('...') and not translated.endswith('...'):
            translated += '...'
        
        # 处理括号
        if '(' in original and ')' in original:
            if '(' not in translated or ')' not in translated:
                # 如果翻译丢失了括号，尝试保持原格式
                pass
        
        return translated
    
    def translate_batch(self, texts, target_lang):
        """高效地批量翻译多个文本"""
        if not self.translator or not texts:
            return texts

        api_lang_code = self.lang_code_mapping.get(target_lang, target_lang).replace('_', '-')
        source_lang_code = 'zh-CN'

        # 清理和准备文本
        original_texts = []
        texts_to_translate = []
        indices_to_translate = []

        for i, text in enumerate(texts):
            clean_text = text.strip()
            # 过滤掉不需要翻译的内容
            if (not clean_text or 
                clean_text in ['&', '...', ':', '()', '[]', '{}', '&amp;', 'OK', 'Qt', 'UI'] or 
                clean_text.isdigit() or
                clean_text.startswith('%') or  # Qt占位符
                clean_text.startswith('&')):  # 快捷键
                original_texts.append(text) # 保留原文
            else:
                original_texts.append(None) # 占位符
                texts_to_translate.append(clean_text)
                indices_to_translate.append(i)

        if not texts_to_translate:
            return texts # 没有需要翻译的文本

        try:
            print(f"\n[Info] 准备翻译 {len(texts_to_translate)} 个文本到 {api_lang_code}")
            
            # 逐个翻译文本（Lara SDK 不支持批量翻译）
            translated_results = []
            for i, text in enumerate(texts_to_translate):
                try:
                    # 使用Lara SDK翻译，参考官方示例
                    res = self.translator.translate(text, source=source_lang_code, target=api_lang_code)
                    
                    # 获取翻译结果
                    if hasattr(res, 'translation'):
                        translated_text = res.translation
                    else:
                        translated_text = str(res)
                    
                    translated_results.append(translated_text)
                    # 减少调试输出以节省token
                    if i == 0:  # 只打印第一个作为示例
                        print(f"[Success] 翻译示例: '{text}' -> '{translated_text}'")
                except Exception as e:
                    print(f"[Warning] 翻译失败: {text[:30]}... -> {str(e)[:50]}")
                    translated_results.append(text)  # 翻译失败时使用原文
            
            print(f"[Info] 完成翻译 {len(translated_results)} 个文本")
            
            if not translated_results:
                print("[Warning] 翻译API返回空结果，使用原文")
                return texts

            # 清理并合并结果
            final_translations = list(original_texts) # 创建副本
            for i, original_index in enumerate(indices_to_translate):
                if i < len(translated_results):
                    translated = self._clean_translation(translated_results[i], texts_to_translate[i])
                    final_translations[original_index] = translated
                else:
                    final_translations[original_index] = texts_to_translate[i] # 翻译失败，返回原文
            
            return final_translations

        except Exception as e:
            print(f"\n[Lara SDK Batch Error] Failed to translate batch: {e}")
            print(f"[Debug] 异常详情: {type(e).__name__}: {str(e)}")
            return texts  # 批量翻译失败时返回所有原文
    
    def translate_ts_file(self, source_file, target_lang, output_file=None):
        """翻译TS文件"""
        if not self.translator:
            print(f"[Error] 翻译器未初始化，无法翻译到 {target_lang}。请设置环境变量。")
            return False
            
        if target_lang not in self.all_languages:
            print(f"不支持的语言: {target_lang}")
            return False
        
        source_path = Path(source_file)
        if not source_path.exists():
            print(f"源文件不存在: {source_file}")
            return False
        
        # 确定输出文件
        if output_file:
            output_path = Path(output_file)
        else:
            output_path = source_path.parent / f"{target_lang}.ts"
        
        try:
            # 解析XML
            tree = ET.parse(source_file)
            root = tree.getroot()
            
            # 更新language属性
            root.set('language', target_lang)
            
            # 收集需要翻译的文本
            texts = []
            elements = []
            
            for context in root.findall('.//context'):
                for message in context.findall('message'):
                    source_elem = message.find('source')
                    if source_elem is not None and source_elem.text:
                        texts.append(source_elem.text)
                        elements.append(message)
            
            print(f"开始翻译 {len(texts)} 个条目到 {self.all_languages[target_lang]}...")
            
            # 批量翻译
            translated_texts = self.translate_batch(texts, target_lang)
            
            # 打印进度
            total = len(texts)
            for i, _ in enumerate(translated_texts):
                progress_text = f"Progress: {i + 1}/{total}"
                print(f"\r{progress_text}", end="", flush=True)
            print() # 换行
            
            # 更新XML
            for i, (message, translated) in enumerate(zip(elements, translated_texts)):
                translation_elem = message.find('translation')
                if translation_elem is None:
                    translation_elem = ET.SubElement(message, 'translation')
                
                translation_elem.text = translated
                
                # 如果翻译成功且文本非空，则移除 "unfinished" 状态
                if translated and translated.strip() and 'type' in translation_elem.attrib:
                    del translation_elem.attrib['type']
            
            # 保存文件
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(output_path), encoding='utf-8', xml_declaration=True)
            
            print(f"翻译完成: {output_path}")
            return True
            
        except Exception as e:
            print(f"翻译失败: {e}")
            return False
    
    def translate_multiple(self, source_file, languages, output_dir=None):
        """翻译为多种语言"""
        results = {}
        for lang in languages:
            print(f"\n=== 翻译为 {self.all_languages.get(lang, lang)} ===")
            if output_dir:
                output_file = Path(output_dir) / f"{lang}.ts"
            else:
                output_file = None
            results[lang] = self.translate_ts_file(source_file, lang, output_file)
        return results
    
    def translate_all_default(self, source_file, output_dir=None):
        """翻译为所有默认配置的语言"""
        print(f"开始批量翻译为 {len(self.default_target_languages)} 种语言: {', '.join(self.default_target_languages)}")
        return self.translate_multiple(source_file, self.default_target_languages, output_dir)

def main():
    """命令行入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='快速翻译Qt TS文件')
    parser.add_argument('input_file', help='输入的TS文件路径')
    parser.add_argument('target_language', nargs='?', help='目标语言代码 (如: en, fr, de, es, it, pt, ru, ja, ko)')
    parser.add_argument('-o', '--output', help='输出文件路径 (可选，默认为目标语言代码.ts)')
    parser.add_argument('--all', action='store_true', help='翻译为所有默认语言')
    parser.add_argument('--languages', nargs='+', help='指定多个目标语言')
    parser.add_argument('--output-dir', help='输出目录 (用于多语言翻译)')
    
    args = parser.parse_args()
    
    try:
        translator = FastTSTranslator()
        
        if args.all:
            # 翻译为所有默认语言
            success = translator.translate_all_default(args.input_file, args.output_dir)
            if all(success.values()):
                print("所有语言翻译完成")
            else:
                print("部分语言翻译失败")
                exit(1)
        elif args.languages:
            # 翻译为多种指定语言
            success = translator.translate_multiple(args.input_file, args.languages, args.output_dir)
            if all(success.values()):
                print("所有指定语言翻译完成")
            else:
                print("部分语言翻译失败")
                exit(1)
        elif args.target_language:
            # 翻译为单一语言
            success = translator.translate_ts_file(args.input_file, args.target_language, args.output)
            if success:
                print(f"翻译完成: {args.input_file} -> {args.target_language}")
            else:
                print("翻译失败")
                exit(1)
        else:
            parser.error("必须指定目标语言、使用--all或--languages参数")
                
    except Exception as e:
        print(f"错误: {e}")
        exit(1)


if __name__ == '__main__':
    main()