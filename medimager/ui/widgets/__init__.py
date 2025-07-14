"""
UI组件模块

包含各种自定义UI组件。
"""

from .magnifier import MagnifierWidget
from .roi_stats_box import get_stats_text, calculate_stats_box_size_rect, draw_stats_box

__all__ = [
    'MagnifierWidget',
    'get_stats_text', 
    'calculate_stats_box_size_rect',
    'draw_stats_box'
] 