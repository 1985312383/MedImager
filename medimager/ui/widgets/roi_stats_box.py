#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROI 统计信息框控件

负责计算ROI统计信息框的大小、位置以及绘制。
"""

from PySide6.QtGui import QPainter, QFont, QColor, QPen, QFontMetrics
from PySide6.QtCore import QRect, Qt
from typing import Dict, Optional

def _get_stats_box_settings():
    """获取信息板设置"""
    try:
        from medimager.utils.theme_manager import get_theme_settings
        
        # 使用统一的主题设置读取函数
        theme_data = get_theme_settings('roi')
        
        return {
            'bg_color': theme_data.get('info_bg_color', '#00000096'),
            'text_color': theme_data.get('info_text_color', '#FFFFFF'),
            'border_color': theme_data.get('info_border_color', '#FFFFFF'),
            'font_size': theme_data.get('info_font_size', 8),
            'border_radius': theme_data.get('info_radius', 5),
            'padding': theme_data.get('info_padding', 8),
            'precision': theme_data.get('info_precision', 1)
        }
    except Exception:
        # 默认设置
        return {
            'bg_color': '#00000096',
            'text_color': '#FFFFFF',
            'border_color': '#FFFFFF',
            'font_size': 8,
            'border_radius': 5,
            'padding': 8,
            'precision': 1
        }

def get_stats_text(stats: Dict[str, float]) -> str:
    """将统计数据格式化为显示字符串。"""
    settings = _get_stats_box_settings()
    precision = settings['precision']
    
    return (
        f"Max: {stats['max']:.{precision}f}\n"
        f"Min: {stats['min']:.{precision}f}\n"
        f"Mean: {stats['mean']:.{precision}f}\n"
        f"Std: {stats['std']:.{precision}f}"
    )

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

def draw_stats_box(painter: QPainter, stats: Dict[str, float], box_rect: QRect) -> None:
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
    bg_color = QColor(settings['bg_color'])
    border_color = QColor(settings['border_color'])
    
    painter.setBrush(bg_color)
    painter.setPen(QPen(border_color, 1))
    painter.drawRoundedRect(box_rect, settings['border_radius'], settings['border_radius'])
    
    # 绘制文本
    text_color = QColor(settings['text_color'])
    painter.setPen(text_color)
    
    text_draw_rect = box_rect.adjusted(settings['padding'], settings['padding'], 
                                     -settings['padding'], -settings['padding'])
    painter.drawText(text_draw_rect, Qt.AlignLeft | Qt.AlignTop, stats_text)
    
    painter.restore()