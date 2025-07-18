# MedImager 翻译工具链使用说明

## 概述

MedImager 翻译工具链是一套完整的国际化解决方案，包含自动检测、生成、翻译和编译功能，专门为PySide6/Qt项目设计。

## 主要特点

- ✅ **完整工具链**：一键运行所有翻译流程
- ✅ **f字符串支持**：正确识别和处理复杂的f字符串
- ✅ **Qt兼容格式**：生成Qt标准的%1, %2占位符
- ✅ **并行翻译**：支持6线程并行处理，速度快
- ✅ **智能检测**：自动检查未国际化的中文字符串
- ✅ **多语言支持**：支持9种常用语言
- ✅ **容错机制**：双重翻译服务备份，确保可靠性

## 工具链组成

### 1. check_i18n.py - 国际化检查工具
- 检查代码中未使用`self.tr()`包装的中文字符串
- 支持复杂f字符串的识别
- 智能过滤非UI文本

### 2. auto_translation_generator.py - 翻译文件生成器
- 使用AST解析准确提取`self.tr()`字符串
- 支持f字符串，生成Qt兼容的%1, %2占位符
- 按类名正确设置翻译上下文
- 生成标准的zh_CN.ts模板文件

### 3. translate_ts.py - TS文件翻译器
- 并行翻译多个语言
- 实时进度显示
- 双重翻译服务备份
- 智能文本清理

### 4. compile_translations.py - 翻译文件编译器
- 将.ts文件编译为.qm文件
- 自动检测PySide6的lrelease工具
- 批量处理所有语言文件

### 5. main.py - 一键运行工具
- 按顺序自动运行所有工具
- 错误处理和用户交互
- 完整的执行报告

## 支持的语言

| 代码 | 语言 |
|------|------|
| en_US | English (英语) |
| fr_FR | French (法语) |
| de_DE | German (德语) |
| es_ES | Spanish (西班牙语) |
| it_IT | Italian (意大利语) |
| pt_PT | Portuguese (葡萄牙语) |
| ru_RU | Russian (俄语) |
| ja_JP | Japanese (日语) |
| ko_KR | Korean (韩语) |

## 输出文件

翻译完成后，会在`medimager/translations/`目录下生成：
- `zh_CN.ts` - 中文模板文件
- `en_US.ts` - 英语翻译文件
- `fr_FR.ts` - 法语翻译文件
- `de_DE.ts` - 德语翻译文件
- `es_ES.ts` - 西班牙语翻译文件
- 对应的`.qm`编译文件

## 翻译质量

工具采用双重翻译服务：
1. **主服务**：Google Translate API
2. **备用服务**：MyMemory Translation API

内置智能处理机制：
- 自动跳过纯符号和数字
- 保持原文标点符号格式
- 清理多余空格
- 处理括号等特殊字符

## 性能表现

- **翻译速度**：238个条目约30-60秒
- **并发处理**：6个线程同时工作
- **成功率**：>95%（双重备份机制）
- **内存占用**：<50MB



## 注意事项

1. **网络要求**：需要稳定的网络连接访问翻译服务
2. **速率限制**：内置0.1秒延迟，避免请求过快
3. **文件备份**：建议翻译前备份原始文件
4. **质量检查**：翻译完成后建议人工检查关键术语

## 故障排除

### 翻译质量问题
- 工具会自动使用备用翻译服务
- 失败的条目会保持原文
- 可以手动编辑生成的.ts文件

## 新功能特性

### f字符串支持
工具链现在完全支持复杂的f字符串，例如：
```python
self.tr(f"清除绑定完成：清除了 {count} 个绑定")
self.tr(f"当前布局: {rows}×{cols}")
```

这些f字符串会被正确转换为Qt兼容的格式：
```xml
<source>清除绑定完成：清除了 %1 个绑定</source>
<source>当前布局: %1×%2</source>
```

### 实时进度显示
翻译过程中会显示实时进度，例如：
```
进度: 45/120
```

### 智能错误处理
- 自动检测PySide6工具
- 双重翻译服务备份
- 详细的错误报告和建议

## 使用方法

### 一键运行（推荐）

```bash
# 运行完整的翻译工具链
python main.py
```

这将按顺序执行：
1. 生成zh_CN.ts翻译模板
2. 翻译为所有支持的语言
3. 编译.qm文件

### 单独使用各工具

#### 1. 检查国际化问题
```bash
python check_i18n.py
```

#### 2. 生成翻译模板
```bash
python auto_translation_generator.py
```

#### 3. 翻译TS文件
```bash
# 翻译为所有支持的语言
python translate_ts.py ../medimager/translations/zh_CN.ts --all

# 翻译为特定语言
python translate_ts.py ../medimager/translations/zh_CN.ts --languages en_US fr_FR de_DE
```

#### 4. 编译翻译文件
```bash
python compile_translations.py
```

### 参数说明

#### translate_ts.py 参数
- `ts_file`: 源TS文件路径（通常是zh_CN.ts）
- `--all`: 翻译为所有支持的语言
- `--languages`: 指定要翻译的语言代码（空格分隔）
- `--output-dir`: 指定输出目录（可选，默认为源文件目录）

## 快速开始

最简单的使用方式：
```bash
cd translation_tools
python main.py
```

就这么简单！🎉