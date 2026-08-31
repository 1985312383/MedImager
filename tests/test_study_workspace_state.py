import json

import numpy as np
from PySide6.QtCore import QPointF

from medimager.core.image_data_model import ImageDataModel
from medimager.core.layout_presets import LayoutSpec
from medimager.core.multi_series_manager import SeriesInfo
from medimager.core.study_workspace import (
    WORKSPACE_DOCUMENT_KEY,
    MprWorkspaceSnapshot,
    StudyWorkspaceState,
    StudyWorkspaceStore,
    study_key_for_uid,
)
from medimager.core.sync_manager import SyncGroup, SyncMode
from medimager.core.view_presentation_state import InterpolationMode
from medimager.ui.main_window import MainWindow


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value

    def remove_setting(self, key):
        self.values.pop(key, None)

    def has_setting(self, key):
        return key in self.values

    def save_settings(self):
        pass


def _add_loaded(window: MainWindow, series_id: str, series_uid: str) -> None:
    info = SeriesInfo(
        series_id=series_id,
        patient_name="Sensitive Example Name",
        patient_id="P-1",
        study_instance_uid="1.2.840.study",
        series_instance_uid=series_uid,
        modality="CT",
    )
    window.series_manager.add_series(info)
    model = ImageDataModel()
    assert model.load_single_image(np.zeros((4, 8, 8), dtype=np.float32))
    assert window.series_manager.load_series_data(series_id, model)


def test_schema_v2_workspace_roundtrip_waits_for_all_series_and_is_uid_free(qapp):
    window = MainWindow()
    memory = MemorySettings({"workspace.history_limit": 20})
    window._workspace_store = StudyWorkspaceStore(memory)
    _add_loaded(window, "one", "1.2.840.series.1")
    _add_loaded(window, "two", "1.2.840.series.2")
    special = LayoutSpec(
        kind="special",
        special_type="horizontal_split",
        ratios=(0.61, 0.42),
    )
    window._set_layout(special.to_legacy())
    assert window.series_manager.bind_series_to_view("view_0_0", "one")
    assert window.series_manager.bind_series_to_view("view_0_1", "two")
    assert window.series_manager.set_active_view("view_0_0")
    viewer = window.multi_viewer_grid.get_view_frame("view_0_0").image_viewer
    state = viewer.presentation_state
    state.slice_index = 2
    state.window_width = 900.0
    state.window_level = 120.0
    state.zoom = 2.25
    state.pan_center = QPointF(7.5, -3.25)
    state.rotation = 270
    state.flip_horizontal = True
    state.flip_vertical = True
    state.inverted = True
    state.interpolation = InterpolationMode.PIXEL_EXACT
    state.fit_mode = False
    window.sync_manager.set_sync_mode(
        SyncMode.WINDOW_LEVEL | SyncMode.SLICE | SyncMode.CROSS_REFERENCE
    )
    window.sync_manager.set_sync_group(SyncGroup.SAME_MODALITY)

    window._save_study_workspace_state()

    document = memory.values[WORKSPACE_DOCUMENT_KEY]
    serialized = json.dumps(document)
    assert document["schema_version"] == 2
    assert "Sensitive Example Name" not in serialized
    assert "1.2.840.study" not in serialized
    assert "1.2.840.series.1" not in serialized
    saved = document["states"][study_key_for_uid("1.2.840.study")]
    assert saved["layout"]["special_type"] == "horizontal_split"
    assert saved["splitter_ratios"]["workspace"]

    window._restored_study_keys.clear()
    window.series_manager.get_series_info("two").is_loaded = False
    assert not window._restore_study_workspace_for_series("one")
    window.series_manager.get_series_info("two").is_loaded = True
    window._set_layout((1, 1))
    window.sync_manager.set_sync_mode(SyncMode.NONE)
    window.sync_manager.set_sync_group(SyncGroup.ALL_VIEWS)

    assert window._restore_study_workspace_for_series("one")
    restored_spec = window.multi_viewer_grid.current_layout_spec()
    assert restored_spec.kind == "special"
    assert restored_spec.special_type == "horizontal_split"
    assert window.series_manager.get_view_binding("view_0_0").series_id == "one"
    assert window.series_manager.get_view_binding("view_0_1").series_id == "two"
    assert window.series_manager.get_active_view_id() == "view_0_0"
    assert window.sync_manager.get_sync_mode() == (
        SyncMode.WINDOW_LEVEL | SyncMode.SLICE | SyncMode.CROSS_REFERENCE
    )
    assert window.sync_manager.get_sync_group() is SyncGroup.SAME_MODALITY
    restored = window.multi_viewer_grid.get_view_frame("view_0_0").image_viewer
    presentation = restored.presentation_state
    assert presentation.slice_index == 2
    assert presentation.window_width == 900.0
    assert presentation.window_level == 120.0
    assert presentation.zoom == 2.25
    assert presentation.pan_center == QPointF(7.5, -3.25)
    assert presentation.rotation == 270
    assert presentation.flip_horizontal and presentation.flip_vertical
    assert presentation.inverted
    assert presentation.interpolation is InterpolationMode.PIXEL_EXACT
    assert not presentation.fit_mode
    window._closing = True
    window.deleteLater()
    qapp.processEvents()


def test_mainwindow_never_overwrites_a_newer_workspace_document(qapp):
    raw = {"schema_version": 99, "states": {"future": {"opaque": True}}}
    memory = MemorySettings({WORKSPACE_DOCUMENT_KEY: raw})
    window = MainWindow()
    window._workspace_store = StudyWorkspaceStore(memory)
    _add_loaded(window, "one", "1.2.840.series.1")
    window._save_study_workspace_state()

    assert memory.values[WORKSPACE_DOCUMENT_KEY] is raw
    assert not window._restore_study_workspace_for_series("one")
    assert memory.values[WORKSPACE_DOCUMENT_KEY] is raw
    window._closing = True
    window.deleteLater()
    qapp.processEvents()


def test_mpr_restore_is_pending_by_default_and_auto_entry_is_one_shot(
    qapp, monkeypatch
):
    memory = MemorySettings(
        {
            "workspace.history_limit": 20,
            "workspace.restore_mpr": False,
        }
    )
    mpr = MprWorkspaceSnapshot.capture(
        series_uid="1.2.840.series.1",
        cursor_lps=(-40.0, 5.0, 120.0),
        plane_indices={"axial": 2, "coronal": 3, "sagittal": 4},
        views={},
        layout_mode="one_plus_two",
        active_plane="sagittal",
    )
    stored = StudyWorkspaceState.capture(
        study_instance_uid="1.2.840.study",
        layout=(1, 1),
        bindings={"view_0_0": "1.2.840.series.1"},
        mpr=mpr,
        updated_at_ms=1,
    )
    store = StudyWorkspaceStore(memory)
    assert store.save_state(stored).success

    window = MainWindow()
    window._workspace_store = store
    monkeypatch.setattr(
        window.settings_manager,
        "get_setting",
        lambda key, default=None: memory.get_setting(key, default),
    )
    _add_loaded(window, "one", "1.2.840.series.1")
    attempts = []
    monkeypatch.setattr(
        window,
        "_start_mpr_workspace_for_series",
        lambda series_id, **kwargs: attempts.append((series_id, kwargs)) or True,
    )

    assert window._restore_study_workspace_for_series("one")
    assert not window._mpr_active
    assert window._pending_mpr_workspace_snapshot == ("one", mpr)
    qapp.processEvents()
    assert attempts == []

    window._restored_study_keys.clear()
    window._auto_mpr_restore_attempted_studies.clear()
    memory.values["workspace.restore_mpr"] = True
    assert window._restore_study_workspace_for_series("one")
    qapp.processEvents()
    assert attempts == [("one", {"warn_if_incompatible": False})]
    qapp.processEvents()
    assert len(attempts) == 1
    window._closing = True
    window.deleteLater()
    qapp.processEvents()
