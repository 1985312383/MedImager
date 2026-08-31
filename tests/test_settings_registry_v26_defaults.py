from medimager.core.settings_registry import (
    ApplyPolicy,
    DEFAULT_SETTINGS_REGISTRY,
    SETTINGS,
)


def test_v26_user_visible_registry_defaults_are_typed_and_complete():
    expected = {
        "ui.density": "compact",
        "ui.icon_size": 24,
        "ui.font_scale": 100,
        "toolbar.group_order": ["browse", "measure", "compare", "advanced"],
        "toolbar.visible_groups": ["browse", "measure", "compare", "advanced"],
        "toolbar.show_labels": False,
        "overlay.show_orientation": True,
        "overlay.show_slice_position": True,
        "overlay.show_scale": True,
        "overlay.show_patient": True,
        "overlay.show_pixel_value": False,
        "sync.position_mode": "auto_lps",
        "sync.window_level": True,
        "sync.zoom": False,
        "sync.pan": False,
        "sync.reference_lines": True,
        "sync.shared_cursor": True,
        "recent_studies.max_items": 20,
        "cache.demo.keep": True,
    }

    defaults = DEFAULT_SETTINGS_REGISTRY.defaults()
    for key, value in expected.items():
        assert defaults[key] == value
        assert SETTINGS[key].default == value

    assert SETTINGS["cache.demo.keep"].apply_policy is ApplyPolicy.NEXT_LOAD


def test_v26_registry_coercion_clamps_ranges_and_rejects_invalid_choices():
    registry = DEFAULT_SETTINGS_REGISTRY

    assert registry.coerce("ui.icon_size", 3) == 16
    assert registry.coerce("ui.icon_size", 1000) == 40
    assert registry.coerce("ui.font_scale", 20) == 80
    assert registry.coerce("ui.font_scale", 999) == 150
    assert registry.coerce("ui.density", "spacious") == "compact"
    assert registry.coerce("sync.position_mode", "manual") == "auto_lps"

    default_order = ["browse", "measure", "compare", "advanced"]
    assert registry.coerce(
        "toolbar.group_order", ["measure", "browse", "advanced", "compare"]
    ) == ["measure", "browse", "advanced", "compare"]
    assert registry.coerce(
        "toolbar.group_order", ["browse", "browse", "compare", "advanced"]
    ) == default_order
    assert registry.coerce(
        "toolbar.visible_groups", ["browse", "measure"]
    ) == ["browse", "measure"]
    assert registry.coerce("toolbar.visible_groups", ["unknown"]) == default_order


def test_registry_returns_independent_mutable_defaults():
    first = DEFAULT_SETTINGS_REGISTRY.defaults()
    second = DEFAULT_SETTINGS_REGISTRY.defaults()
    first["toolbar.group_order"].reverse()

    assert second["toolbar.group_order"] == [
        "browse",
        "measure",
        "compare",
        "advanced",
    ]
