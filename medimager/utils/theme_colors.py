from PySide6.QtGui import QColor


def qcolor_from_theme(value: str, fallback: str = "#000000") -> QColor:
    """Parse theme colors, including CSS-style #RRGGBBAA alpha values."""
    color_text = str(value or fallback).strip()
    if len(color_text) == 9 and color_text.startswith("#"):
        try:
            return QColor(
                int(color_text[1:3], 16),
                int(color_text[3:5], 16),
                int(color_text[5:7], 16),
                int(color_text[7:9], 16),
            )
        except ValueError:
            color_text = fallback

    color = QColor(color_text)
    if not color.isValid():
        color = QColor(fallback)
    return color
