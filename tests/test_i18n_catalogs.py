import json
from pathlib import Path

import pytest
from medimager.utils.i18n import DEFAULT_LANGUAGE, get_translation_manager
from translation_tools.i18n_check import check_catalogs
from translation_tools.i18n_compile import I18nCompileError, compile_catalogs


def test_compiled_catalogs_have_expected_messages():
    catalog_path = Path("medimager/i18n/compiled/en_US.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert payload["meta"]["language"] == "en_US"
    assert payload["messages"]["dialogs.custom_wl.title"] == "Custom Window/Level"
    assert payload["messages"]["viewer.active_view"] == "Active view: {position}"


def test_checked_in_compiled_catalogs_match_locale_sources(tmp_path):
    generated_dir = tmp_path / "compiled"
    generated = compile_catalogs(Path("medimager/i18n/locales"), generated_dir)

    checked_in_dir = Path("medimager/i18n/compiled")
    for generated_path in generated:
        checked_in_path = checked_in_dir / generated_path.name
        assert checked_in_path.read_text(encoding="utf-8") == generated_path.read_text(
            encoding="utf-8"
        )


def test_runtime_default_language_is_english():
    assert DEFAULT_LANGUAGE == "en_US"


def test_non_chinese_catalogs_do_not_contain_chinese_text():
    assert check_catalogs() == []


def test_locale_files_do_not_embed_legacy_source_maps():
    locale_dir = Path("medimager/i18n/locales")

    for locale_file in locale_dir.glob("*.yml"):
        text = locale_file.read_text(encoding="utf-8")
        assert "\nlegacy:" not in text
        assert "legacy." not in text


def test_translation_manager_formats_and_falls_back(qapp):
    manager = get_translation_manager()
    original_language = manager.current_language()
    try:
        assert manager.set_language("en_US")
        assert manager.t("viewer.active_view", position="A") == "Active view: A"
        assert manager.t("missing.example") == "missing.example"
    finally:
        manager.set_language(original_language)


def test_compiled_catalogs_do_not_embed_legacy_source_maps():
    catalog_path = Path("medimager/i18n/compiled/en_US.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert "legacy_source_map" not in payload


def test_migrated_main_window_key_uses_stable_catalog_key(qapp):
    manager = get_translation_manager()
    original_language = manager.current_language()
    try:
        assert manager.set_language("en_US")
        assert manager.t("mainwindow.file_f") == "File (&F)"
        assert manager.t("mainwindow.toggle_series_panel") == "Toggle series panel"
    finally:
        manager.set_language(original_language)


def test_migrated_settings_dialog_key_uses_stable_catalog_key(qapp):
    manager = get_translation_manager()
    original_language = manager.current_language()
    try:
        assert manager.set_language("en_US")
        assert manager.t("settingsdialog.settings") == "Settings"
        assert manager.t("settingsdialog.sync_scope_same_study") == "Same study (recommended)"
    finally:
        manager.set_language(original_language)


def test_i18n_compile_rejects_placeholder_mismatch(tmp_path):
    locales = tmp_path / "locales"
    compiled = tmp_path / "compiled"
    locales.mkdir()

    (locales / "zh_CN.yml").write_text(
        """
meta:
  language: zh_CN
  name: 简体中文
  fallback: null
viewer:
  active_view: "活动视图: {position}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (locales / "en_US.yml").write_text(
        """
meta:
  language: en_US
  name: English
  fallback: zh_CN
viewer:
  active_view: "Active view: {view}"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(I18nCompileError, match="placeholder mismatch"):
        compile_catalogs(locales, compiled)
