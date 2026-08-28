from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QToolButton

from medimager.ui.main_toolbar import create_main_toolbar
from tests.test_main_toolbar import _ToolbarWindow


def test_toolbar_exposes_interaction_view_voi_sync_and_fps_contract(qapp):
    window = _ToolbarWindow()
    window._cine_fps = 18
    toolbar = create_main_toolbar(window)
    interaction_spy = QSignalSpy(toolbar.interaction_mode_requested)
    command_spy = QSignalSpy(toolbar.viewer_command_requested)
    voi_spy = QSignalSpy(toolbar.voi_option_requested)

    window.tool_actions["pan"].trigger()
    fit_action = next(
        action for action in toolbar.actions()
        if action.property("shortcutHint") == "F"
    )
    fit_action.trigger()

    window_level_button = next(
        button for button in toolbar.findChildren(QToolButton)
        if hasattr(button, "_dicom_voi_actions")
    )
    option = {"kind": "window", "index": 1, "label": "Soft tissue"}
    toolbar.set_dicom_voi_options([option], active_index=0)
    window_level_button._dicom_voi_actions[0].trigger()

    assert interaction_spy.at(0)[0] == "pan"
    assert command_spy.at(0)[0] == "fit"
    assert voi_spy.at(0)[0] == option
    assert window._cine_fps_spin.value() == 18
    toolbar.set_cine_fps(24)
    assert window._cine_fps_spin.value() == 24

    toolbar.sync_button.set_sync_states("none", False, False, False)
    assert toolbar.sync_button.property("syncState") == "off"
    toolbar.sync_button.set_sync_states("both", True, True, True)
    assert toolbar.sync_button.property("syncState") == "all"
    window.close()
