# MedImager 翻译工具使用说明

## 概述

这是一个专为医学影像软件设计的智能翻译工具，能够准确翻译医学术语和界面文本。该工具支持多翻译源对比、医学术语保护、翻译缓存等高级功能。

## 主要特性

### 🏥 医学术语专业翻译
- **专业词典**: 内置丰富的医学影像术语词典
- **术语保护**: 自动识别并保护医学术语不被错误翻译
- **上下文感知**: 根据医学语境选择最佳翻译

### 🔄 多源翻译对比
- **Google Translate**: 主要翻译引擎
- **MyMemory API**: 备用翻译源
- **DeepL API**: 可选的高质量翻译（需要API密钥）
- **智能评分**: 自动选择最佳翻译结果

### 💾 智能缓存系统
- **翻译缓存**: 避免重复翻译，提高效率
- **持久化存储**: 缓存结果保存到本地文件
- **增量更新**: 只翻译新增或修改的文本

### 🎯 后处理优化
- **格式修正**: 自动修正常见的翻译格式错误
- **大小写规范**: 确保专业术语的正确大小写
- **标点符号**: 保持原文的格式和标点

## 文件结构

```
translation_tools/
├── translate_ts.py          # 主翻译脚本
├── medical_terms.json       # 医学术语词典
├── translation_cache.json   # 翻译缓存（自动生成）
└── README.md               # 使用说明
```

## 医学术语词典

`medical_terms.json` 包含以下分类的术语：

- **DICOM术语**: DICOM文件、序列、图像等
- **医学影像**: 窗宽窗位、像素、切片、重建等
- **ROI测量**: 感兴趣区域、测量、标注等
- **医学设备**: CT、MRI、X射线、PET等
- **图像处理**: 增强、滤波、缩放、旋转等
- **界面元素**: 工具栏、菜单、对话框等
- **常用操作**: 打开、保存、编辑、查看等
- **医学专科**: 放射科、影像科、核医学等

## 使用方法

### 基本用法

```python
from translate_ts import TSTranslator

# 创建翻译器实例
translator = TSTranslator()

# 翻译TS文件
translator.translate_ts_file('input.ts', 'output_en.ts')
```

### 命令行使用

```bash
# 翻译单个TS文件
python translate_ts.py input.ts

# 指定输出文件
python translate_ts.py input.ts -o output_en.ts
```

### 高级功能

#### 1. 自定义医学术语

编辑 `medical_terms.json` 文件，添加项目特定的术语：

```json
{
  "custom_terms": {
    "自定义术语": "Custom Term",
    "项目特定词汇": "Project Specific Vocabulary"
  }
}
```

#### 2. 翻译质量评估

翻译器会自动评估翻译质量并选择最佳结果：

- 医学术语匹配（权重: 2.0）
- 专业关键词（权重: 1.5）
- 格式规范性（权重: 0.1-0.2）

#### 3. 缓存管理

```python
# 清除翻译缓存
translator.translation_cache.clear()
translator._save_translation_cache()

# 查看缓存统计
print(f"缓存条目数: {len(translator.translation_cache)}")
```

## 翻译示例

### 输入文本
```xml
<source>DICOM文件窗宽窗位调整工具</source>
```

### 翻译过程
1. **术语提取**: 识别"DICOM"、"窗宽"、"窗位"等医学术语
2. **多源翻译**: 使用Google和MyMemory进行翻译
3. **质量评分**: 评估翻译结果的专业性
4. **后处理**: 修正格式和术语大小写

### 输出结果
```xml
<translation>DICOM File Window Width/Level Adjustment Tool</translation>
```

## 配置选项

### 翻译引擎配置

```python
# 禁用某个翻译源
translator._translate_with_mymemory = lambda x: None

# 添加自定义翻译源
def custom_translate(text):
    # 自定义翻译逻辑
    return translated_text
```

### 术语保护配置

```python
# 添加需要保护的术语
protected_terms = ['DICOM', 'ROI', 'MPR']
translator.medical_terms.update({
    term: term for term in protected_terms
})
```

## 性能优化

### 1. 批量翻译
- 使用翻译缓存避免重复翻译
- 预处理提取术语减少API调用
- 智能跳过纯术语文本

### 2. 网络优化
- 设置合理的请求超时时间
- 使用Session复用连接
- 实现重试机制

### 3. 内存管理
- 定期保存翻译缓存
- 限制缓存大小防止内存溢出

## 故障排除

### 常见问题

1. **翻译质量不佳**
   - 检查医学术语词典是否完整
   - 验证网络连接和API可用性
   - 查看翻译评分日志

2. **缓存文件损坏**
   - 删除 `translation_cache.json` 文件
   - 重新运行翻译程序

3. **术语词典加载失败**
   - 检查 `medical_terms.json` 文件格式
   - 验证文件编码为UTF-8

### 调试模式

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看翻译过程
translator.translate_with_medical_context("测试文本")
```

## 扩展开发

### 添加新的翻译源

```python
def _translate_with_custom_api(self, text: str) -> Optional[str]:
    """自定义翻译API"""
    try:
        # 实现自定义翻译逻辑
        response = requests.post('https://api.example.com/translate', {
            'text': text,
            'from': 'zh',
            'to': 'en'
        })
        return response.json()['translation']
    except Exception as e:
        print(f"自定义翻译API错误: {e}")
        return None
```

### 自定义评分算法

```python
def _custom_score_translation(self, translation: str) -> float:
    """自定义翻译评分"""
    score = 0.0
    
    # 添加自定义评分逻辑
    if 'Medical' in translation:
        score += 1.0
        
    return score
```

## 许可证

本工具遵循项目主许可证。使用时请确保遵守相关翻译API的使用条款。

## 贡献

欢迎提交Issue和Pull Request来改进这个翻译工具：

1. 添加新的医学术语
2. 改进翻译质量评估算法
3. 支持更多翻译API
4. 优化性能和用户体验