import json

import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QDialogButtonBox

from medimager.core.privacy import get_privacy_service
from medimager.core.settings_registry import (
    DEFAULT_SETTINGS_REGISTRY,
    SETTINGS,
    SettingsRegistry,
    SettingsSession,
)
from medimager.core.storage_cleanup import StorageCategory, StorageCleanupService
from medimager.ui.dialogs.settings_dialog import SIMPLE_SETTING_KEYS, SettingsDialog
from medimager.utils.i18n import get_translation_manager
from medimager.utils.settings import SettingsManager


class _MemoryManager:
    registry = DEFAULT_SETTINGS_REGISTRY

    def __init__(self):
        self.values = self.registry.defaults()

    def get_typed(self, setting):
        spec = setting if hasattr(setting, "key") else self.registry.require(setting)
        return spec.coerce(self.values.get(spec.key, spec.default))

    def set_many(self, values):
        self.values.update(values)


def _json_manager(tmp_path, name="MedImagerSettingsV26"):
    manager = SettingsManager(app_name=name, use_json=True)
    manager.config_dir = tmp_path / name
    manager.config_file = manager.config_dir / "settings.json"
    manager._settings_data = {"settings.schema_version": 2}
    manager.save_settings()
    return manager


def test_registry_coerces_ranges_and_rejects_duplicate_keys():
    history = SETTINGS["workspace.history_limit"]
    assert history.coerce("45") == 45
    assert history.coerce(-5) == 1
    assert history.coerce(1000) == 100
    assert SETTINGS["privacy.screen_mode"].coerce("false") is False

    registry = SettingsRegistry((history,))
    try:
        registry.register(history)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate setting keys must be rejected")


def test_settings_session_rolls_back_live_preview_and_commits():
    manager = _MemoryManager()
    previews = []
    session = SettingsSession(
        manager,
        lambda key, value, preview: previews.append((key, value, preview)),
    )

    session.set("privacy.screen_mode", True)
    assert session.is_dirty
    assert previews[-1] == ("privacy.screen_mode", True, True)
    session.discard()
    assert previews[-1] == ("privacy.screen_mode", False, False)
    assert manager.values["privacy.screen_mode"] is False

    session.set("privacy.screen_mode", True)
    assert session.commit() == ("privacy.screen_mode",)
    assert manager.values["privacy.screen_mode"] is True


def test_settings_export_roundtrips_qbytearray_and_excludes_state_by_default(tmp_path):
    manager = _json_manager(tmp_path, "ExportSource")
    geometry = QByteArray(b"window-bytes")
    manager.set_many(
        {
            "ui_theme": "light",
            "window_geometry": geometry,
            "study_workspace.states": {"study": {"series": "uid"}},
        }
    )

    public_export = tmp_path / "public.json"
    assert manager.export_settings(public_export)
    public_document = json.loads(public_export.read_text(encoding="utf-8"))
    assert public_document["format"] == "medimager-settings"
    assert public_document["settings"]["ui_theme"] == "light"
    assert "window_geometry" not in public_document["settings"]
    assert "study_workspace.states" not in public_document["settings"]

    full_export = tmp_path / "full.json"
    assert manager.export_settings(full_export, include_state=True)
    restored = _json_manager(tmp_path, "ExportTarget")
    assert restored.import_settings(full_export, include_state=True)
    assert bytes(restored.get_setting("window_geometry")) == b"window-bytes"


def test_settings_import_rejects_newer_schema_without_mutating(tmp_path):
    manager = _json_manager(tmp_path, "ImportGuard")
    manager.set_setting("ui_theme", "dark")
    source = tmp_path / "future.json"
    source.write_text(
        json.dumps(
            {
                "format": "medimager-settings",
                "schema_version": 999,
                "settings": {"ui_theme": "light"},
            }
        ),
        encoding="utf-8",
    )
    assert not manager.import_settings(source)
    assert manager.get_setting("ui_theme") == "dark"


def test_smoke_environment_uses_isolated_json_settings(monkeypatch, tmp_path):
    import medimager.utils.settings as settings_module

    previous = settings_module._settings_manager
    settings_module._settings_manager = None
    monkeypatch.setenv("MEDIMAGER_SMOKE_APP_DATA_ROOT", str(tmp_path))
    try:
        manager = settings_module.get_settings_manager()
        manager.set_setting("cache.demo.keep", False)

        assert manager.use_json
        assert manager.config_dir == (tmp_path / "config").resolve()
        assert (manager.config_dir / "medimager_settings.json").is_file()
    finally:
        settings_module.shutdown_settings_manager()
        settings_module._settings_manager = previous


def test_privacy_service_preview_alias_and_persistence(tmp_path):
    manager = _json_manager(tmp_path, "PrivacyService")
    service = get_privacy_service(manager)
    assert not service.enabled
    service.set_preview(True)
    assert service.enabled
    assert service.alias_for("patient", "P-1") == "Patient 01"
    assert service.alias_for("patient", "P-1") == "Patient 01"
    service.clear_preview()
    assert not service.enabled
    service.set_enabled(True)
    assert service.enabled
    assert manager.get_setting("privacy.screen_mode") is True


def test_temporary_cleanup_never_removes_recovery_or_sidecars(tmp_path):
    manager = _json_manager(tmp_path, "Cleanup")
    thumbnail_dir = manager.get_config_directory() / "thumbnail_cache"
    recovery_dir = manager.get_config_directory() / "annotation_drafts"
    thumbnail_dir.mkdir(parents=True)
    recovery_dir.mkdir(parents=True)
    thumbnail = thumbnail_dir / "one.png"
    draft = recovery_dir / "one.json"
    sidecar = tmp_path / "image.medimager.json"
    demo_root = tmp_path / "app_local" / "demo_studies" / "v1"
    demo_file = demo_root / "ct_multiphase" / "series" / "one.dcm"
    demo_file.parent.mkdir(parents=True)
    demo_file.write_bytes(b"dicom")
    thumbnail.write_bytes(b"png")
    draft.write_text("{}", encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")
    manager.set_setting("study_workspace.states", {"study": {}})
    manager.get_performance_manager().add_to_cache("frame", b"display")

    service = StorageCleanupService(manager, demo_cache_root=demo_root)
    usages = {
        usage.category: usage
        for usage in service.inspect((StorageCategory.DEMO_STUDIES,))
    }
    assert usages[StorageCategory.DEMO_STUDIES].item_count == 1
    assert usages[StorageCategory.DEMO_STUDIES].bytes == 5

    results = service.clear_temporary_caches()
    assert tuple(result.category for result in results) == (
        StorageCategory.DISPLAY_MEMORY,
        StorageCategory.THUMBNAILS,
        StorageCategory.DEMO_STUDIES,
    )
    assert not thumbnail.exists()
    assert not demo_root.exists()
    assert draft.exists()
    assert sidecar.exists()
    assert manager.has_setting("study_workspace.states")

    service.set_protected_drafts_provider(lambda: (draft,))
    result = service.clear(StorageCategory.RECOVERY_DRAFTS)
    assert result.skipped_active == 1
    assert draft.exists()


def test_demo_cleanup_does_not_follow_nested_directory_symlinks(tmp_path):
    manager = _json_manager(tmp_path, "DemoCleanupSafety")
    demo_root = tmp_path / "app_local" / "demo_studies" / "v1"
    demo_root.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    protected = external / "must-remain.dcm"
    protected.write_bytes(b"patient-independent-test")
    link = demo_root / "linked-directory"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this Windows host")

    service = StorageCleanupService(manager, demo_cache_root=demo_root)
    result = service.clear(StorageCategory.DEMO_STUDIES)

    assert result.category is StorageCategory.DEMO_STUDIES
    assert protected.read_bytes() == b"patient-independent-test"
    assert not link.exists()
    assert not demo_root.exists()


def test_settings_center_uses_planned_eight_categories_without_losing_controls(
    qapp, tmp_path
):
    translation_manager = get_translation_manager()
    original_language = translation_manager.current_language()
    dialog = None
    try:
        assert translation_manager.set_language("en_US")
        manager = _json_manager(tmp_path, "SettingsInformationArchitectureV26")
        dialog = SettingsDialog(manager)
        qapp.processEvents()

        assert [
            dialog.nav_list.item(index).text()
            for index in range(dialog.nav_list.count())
        ] == [
            "General",
            "Workspace and startup",
            "Display and privacy",
            "Interaction",
            "DICOM and sources",
            "Multi-view and synchronization",
            "Tools and annotations",
            "Performance and storage",
        ]
        assert dialog.stacked_widget.count() == 8

        page_key_sets = [set(record[4]) for record in dialog._page_records]
        expected_page_keys = (
            {"language", "ui_theme"},
            {"workspace.startup_mode", "recent_studies.max_items"},
            {
                "display.smooth_interpolation",
                "overlay.show_patient",
                "privacy.screen_mode",
            },
            {"interaction.left_drag_action", "cine.default_fps"},
            {"dicom.recursive_scan", "dicom.strict_metadata"},
            {"multiview.default_layout", "sync.shared_cursor"},
            {"roi_theme", "measurement_theme", "toolbar.group_order"},
            {"cache_size", "cache.thumbnail.max_items", "cache.demo.keep"},
        )
        for actual, expected in zip(page_key_sets, expected_page_keys, strict=True):
            assert expected <= actual

        display_privacy_page = dialog.stacked_widget.widget(2)
        assert display_privacy_page.isAncestorOf(
            dialog.setting_widgets["display.smooth_interpolation"]
        )
        assert display_privacy_page.isAncestorOf(
            dialog.setting_widgets["privacy.screen_mode"]
        )
        assert set(SIMPLE_SETTING_KEYS) <= set(dialog.setting_widgets)
        assert {
            "language",
            "ui_theme",
            "roi_theme",
            "measurement_theme",
            "cache_size",
            "thread_count",
        } <= set(dialog.setting_widgets)
    finally:
        if dialog is not None:
            dialog.close()
        translation_manager.set_language(original_language)


def test_settings_dialog_search_apply_and_cancel_live_privacy(qapp, tmp_path):
    manager = _json_manager(tmp_path, "SettingsDialogV26")
    dialog = SettingsDialog(manager)
    assert StorageCategory.DEMO_STUDIES in dialog._storage_labels
    dialog.show()
    qapp.processEvents()

    dialog.search_edit.setText("Privacy")
    qapp.processEvents()
    visible_pages = [
        not dialog.nav_list.item(index).isHidden()
        for index in range(dialog.nav_list.count())
    ]
    assert sum(visible_pages) == 1

    privacy = dialog.setting_widgets["privacy.screen_mode"]
    privacy.setChecked(True)
    dialog.button_box.button(QDialogButtonBox.Apply).click()
    qapp.processEvents()
    assert manager.get_setting("privacy.screen_mode") is True
    assert dialog.isVisible()

    privacy.setChecked(False)
    assert not get_privacy_service(manager).enabled
    dialog.reject()
    assert manager.get_setting("privacy.screen_mode") is True
    assert get_privacy_service(manager).enabled


def test_settings_center_persists_toolbar_order_visibility_and_visual_defaults(
    qapp, tmp_path
):
    manager = _json_manager(tmp_path, "SettingsToolbarV26")
    dialog = SettingsDialog(manager)
    dialog.show()
    qapp.processEvents()

    assert dialog.setting_widgets["ui.density"].currentData() == "compact"
    assert dialog.setting_widgets["ui.icon_size"].value() == 24
    assert dialog.setting_widgets["ui.font_scale"].value() == 100
    assert dialog.setting_widgets["overlay.show_pixel_value"].isChecked() is False
    assert dialog.setting_widgets["sync.window_level"].isChecked() is True
    assert dialog.setting_widgets["sync.zoom"].isChecked() is False

    order = ["compare", "browse", "measure", "advanced"]
    visible = ["browse", "compare"]
    dialog.setting_widgets["toolbar.group_order"].setValue(order)
    dialog.setting_widgets["toolbar.visible_groups"].setValue(visible)
    dialog.setting_widgets["toolbar.show_labels"].setChecked(True)
    dialog.setting_widgets["ui.icon_size"].setValue(30)
    dialog.setting_widgets["language"].setCurrentIndex(
        dialog.setting_widgets["language"].findData("zh_CN")
    )
    qapp.processEvents()

    assert "modified" in dialog.change_status_label.text().lower()
    assert dialog.restart_badge.isVisible()
    dialog.button_box.button(QDialogButtonBox.Apply).click()
    qapp.processEvents()

    assert manager.get_setting("toolbar.group_order") == order
    assert manager.get_setting("toolbar.visible_groups") == visible
    assert manager.get_setting("toolbar.show_labels") is True
    assert manager.get_setting("ui.icon_size") == 30
    assert not dialog.restart_badge.isVisible()
    dialog.close()
