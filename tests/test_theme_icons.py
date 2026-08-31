import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from medimager.utils.settings import SettingsManager
from medimager.utils.theme_manager import ThemeManager


def test_runtime_svg_icons_are_valid_and_use_viewbox():
    icons_dir = Path("medimager/icons")
    for icon_path in icons_dir.glob("*.svg"):
        root = ET.parse(icon_path).getroot()
        assert root.tag.endswith("svg"), icon_path
        assert root.attrib.get("viewBox"), icon_path


def test_themed_svg_icon_renders_at_requested_device_pixel_ratio(qapp):
    settings = SettingsManager(app_name="MedImagerTestDprIcon", use_json=True)
    settings.set_setting("ui_theme", "dark")
    manager = ThemeManager(settings)
    icon = manager.create_themed_icon("medimager/icons/angle.svg")

    pixmap = icon.pixmap(QSize(24, 24), 2.0)

    assert not icon.isNull()
    assert pixmap.devicePixelRatio() == 2.0
    assert pixmap.deviceIndependentSize().toSize() == QSize(24, 24)


def test_highlight_text_color_uses_the_higher_contrast_choice():
    assert ThemeManager._contrasting_text_color("#0063B1") == "#FFFFFF"
    assert ThemeManager._contrasting_text_color("#FFD740") == "#000000"


def test_outlined_toggle_icon_preserves_readable_foreground_when_checked(
    qapp,
    tmp_path,
):
    settings = SettingsManager(
        app_name="MedImagerOutlinedToggleIcon",
        use_json=True,
        config_dir=tmp_path,
    )
    settings.set_setting("ui_theme", "light")
    manager = ThemeManager(settings)
    icon = manager.create_themed_icon(
        "medimager/icons/chain.svg",
        preserve_on_color=True,
    )

    off_image = icon.pixmap(
        QSize(24, 24),
        QIcon.Mode.Normal,
        QIcon.State.Off,
    ).toImage()
    on_image = icon.pixmap(
        QSize(24, 24),
        QIcon.Mode.Normal,
        QIcon.State.On,
    ).toImage()

    assert not off_image.isNull()
    assert on_image == off_image
