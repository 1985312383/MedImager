import json

from PySide6.QtCore import QPointF

from medimager.core.layout_presets import LayoutSpec
from medimager.core.study_workspace import (
    LEGACY_WORKSPACE_KEY,
    WORKSPACE_DOCUMENT_KEY,
    MprWorkspaceSnapshot,
    PresentationSnapshot,
    StudyWorkspaceState,
    StudyWorkspaceStore,
    WorkspaceDocument,
    WorkspaceSyncState,
    build_series_key_index,
    migrate_v25_bare_states,
    series_key_for_uid,
    study_key_for_uid,
)
from medimager.core.view_presentation_state import (
    InterpolationMode,
    ViewPresentationState,
)


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.corrupt_document_read = False

    def get_setting(self, key, default=None):
        if key == WORKSPACE_DOCUMENT_KEY and self.corrupt_document_read:
            self.corrupt_document_read = False
            return {"schema_version": 2, "states": []}
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value

    def remove_setting(self, key):
        self.values.pop(key, None)

    def has_setting(self, key):
        return key in self.values

    def save_settings(self):
        pass


def _full_view_state() -> ViewPresentationState:
    return ViewPresentationState(
        series_id="runtime-id",
        slice_index=17,
        window_width=1234.5,
        window_level=-120.25,
        use_dicom_voi_lut=True,
        voi_lut_index=2,
        zoom=2.75,
        pan_center=QPointF(13.5, -8.25),
        rotation=270,
        flip_horizontal=True,
        flip_vertical=True,
        inverted=True,
        interpolation=InterpolationMode.PIXEL_EXACT,
        magnifier_enabled=True,
        fit_mode=False,
        use_physical_pixel_aspect=False,
    )


def _state(study_uid: str, series_uid: str, updated: int) -> StudyWorkspaceState:
    return StudyWorkspaceState.capture(
        study_instance_uid=study_uid,
        layout=LayoutSpec(
            kind="special",
            special_type="horizontal_split",
            ratios=(0.62, 0.48),
        ),
        splitter_ratios={"workspace": (3, 7), "sidebar": (1, 4)},
        bindings={"view_0_0": series_uid},
        presentations={"view_0_0": _full_view_state()},
        active_viewport="view_0_0",
        sync=WorkspaceSyncState.from_runtime(79, "same_study", "both"),
        updated_at_ms=updated,
    )


def test_capture_roundtrip_is_json_safe_complete_and_uid_free():
    state = _state("1.2.840.study.secret", "1.2.840.series.secret", 123456)
    document = WorkspaceDocument(states={state.study_key: state}).to_document()
    encoded = json.dumps(document, allow_nan=False)

    assert "1.2.840.study.secret" not in encoded
    assert "1.2.840.series.secret" not in encoded
    assert state.study_key == study_key_for_uid("1.2.840.study.secret")
    assert state.bindings["view_0_0"] == series_key_for_uid(
        "1.2.840.series.secret"
    )
    assert state.splitter_ratios["workspace"] == (0.3, 0.7)
    # The manual half of "both" is intentionally not persisted.
    assert state.sync.position_mode == "auto_lps"
    assert "registration" not in encoded.casefold()

    parsed, skipped = WorkspaceDocument.parse(document)
    assert skipped == 0
    restored = parsed.states[state.study_key]
    snapshot = restored.presentations["view_0_0"]
    view = snapshot.to_view_state(series_id="runtime", slice_count=100)
    assert view.series_id == "runtime"
    assert view.slice_index == 17
    assert view.window_width == 1234.5
    assert view.window_level == -120.25
    assert view.use_dicom_voi_lut is True
    assert view.voi_lut_index == 2
    assert view.pan_center == QPointF(13.5, -8.25)
    assert view.rotation == 270
    assert view.flip_horizontal and view.flip_vertical and view.inverted
    assert view.interpolation is InterpolationMode.PIXEL_EXACT
    assert view.magnifier_enabled and not view.fit_mode
    assert not view.use_physical_pixel_aspect


def test_series_index_resolves_opaque_bindings():
    state = _state("study", "series", 1)
    index = build_series_key_index({"runtime-series": "series"})
    assert state.resolve_bindings(index) == {"view_0_0": "runtime-series"}
    assert state.required_series_keys == frozenset(index)


def test_optional_mpr_snapshot_roundtrips_without_raw_uid():
    series_uid = "1.2.840.mpr.secret"
    axial = _full_view_state()
    axial.window_width = 1500.0
    axial.window_level = 250.0
    mpr = MprWorkspaceSnapshot.capture(
        series_uid=series_uid,
        cursor_lps=(-81.25, 14.5, 203.75),
        plane_indices={"axial": 17, "coronal": 23, "sagittal": 31},
        views={
            "axial": axial,
            "coronal": _full_view_state(),
            "sagittal": _full_view_state(),
        },
        layout_mode="one_plus_two",
        active_plane="coronal",
        intersection_lines_visible=False,
    )
    state = StudyWorkspaceState.capture(
        study_instance_uid="1.2.840.study.secret",
        layout=(1, 1),
        bindings={"view_0_0": series_uid},
        mpr=mpr,
        updated_at_ms=1,
    )

    document = WorkspaceDocument(states={state.study_key: state}).to_document()
    encoded = json.dumps(document)
    restored, skipped = WorkspaceDocument.parse(document)
    restored_mpr = restored.states[state.study_key].mpr

    assert skipped == 0
    assert series_uid not in encoded
    assert restored_mpr is not None
    assert restored_mpr.cursor_lps == (-81.25, 14.5, 203.75)
    assert restored_mpr.layout_mode == "one_plus_two"
    assert restored_mpr.active_plane == "coronal"
    assert not restored_mpr.intersection_lines_visible
    assert restored_mpr.views["axial"].window_width == 1500.0
    index = build_series_key_index({"runtime-mpr": series_uid})
    restored_state = restored.states[state.study_key]
    assert restored_state.resolve_mpr_series(index) == "runtime-mpr"
    assert restored_mpr.series_key in restored_state.required_series_keys


def test_store_enforces_lru_history_and_verifies_writes():
    settings = MemorySettings()
    store = StudyWorkspaceStore(settings, maximum=2)

    assert store.save_state(_state("study-old", "series-old", 10)).success
    assert store.save_state(_state("study-new", "series-new", 30)).success
    result = store.save_state(_state("study-middle", "series-middle", 20))

    assert result.success and result.verified
    assert result.pruned_entries == 1
    assert list(result.document.states) == [
        study_key_for_uid("study-new"),
        study_key_for_uid("study-middle"),
    ]
    parsed, skipped = WorkspaceDocument.parse(settings.values[WORKSPACE_DOCUMENT_KEY])
    assert skipped == 0
    assert set(parsed.states) == set(result.document.states)


def test_v25_migration_is_idempotent_hashes_series_and_removes_old_after_verify():
    study_key = study_key_for_uid("1.2.3.study")
    legacy = {
        study_key: {
            "updated": 100.125,
            "layout": [1, 2],
            "bindings": {"view_0_0": "1.2.3.series"},
            "presentations": {
                "view_0_0": {
                    "series_uid": "1.2.3.series",
                    "slice": 9,
                    "ww": 800,
                    "wl": 70,
                    "zoom": 1.5,
                    "pan": [3, 4],
                    "invert": True,
                    "interpolation": "nearest",
                    "fit": False,
                }
            },
            "active_view": "view_0_0",
            "sync_mode": 3,
            "position_mode": "manual",
            "manual_registration_offsets": {"view_0_0": [99, 42]},
        }
    }
    first, first_skipped = migrate_v25_bare_states(legacy)
    second, second_skipped = migrate_v25_bare_states(legacy)
    assert first.to_document() == second.to_document()
    assert first_skipped == second_skipped == 0

    settings = MemorySettings({LEGACY_WORKSPACE_KEY: legacy})
    loaded = StudyWorkspaceStore(settings).load_document()
    assert loaded.migrated and loaded.error == ""
    assert LEGACY_WORKSPACE_KEY not in settings.values
    migrated = loaded.document.states[study_key]
    assert migrated.bindings["view_0_0"] == series_key_for_uid("1.2.3.series")
    assert migrated.sync.position_mode == "none"
    encoded = json.dumps(settings.values[WORKSPACE_DOCUMENT_KEY])
    assert "1.2.3.series" not in encoded
    assert "manual_registration_offsets" not in encoded


def test_failed_migration_verification_preserves_legacy_and_rolls_back_new_key():
    study_key = study_key_for_uid("study")
    settings = MemorySettings(
        {
            LEGACY_WORKSPACE_KEY: {
                study_key: {
                    "updated": 1,
                    "layout": [1, 1],
                    "bindings": {},
                    "presentations": {},
                    "active_view": "",
                    "sync_mode": 0,
                }
            }
        }
    )
    settings.corrupt_document_read = True
    loaded = StudyWorkspaceStore(settings).load_document()

    assert loaded.error == "verification_failed"
    assert LEGACY_WORKSPACE_KEY in settings.values
    assert WORKSPACE_DOCUMENT_KEY not in settings.values


def test_newer_schema_is_read_only_and_never_overwritten():
    raw = {"schema_version": 99, "states": {"future": {"opaque": True}}}
    settings = MemorySettings({WORKSPACE_DOCUMENT_KEY: raw})
    store = StudyWorkspaceStore(settings)

    loaded = store.load_document()
    written = store.save_state(_state("study", "series", 1))

    assert loaded.read_only and loaded.newer_schema_version == 99
    assert not written.success and written.reason == "newer_schema"
    assert settings.values[WORKSPACE_DOCUMENT_KEY] is raw


def test_corrupt_study_entry_is_skipped_without_losing_valid_entries():
    valid = _state("valid-study", "series", 1)
    raw = WorkspaceDocument(states={valid.study_key: valid}).to_document()
    raw["states"]["not-a-valid-hash"] = {"layout": "broken"}
    settings = MemorySettings({WORKSPACE_DOCUMENT_KEY: raw})

    loaded = StudyWorkspaceStore(settings).load_document()

    assert loaded.skipped_entries == 1
    assert set(loaded.document.states) == {valid.study_key}
    assert settings.values[WORKSPACE_DOCUMENT_KEY] == raw


def test_presentation_parser_rejects_nonfinite_values():
    series_key = series_key_for_uid("series")
    snapshot = PresentationSnapshot.from_view_state(
        _full_view_state(), series_key=series_key
    ).to_document()
    snapshot["zoom"] = float("nan")

    try:
        PresentationSnapshot.from_document(snapshot)
    except ValueError as error:
        assert "finite" in str(error)
    else:
        raise AssertionError("non-finite workspace values must be rejected")
