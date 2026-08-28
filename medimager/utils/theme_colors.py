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


def qcolor_to_theme(color: QColor) -> str:
    """Serialize a QColor using the theme file's CSS ``#RRGGBBAA`` format.

    ``QColor.name(QColor.HexArgb)`` returns ``#AARRGGBB`` which is a different
    byte order from the existing theme files. Keeping this conversion in one
    place prevents alpha values from being silently lost or swapped.
    """
    if not isinstance(color, QColor) or not color.isValid():
        raise ValueError("A valid QColor is required")
    return (
        f"#{color.red():02X}{color.green():02X}{color.blue():02X}"
        f"{color.alpha():02X}"
    )
