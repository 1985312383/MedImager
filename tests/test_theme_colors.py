from medimager.utils.theme_colors import qcolor_from_theme


def test_qcolor_from_theme_parses_css_rgba_hex():
    color = qcolor_from_theme("#FFFF0080")

    assert color.red() == 255
    assert color.green() == 255
    assert color.blue() == 0
    assert color.alpha() == 128


def test_qcolor_from_theme_falls_back_for_invalid_values():
    color = qcolor_from_theme("not-a-color", "#112233")

    assert color.name().lower() == "#112233"
