#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译文件编译脚本
演示如何将 .ts 文件编译为 .qm 文件
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom


def find_qt_tool(tool_name: str) -> str:
    """在常见的 PySide6 和系统路径中查找 Qt 工具 (lrelease)"""
    # 1. 检查 PySide6 的安装路径
    try:
        import PySide6
        pyside6_dir = Path(PySide6.__file__).parent
        tool_path = pyside6_dir / tool_name
        if tool_path.exists():
            return str(tool_path)
    except ImportError:
        pass

    # 2. 检查系统 PATH
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path

    # 3. 在 Python Scripts 目录中查找 (Windows)
    if sys.platform == "win32":
        scripts_dir = Path(sys.prefix) / "Scripts"
        tool_path = scripts_dir / tool_name
        if tool_path.exists():
            return str(tool_path)

    return None


def compile_ts_to_qm(ts_file: Path, lrelease_path: str) -> bool:
    """使用 lrelease 将 .ts 文件编译为 .qm 文件"""
    qm_file = ts_file.with_suffix('.qm')
    command = [lrelease_path, str(ts_file), "-qm", str(qm_file)]
    
    try:
        print(f"执行编译: {' '.join(command)}")
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        if result.returncode == 0:
            print(f"✓ 编译成功: {ts_file.name} -> {qm_file.name}")
            return True
        else:
            print(f"✗ 编译失败: {ts_file.name}")
            print(f"  错误: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"✗ 错误: 未找到 'lrelease' 工具。请确保它在系统PATH中或PySide6已正确安装。")
        return False
    except subprocess.CalledProcessError as e:
        print(f"✗ 编译命令执行失败: {ts_file.name}")
        print(f"  错误: {e.stderr}")
        return False
    except Exception as e:
        print(f"✗ 发生未知错误: {e}")
        return False


def generate_ts_file(file_path: Path, language: str, translations: dict):
    """使用ElementTree生成格式正确的.ts文件"""
    print(f"生成TS文件: {file_path}")

    # 创建根元素
    ts_node = ET.Element("TS", version="2.1", language=language)

    for context_name, messages in translations.items():
        context_node = ET.SubElement(ts_node, "context")
        name_node = ET.SubElement(context_node, "name")
        name_node.text = context_name

        for msg_info in messages:
            message_node = ET.SubElement(context_node, "message")
            location_node = ET.SubElement(message_node, "location", filename=msg_info["filename"])
            source_node = ET.SubElement(message_node, "source")
            source_node.text = msg_info["source"]
            translation_node = ET.SubElement(message_node, "translation")
            translation_node.text = msg_info["translation"]

    # 格式化XML使其可读
    xml_str = ET.tostring(ts_node, 'utf-8')
    dom = minidom.parseString(xml_str)
    pretty_xml_str = dom.toprettyxml(indent="    ", encoding="utf-8")

    # 写入文件，并添加DOCTYPE
    with open(file_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE TS>\n')
        f.write(pretty_xml_str[pretty_xml_str.find(b"?>")+2:].strip())


def get_translation_data():
    """返回所有翻译数据"""
    
    # 定义所有源字符串和它们的文件位置
    source_data = {
        "ColorButton": [
            {"source": "选择...", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "选择颜色", "filename": "../ui/dialogs/settings_dialog.py"},
        ],
        "MainWindow": [
            {"source": "MedImager - DICOM 查看器与图像分析工具", "filename": "../ui/main_window.py"},
            {"source": "就绪", "filename": "../ui/main_window.py"},
            {"source": "鼠标位置: (0, 0)", "filename": "../ui/main_window.py"},
            {"source": "像素值: 0.00 HU", "filename": "../ui/main_window.py"},
            {"source": "缩放", "filename": "../ui/main_window.py"},
            {"source": "窗宽: 0 L: 0", "filename": "../ui/main_window.py"},
            {"source": "文件(&F)", "filename": "../ui/main_window.py"},
            {"source": "打开DICOM文件夹(&D)", "filename": "../ui/main_window.py"},
            {"source": "打开包含DICOM序列的文件夹", "filename": "../ui/main_window.py"},
            {"source": "打开图像文件(&I)", "filename": "../ui/main_window.py"},
            {"source": "打开单张图像文件 (DICOM, PNG, JPG, BMP, NPY)", "filename": "../ui/main_window.py"},
            {"source": "退出(&X)", "filename": "../ui/main_window.py"},
            {"source": "退出应用程序", "filename": "../ui/main_window.py"},
            {"source": "查看(&V)", "filename": "../ui/main_window.py"},
            {"source": "重置视图(&R)", "filename": "../ui/main_window.py"},
            {"source": "重置图像查看器到默认状态", "filename": "../ui/main_window.py"},
            {"source": "显示/隐藏序列面板", "filename": "../ui/main_window.py"},
            {"source": "显示/隐藏信息面板", "filename": "../ui/main_window.py"},
            {"source": "窗位(&W)", "filename": "../ui/main_window.py"},
            {"source": "自动", "filename": "../ui/main_window.py"},
            {"source": "腹部", "filename": "../ui/main_window.py"},
            {"source": "脑窗", "filename": "../ui/main_window.py"},
            {"source": "骨窗", "filename": "../ui/main_window.py"},
            {"source": "肺窗", "filename": "../ui/main_window.py"},
            {"source": "纵隔", "filename": "../ui/main_window.py"},
            {"source": "设置为 {name}: W:{width} L:{level}", "filename": "../ui/main_window.py"},
            {"source": "自定义", "filename": "../ui/main_window.py"},
            {"source": "手动设置窗宽和窗位", "filename": "../ui/main_window.py"},
            {"source": "工具(&T)", "filename": "../ui/main_window.py"},
            {"source": "测试(&T)", "filename": "../ui/main_window.py"},
            {"source": "加载模型", "filename": "../ui/main_window.py"},
            {"source": "加载水模", "filename": "../ui/main_window.py"},
            {"source": "加载用于测试的NPY格式水模图像", "filename": "../ui/main_window.py"},
            {"source": "加载Gammex模体", "filename": "../ui/main_window.py"},
            {"source": "加载用于测试的DICOM格式Gammex模体", "filename": "../ui/main_window.py"},
            {"source": "水模", "filename": "../ui/main_window.py"},
            {"source": "Gammex模体", "filename": "../ui/main_window.py"},
            {"source": "设置(&S)", "filename": "../ui/main_window.py"},
            {"source": "首选项(&P)", "filename": "../ui/main_window.py"},
            {"source": "打开设置对话框", "filename": "../ui/main_window.py"},
            {"source": "帮助(&H)", "filename": "../ui/main_window.py"},
            {"source": "关于MedImager(&A)", "filename": "../ui/main_window.py"},
            {"source": "显示关于信息", "filename": "../ui/main_window.py"},
            {"source": "关于", "filename": "../ui/main_window.py"},
            {"source": "关于 MedImager", "filename": "../ui/main_window.py"},
            {"source": "X: {}, Y: {}", "filename": "../ui/main_window.py"},
            {"source": "像素值: {:.2f} HU", "filename": "../ui/main_window.py"},
            {"source": "缩放: {:.1%}", "filename": "../ui/main_window.py"},
            {"source": "W: {} L: {}", "filename": "../ui/main_window.py"},
            {"source": "选择DICOM文件夹", "filename": "../ui/main_window.py"},
            {"source": "正在加载 {} 个DICOM文件...", "filename": "../ui/main_window.py"},
            {"source": "加载DICOM序列失败", "filename": "../ui/main_window.py"},
            {"source": "选择图像文件", "filename": "../ui/main_window.py"},
            {"source": "所有支持的文件 (*.dcm *.png *.jpg *.jpeg *.bmp *.npy);;DICOM 文件 (*.dcm);;PNG 文件 (*.png);;JPEG 文件 (*.jpg *.jpeg);;BMP 文件 (*.bmp);;NumPy 数组 (*.npy)", "filename": "../ui/main_window.py"},
            {"source": "加载文件失败", "filename": "../ui/main_window.py"},
            {"source": "设置", "filename": "../ui/main_window.py"},
            {"source": "设置已保存", "filename": "../ui/main_window.py"},
            {"source": "语言设置将在下次启动时完全生效。", "filename": "../ui/main_window.py"},
            {"source": "语言设置", "filename": "../ui/main_window.py"},
            {"source": "语言设置已更改。是否立即重启应用程序以应用新的语言设置？\n\n点击'是'立即重启，点击'否'稍后手动重启。", "filename": "../ui/main_window.py"},
            {"source": "设置已成功保存。", "filename": "../ui/main_window.py"},
            {"source": "椭圆", "filename": "../ui/main_toolbar.py"},
            {"source": "绘制椭圆ROI", "filename": "../ui/main_toolbar.py"},
            {"source": "矩形", "filename": "../ui/main_toolbar.py"},
            {"source": "绘制矩形ROI", "filename": "../ui/main_toolbar.py"},
            {"source": "圆形", "filename": "../ui/main_toolbar.py"},
            {"source": "绘制圆形ROI", "filename": "../ui/main_toolbar.py"},
        ],
        "SettingsDialog": [
            {"source": "设置", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "通用", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "工具", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "通用设置", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "界面语言", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "简体中文", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "English", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "语言:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "界面主题", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "主题:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "工具设置", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "ROI设置", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "自定义设置", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "外观", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "边框颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "填充颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "选中时颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "边框粗细:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "锚点", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "锚点颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "锚点大小:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "测量工具", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "线条颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "线条宽度:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "信息面板", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "背景颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "文本颜色:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "字体大小:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "数值精度:", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "鼠标离开时自动隐藏", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "确定", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "取消", "filename": "../ui/dialogs/settings_dialog.py"},
            {"source": "恢复默认", "filename": "../ui/dialogs/settings_dialog.py"},
        ],
        "MeasurementTool": [
            {"source": "测量工具已激活 - 点击设置起始点", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "已设置起始点 - 点击设置终点（右键取消）", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "测量已取消", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "测量线已删除", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "拖拽起始点", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "拖拽终点", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "拖拽测量线", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "拖拽完成", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "预览距离: {:.1f} mm", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "预览距离: {:.2f} mm", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "预览距离: 无法计算（缺少像素间距信息）", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "测量距离: {:.1f} mm", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "测量距离: {:.2f} mm", "filename": "../ui/tools/measurement_tool.py"},
            {"source": "测量距离: 无法计算（缺少像素间距信息）", "filename": "../ui/tools/measurement_tool.py"},
        ]
    }

    # 英文翻译: 使用字典映射以保证准确性
    en_translations_map = {
        "ColorButton": {
            "选择...": "Select...",
            "选择颜色": "Select Color",
        },
        "MainWindow": {
            "MedImager - DICOM 查看器与图像分析工具": "MedImager - DICOM Viewer & Analysis Tool",
            "就绪": "Ready",
            "鼠标位置: (0, 0)": "Mouse: (0, 0)",
            "像素值: 0.00 HU": "Value: 0.00 HU",
            "缩放": "Zoom",
            "窗宽: 0 L: 0": "W: 0 L: 0",
            "文件(&F)": "File(&F)",
            "打开DICOM文件夹(&D)": "Open DICOM Folder(&D)",
            "打开包含DICOM序列的文件夹": "Open a folder containing a DICOM series",
            "打开图像文件(&I)": "Open Image File(&I)",
            "打开单张图像文件 (DICOM, PNG, JPG, BMP, NPY)": "Open a single image file (DICOM, PNG, JPG, BMP, NPY)",
            "退出(&X)": "Exit(&X)",
            "退出应用程序": "Exit the application",
            "查看(&V)": "View(&V)",
            "重置视图(&R)": "Reset View(&R)",
            "重置图像查看器到默认状态": "Reset the image viewer to its default state",
            "显示/隐藏序列面板": "Show/Hide Series Panel",
            "显示/隐藏信息面板": "Show/Hide Info Panel",
            "窗位(&W)": "Windowing(&W)",
            "自动": "Auto",
            "腹部": "Abdomen",
            "脑窗": "Brain",
            "骨窗": "Bone",
            "肺窗": "Lung",
            "纵隔": "Mediastinum",
            "设置为 {name}: W:{width} L:{level}": "Set to {name}: W:{width} L:{level}",
            "自定义": "Custom",
            "手动设置窗宽和窗位": "Manually set window width and level",
            "工具(&T)": "Tools(&T)",
            "测试(&T)": "Test(&T)",
            "加载模型": "Load Models",
            "加载水模": "Load Water Phantom",
            "加载用于测试的NPY格式水模图像": "Load NPY format water phantom image for testing",
            "加载Gammex模体": "Load Gammex Phantom",
            "加载用于测试的DICOM格式Gammex模体": "Load DICOM format Gammex phantom for testing",
            "水模": "Water Phantom",
            "Gammex模体": "Gammex Phantom",
            "设置(&S)": "Settings(&S)",
            "首选项(&P)": "Preferences(&P)",
            "打开设置对话框": "Open settings dialog",
            "帮助(&H)": "Help(&H)",
            "关于MedImager(&A)": "About MedImager(&A)",
            "显示关于信息": "Show about information",
            "关于": "About",
            "关于 MedImager": "About MedImager",
            "X: {}, Y: {}": "X: {}, Y: {}",
            "像素值: {:.2f} HU": "Value: {:.2f} HU",
            "缩放: {:.1%}": "Zoom: {:.1%}",
            "W: {} L: {}": "W: {} L: {}",
            "选择DICOM文件夹": "Select DICOM Folder",
            "正在加载 {} 个DICOM文件...": "Loading {} DICOM files...",
            "加载DICOM序列失败": "Failed to Load DICOM Series",
            "选择图像文件": "Select Image File",
            "所有支持的文件 (*.dcm *.png *.jpg *.jpeg *.bmp *.npy);;DICOM 文件 (*.dcm);;PNG 文件 (*.png);;JPEG 文件 (*.jpg *.jpeg);;BMP 文件 (*.bmp);;NumPy 数组 (*.npy)": "All Supported Files (*.dcm *.png *.jpg *.jpeg *.bmp *.npy);;DICOM Files (*.dcm);;PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;BMP Files (*.bmp);;NumPy Arrays (*.npy)",
            "加载文件失败": "Failed to Load File",
            "设置": "Settings",
            "设置已保存": "Settings Saved",
            "语言设置将在下次启动时完全生效。": "Language settings will take full effect the next time you start the application.",
            "语言设置": "Language Settings",
            "语言设置已更改。是否立即重启应用程序以应用新的语言设置？\n\n点击'是'立即重启，点击'否'稍后手动重启。": "Language settings have been changed. Do you want to restart the application immediately to apply the new language settings?\n\nClick 'Yes' to restart now, or 'No' to restart manually later.",
            "设置已成功保存。": "Settings have been saved successfully.",
            "椭圆": "Ellipse",
            "绘制椭圆ROI": "Draw ellipse ROI",
            "矩形": "Rectangle",
            "绘制矩形ROI": "Draw rectangle ROI",
            "圆形": "Circle",
            "绘制圆形ROI": "Draw circle ROI",
        },
        "SettingsDialog": {
            "设置": "Settings",
            "通用": "General",
            "工具": "Tools",
            "通用设置": "General Settings",
            "界面语言": "UI Language",
            "简体中文": "Simplified Chinese",
            "English": "English",
            "语言:": "Language:",
            "界面主题": "UI Theme",
            "主题:": "Theme:",
            "工具设置": "Tools Settings",
            "ROI设置": "ROI Settings",
            "自定义设置": "Custom Settings",
            "外观": "Appearance",
            "边框颜色:": "Border Color:",
            "填充颜色:": "Fill Color:",
            "选中时颜色:": "Selected Color:",
            "边框粗细:": "Border Width:",
            "锚点": "Anchor",
            "锚点颜色:": "Anchor Color:",
            "锚点大小:": "Anchor Size:",
            "测量工具": "Measurement Tool",
            "线条颜色:": "Line Color:",
            "线条宽度:": "Line Width:",
            "信息面板": "Info Panel",
            "背景颜色:": "Background Color:",
            "文本颜色:": "Text Color:",
            "字体大小:": "Font Size:",
            "数值精度:": "Precision:",
            "鼠标离开时自动隐藏": "Auto-hide on mouse leave",
            "确定": "OK",
            "取消": "Cancel",
            "恢复默认": "Restore Defaults",
        },
        "MeasurementTool": {
            "测量工具已激活 - 点击设置起始点": "Measurement tool activated - Click to set start point",
            "已设置起始点 - 点击设置终点（右键取消）": "Start point set - Click to set end point (Right-click to cancel)",
            "测量已取消": "Measurement cancelled",
            "测量线已删除": "Measurement line deleted",
            "拖拽起始点": "Dragging start point",
            "拖拽终点": "Dragging end point",
            "拖拽测量线": "Dragging measurement line",
            "拖拽完成": "Drag completed",
            "预览距离: {:.1f} mm": "Preview distance: {:.1f} mm",
            "预览距离: {:.2f} mm": "Preview distance: {:.2f} mm",
            "预览距离: 无法计算（缺少像素间距信息）": "Preview distance: Cannot calculate (missing pixel spacing)",
            "测量距离: {:.1f} mm": "Measurement distance: {:.1f} mm",
            "测量距离: {:.2f} mm": "Measurement distance: {:.2f} mm",
            "测量距离: 无法计算（缺少像素间距信息）": "Measurement distance: Cannot calculate (missing pixel spacing)",
        }
    }

    # 将翻译合并到源数据结构中
    en_data = {}
    for context, messages in source_data.items():
        en_data[context] = []
        for msg in messages:
            en_msg = msg.copy()
            # 从映射中查找翻译
            translation_text = en_translations_map.get(context, {}).get(en_msg["source"], "")
            if not translation_text:
                print(f"警告: 在 '{context}' 上下文中未找到源文本 '{en_msg['source']}' 的英文翻译。")
            en_msg["translation"] = translation_text
            en_data[context].append(en_msg)
    
    # 创建中文数据（翻译与原文相同）
    zh_data = {}
    for context, messages in source_data.items():
        zh_data[context] = []
        for msg in messages:
            zh_msg = msg.copy()
            zh_msg["translation"] = zh_msg["source"]
            zh_data[context].append(zh_msg)

    return en_data, zh_data


def main():
    """主函数"""
    print("=" * 60)
    print("MedImager 翻译文件生成和编译工具")
    print("=" * 60)
    
    # 1. 获取翻译数据并生成 .ts 文件
    en_data, zh_data = get_translation_data()
    translations_dir = Path("medimager") / "translations"
    translations_dir.mkdir(exist_ok=True)
    
    generate_ts_file(translations_dir / "en_US.ts", "en_US", en_data)
    generate_ts_file(translations_dir / "zh_CN.ts", "zh_CN", zh_data)

    # 2. 编译 .ts 文件
    lrelease_path = find_qt_tool("lrelease.exe" if sys.platform == "win32" else "lrelease")
    if not lrelease_path:
        print("错误: 未能找到 'lrelease' 工具。")
        print("请确保 PySide6 已安装，或将 Qt bin 目录添加到系统 PATH。")
        return

    print(f"✓ 使用 lrelease 工具: {lrelease_path}")
    
    print("\n开始编译...")
    ts_files = list(translations_dir.glob("*.ts"))
    success_count = 0
    for ts_file in ts_files:
        if compile_ts_to_qm(ts_file, lrelease_path):
            success_count += 1
    
    print(f"\n编译完成! 成功: {success_count}/{len(ts_files)}")
    
    # 显示编译后的文件
    qm_files = list(translations_dir.glob("*.qm"))
    if qm_files:
        print("\n编译后的 .qm 文件:")
        for qm_file in qm_files:
            print(f"  - {qm_file.name}")
            
    print("\n" + "=" * 60)
    print("国际化工作流程说明:")
    print("=" * 60)
    print("1. 在代码中使用 self.tr('文本') 包裹所有用户界面字符串")
    print("2. 运行 pylupdate6 或手动提取可翻译字符串到 .ts 文件")
    print("3. 使用 Qt Linguist 工具编辑 .ts 文件进行翻译")
    print("4. 使用 lrelease 工具将 .ts 文件编译为 .qm 文件")
    print("5. 在应用程序中加载 .qm 文件实现界面翻译")
    print("\n注意: 本演示中的 .qm 文件是模拟生成的。")
    print("在实际项目中，需要安装完整的 Qt 工具链来生成真正的 .qm 文件。")


if __name__ == "__main__":
    main() 