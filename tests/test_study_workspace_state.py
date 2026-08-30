import json

import numpy as np

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import SeriesInfo
from medimager.ui.main_window import MainWindow


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


def test_study_workspace_roundtrip_waits_for_bound_series_and_omits_patient_name(
    qapp, monkeypatch
):
    window = MainWindow()
    settings = {}
    monkeypatch.setattr(
        window.settings_manager,
        "get_setting",
        lambda key, default=None: settings.get(key, default),
    )
    monkeypatch.setattr(
        window.settings_manager,
        "set_setting",
        lambda key, value: settings.__setitem__(key, value),
    )
    _add_loaded(window, "one", "1.2.840.series.1")
    _add_loaded(window, "two", "1.2.840.series.2")
    window._set_layout((1, 2))
    assert window.series_manager.bind_series_to_view("view_0_0", "one")
    assert window.series_manager.bind_series_to_view("view_0_1", "two")
    assert window.series_manager.set_active_view("view_0_0")
    first_viewer = window.multi_viewer_grid.get_view_frame("view_0_0").image_viewer
    first_viewer.presentation_state.slice_index = 2
    first_viewer.presentation_state.window_width = 900.0
    first_viewer.presentation_state.window_level = 120.0

    window._save_study_workspace_state()

    serialized = json.dumps(settings["study_workspace.states"])
    assert "Sensitive Example Name" not in serialized
    assert "1.2.840.study" not in settings["study_workspace.states"]

    window._restored_study_keys.clear()
    window.series_manager.get_series_info("two").is_loaded = False
    assert not window._restore_study_workspace_for_series("one")
    window.series_manager.get_series_info("two").is_loaded = True
    window._set_layout((1, 1))

    assert window._restore_study_workspace_for_series("one")
    assert window.series_manager.get_current_layout() == (1, 2)
    assert window.series_manager.get_view_binding("view_0_0").series_id == "one"
    assert window.series_manager.get_view_binding("view_0_1").series_id == "two"
    restored = window.multi_viewer_grid.get_view_frame("view_0_0").image_viewer
    assert restored.presentation_state.slice_index == 2
    assert restored.presentation_state.window_width == 900.0
    assert restored.presentation_state.window_level == 120.0
    window._closing = True
    window.deleteLater()
    qapp.processEvents()
