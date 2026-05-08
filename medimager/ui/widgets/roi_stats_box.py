#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROI 统计信息框控件

负责计算ROI统计信息框的大小、位置以及绘制。
"""

from PySide6.QtGui import QPainter, QFont, QPen, QFontMetrics
from PySide6.QtCore import QRect, Qt
from typing import Dict, Optional
from medimager.utils.settings import get_settings_manager
from medimager.utils.theme_colors import qcolor_from_theme


_STAT_FIELD_SETTINGS = {
    "mean": "roi.stats.show_mean",
    "std": "roi.stats.show_std",
    "max": "roi.stats.show_max",
    "min": "roi.stats.show_min",
}

def _get_stats_box_settings():
    """获取信息板设置"""
    try:
        from medimager.utils.theme_manager import get_theme_settings
        
        # 使用统一的主题设置读取函数
        theme_data = get_theme_settings('roi')
        
        return {
            'bg_color': theme_data.get('info_bg_color', '#00000096'),
            'selected_bg_color': theme_data.get('info_selected_bg_color', theme_data.get('info_bg_color', '#00000096')),
            'text_color': theme_data.get('info_text_color', '#FFFFFF'),
            'border_color': theme_data.get('info_border_color', '#FFFFFF'),
            'font_size': theme_data.get('info_font_size', 8),
            'border_radius': theme_data.get('info_radius', 5),
            'padding': theme_data.get('info_padding', 8),
            'precision': theme_data.get('info_precision', 1),
            'style': theme_data.get('info_style', 'default'),
            'value_label': theme_data.get('info_value_label', ''),
            'auto_hide': theme_data.get('info_auto_hide', False),
        }
    except Exception:
        # 默认设置
        return {
            'bg_color': '#00000096',
            'selected_bg_color': '#00000096',
            'text_color': '#FFFFFF',
            'border_color': '#FFFFFF',
            'font_size': 8,
            'border_radius': 5,
            'padding': 8,
            'precision': 1,
            'style': 'default',
            'value_label': '',
            'auto_hide': False,
        }


def _format_number(value: float, precision: int, trim: bool = False) -> str:
    text = f"{value:.{precision}f}"
    if trim and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _get_area_text(stats: Dict[str, float], precision: int, style: str) -> str:
    area_unit = "auto"
    show_count = True
    try:
        settings_manager = get_settings_manager()
        area_unit = settings_manager.get_setting("roi.stats.area_unit", "auto")
        show_count = _as_bool(settings_manager.get_setting("roi.stats.show_count", True))
    except Exception:
        pass

    if style == "radiant":
        count = int(stats.get('count', stats.get('area_px', 0)))
        suffix = f" ({count} px)" if show_count else ""
        if area_unit == "px" or "area_mm2" not in stats:
            return f"Area={count} px"
        if area_unit in ("auto", "cm2"):
            area_cm2 = stats['area_mm2'] / 100.0
            return f"Area={_format_number(area_cm2, 1, trim=False)} cm²{suffix}"
        if area_unit == "mm2":
            return f"Area={_format_number(stats['area_mm2'], precision, trim=False)} mm²{suffix}"
        return f"Count={count}"

    if area_unit == "px" or "area_mm2" not in stats:
        return f"Area: {stats.get('area_px', stats.get('count', 0)):.0f} px²"
    if area_unit == "cm2":
        return f"Area: {stats['area_mm2'] / 100.0:.{precision}f} cm²"
    if area_unit == "auto" and 'area_mm2' in stats:
        return f"Area: {stats['area_mm2']:.{precision}f} mm²"
    if area_unit == "mm2":
        return f"Area: {stats['area_mm2']:.{precision}f} mm²"
    return f"Area: {stats.get('area_px', stats.get('count', 0)):.0f} px²"


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def _stat_field_enabled(field: str) -> bool:
    try:
        setting_key = _STAT_FIELD_SETTINGS[field]
        return _as_bool(get_settings_manager().get_setting(setting_key, True))
    except Exception:
        return True


def get_stats_text(stats: Dict[str, float]) -> str:
    """将统计数据格式化为显示字符串。"""
    settings = _get_stats_box_settings()
    precision = settings['precision']
    style = settings['style']
    area_text = _get_area_text(stats, precision, style)

    if style == "radiant":
        lines = []
        value_label = settings.get('value_label') or ''
        if value_label:
            lines.append(str(value_label))
        mean_parts = []
        if _stat_field_enabled("mean"):
            mean_parts.append(f"Mean={_format_number(stats['mean'], precision, trim=False)}")
        if _stat_field_enabled("std"):
            mean_parts.append(f"SD={_format_number(stats['std'], precision, trim=False)}")
        if mean_parts:
            lines.append(" ".join(mean_parts))
        range_parts = []
        if _stat_field_enabled("max"):
            range_parts.append(f"Max={_format_number(stats['max'], precision, trim=True)}")
        if _stat_field_enabled("min"):
            range_parts.append(f"Min={_format_number(stats['min'], precision, trim=True)}")
        if range_parts:
            lines.append(" ".join(range_parts))
        if _as_bool(get_settings_manager().get_setting("roi.stats.show_area", True)):
            lines.append(area_text)
        return "\n".join(lines)

    lines = []
    if _stat_field_enabled("max"):
        lines.append(f"Max: {stats['max']:.{precision}f}")
    if _stat_field_enabled("min"):
        lines.append(f"Min: {stats['min']:.{precision}f}")
    if _stat_field_enabled("mean"):
        lines.append(f"Mean: {stats['mean']:.{precision}f}")
    if _stat_field_enabled("std"):
        lines.append(f"Std: {stats['std']:.{precision}f}")
    if _as_bool(get_settings_manager().get_setting("roi.stats.show_area", True)):
        lines.append(area_text)
    if _as_bool(get_settings_manager().get_setting("roi.stats.show_count", True)):
        lines.append(f"Count: {stats['count']:.0f}")
    return "\n".join(lines)

def calculate_stats_box_size_rect(stats_text: str, font: QFont) -> QRect:
    """
    根据统计文本和字体计算信息框的纯大小（位置为(0,0)）。
    
    Args:
        stats_text: 要显示的格式化文本。
        font: 用于渲染文本的字体。

    Returns:
        QRect: 包含所需宽度和高度的大小矩形。
    """
    settings = _get_stats_box_settings()
    padding = settings['padding']
    
    fm = QFontMetrics(font)
    text_bound = fm.boundingRect(QRect(), Qt.AlignLeft, stats_text)
    box_width = text_bound.width() + 2 * padding
    box_height = text_bound.height() + 2 * padding
    return QRect(0, 0, box_width, box_height)

def draw_stats_box(painter: QPainter, stats: Dict[str, float], box_rect: QRect, selected: bool = False) -> None:
    """
    在给定的矩形区域内绘制统计信息框。
    
    Args:
        painter: 用于绘制的 QPainter。
        stats: 统计数据字典。
        box_rect: 绘制信息框的目标矩形区域（包含位置和大小）。
    """
    painter.save()

    # 获取配置的设置
    settings = _get_stats_box_settings()
    
    # 设置字体
    font = painter.font()
    font.setPointSize(settings['font_size'])
    painter.setFont(font)
    
    # 获取格式化文本
    stats_text = get_stats_text(stats)
    
    # 绘制背景
    bg_color = qcolor_from_theme(settings['selected_bg_color'] if selected else settings['bg_color'])
    border_color = qcolor_from_theme(settings['border_color'])
    
    painter.setBrush(bg_color)
    painter.setPen(QPen(border_color, 1))
    painter.drawRoundedRect(box_rect, settings['border_radius'], settings['border_radius'])
    
    # 绘制文本
    text_color = qcolor_from_theme(settings['text_color'])
    painter.setPen(text_color)
    
    text_draw_rect = box_rect.adjusted(settings['padding'], settings['padding'], 
                                     -settings['padding'], -settings['padding'])
    painter.drawText(text_draw_rect, Qt.AlignLeft | Qt.AlignTop, stats_text)
    
    painter.restore()
