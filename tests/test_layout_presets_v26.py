from medimager.core.hanging_protocols import HangingProtocolId
from medimager.core.layout_presets import (
    LayoutApplicationService,
    LayoutContext,
    LayoutPreset,
    LayoutSpec,
    UserLayoutPresetStore,
    builtin_layout_presets,
)


def test_layout_spec_roundtrips_grid_and_special_legacy_values():
    grid = LayoutSpec.from_legacy((2, 3))
    assert grid.to_document() == {
        "schema": 1,
        "kind": "grid",
        "rows": 2,
        "columns": 3,
    }
    assert grid.to_legacy() == (2, 3)

    special = LayoutSpec.from_legacy(
        {"type": "horizontal_split", "left_ratio": 0.7, "right_split": True}
    )
    assert special.kind == "special"
    assert special.ratios == (0.7, 0.5)
    assert special.to_legacy()["left_ratio"] == 0.7


def test_builtin_gallery_has_stable_clinical_presets():
    presets = builtin_layout_presets()
    assert [item.preset_id for item in presets[:4]] == [
        "study_overview",
        "ct_comparison",
        "mr_neuro",
        "current_mpr",
    ]
    assert presets[3].hanging_protocol is HangingProtocolId.CURRENT_MPR


def test_layout_application_rolls_back_after_assignment_failure():
    events = []
    service = LayoutApplicationService(
        capture=lambda: "before",
        restore=lambda value: events.append(("restore", value)),
        apply_layout=lambda spec: events.append(("layout", spec)) or True,
        apply_hanging=lambda protocol: 0,
        enter_mpr=lambda: True,
        persist=lambda: events.append(("persist", None)),
    )
    preset = LayoutPreset(
        "test",
        "Test",
        "",
        "",
        LayoutSpec(rows=1, columns=2),
        HangingProtocolId.CT_COMPARISON,
    )
    result = service.apply(preset, LayoutContext(None, (object(),)))
    assert not result.success
    assert events[-1] == ("restore", "before")


def test_user_layout_store_rejects_duplicate_names_and_keeps_geometry_only():
    settings = {}
    store = UserLayoutPresetStore(settings.get, settings.__setitem__)
    saved = store.save("My comparison", LayoutSpec(rows=1, columns=2))
    assert saved.preset_id.startswith("user_")
    assert "series" not in repr(settings)

    try:
        store.save("my COMPARISON", LayoutSpec(rows=2, columns=2))
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("duplicate user preset should be rejected")


def test_user_layout_store_reads_v1_and_upgrades_only_after_mutation():
    legacy = {
        "schema_version": 1,
        "presets": [
            {
                "preset_id": "legacy",
                "title": "Legacy geometry",
                "layout": LayoutSpec(rows=2, columns=3).to_document(),
            }
        ],
    }
    settings = {"layout_presets.document": legacy}
    store = UserLayoutPresetStore(settings.get, settings.__setitem__)

    loaded = store.load()

    assert loaded[0].favorite is False
    assert loaded[0].last_used_at == 0
    assert settings["layout_presets.document"] is legacy

    updated = store.toggle_favorite("legacy")
    document = settings["layout_presets.document"]

    assert updated is not None and updated.favorite
    assert document["schema_version"] == 2
    assert document["presets"][0] == {
        "preset_id": "legacy",
        "title": "Legacy geometry",
        "layout": LayoutSpec(rows=2, columns=3).to_document(),
        "favorite": True,
        "last_used_at": 0,
    }
    assert "patient" not in repr(document).casefold()
    assert "series" not in repr(document).casefold()


def test_user_layout_favorites_and_recent_have_deterministic_ordering():
    settings = {}
    store = UserLayoutPresetStore(settings.get, settings.__setitem__)
    first = store.save("First", LayoutSpec(rows=1, columns=1))
    second = store.save("Second", LayoutSpec(rows=1, columns=2))
    third = store.save("Third", LayoutSpec(rows=2, columns=2))

    assert store.mark_used(first.preset_id, used_at=100) is not None
    assert store.mark_used(second.preset_id, used_at=300) is not None
    assert store.mark_used(third.preset_id, used_at=200) is not None
    assert store.toggle_favorite(first.preset_id, True) is not None
    assert store.toggle_favorite(third.preset_id, True) is not None

    assert [item.title_key for item in store.load()] == [
        "Third",
        "First",
        "Second",
    ]
    assert [item.title_key for item in store.favorites()] == ["Third", "First"]
    assert [item.title_key for item in store.recent(2)] == ["Second", "Third"]

    unfavorited = store.toggle_favorite(third.preset_id)
    assert unfavorited is not None and not unfavorited.favorite
    assert [item.title_key for item in store.favorites()] == ["First"]


def test_user_layout_metadata_apis_are_bounded_and_safe_for_missing_ids():
    settings = {}
    store = UserLayoutPresetStore(settings.get, settings.__setitem__)
    for index in range(20):
        store.save(f"Layout {index:02d}", LayoutSpec(rows=1, columns=1))

    assert store.mark_used("missing", used_at=1) is None
    assert store.toggle_favorite("missing") is None
    assert len(store.recent(100)) <= 20

    try:
        store.save("Overflow", LayoutSpec(rows=1, columns=1))
    except ValueError as error:
        assert "limit reached" in str(error)
    else:
        raise AssertionError("the user layout store must remain bounded")


def test_layout_dropdown_exposes_all_saved_presets_and_favorite_toggle(qapp):
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QPushButton, QToolButton

    from medimager.ui.widgets.layout_grid_selector import LayoutDropdown

    settings = {}
    store = UserLayoutPresetStore(settings.get, settings.__setitem__)
    first = store.save("CT comparison custom", LayoutSpec(rows=1, columns=2))
    second = store.save("MR review custom", LayoutSpec(rows=2, columns=2))
    store.mark_used(second.preset_id, used_at=20)
    store.toggle_favorite(first.preset_id, True)

    dropdown = LayoutDropdown()
    favorite_spy = QSignalSpy(dropdown.favorite_toggled)
    dropdown.set_user_presets(store.load())

    apply_titles = {
        button.text() for button in dropdown.saved_content.findChildren(QPushButton)
    }
    assert apply_titles == {"CT comparison custom", "MR review custom"}
    stars = dropdown.saved_content.findChildren(QToolButton)
    assert len(stars) == 2
    checked = next(button for button in stars if button.isChecked())
    checked.click()
    assert favorite_spy.count() == 1
    assert favorite_spy.at(0)[0] == first.preset_id
    assert favorite_spy.at(0)[1] is False
    dropdown.close()
