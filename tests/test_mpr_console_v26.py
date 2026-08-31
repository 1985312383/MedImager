from __future__ import annotations

import numpy as np

from medimager.core.volume_geometry import MprPlane
from medimager.ui.mpr_workspace import MprLayoutMode, MprWorkspace
from tests.test_mpr_workspace import _MprModel


def _ready_workspace(qtbot) -> MprWorkspace:
    workspace = MprWorkspace()
    qtbot.addWidget(workspace)
    workspace.show()
    workspace.start_build(_MprModel(), "series", 128 * 1024 * 1024)
    qtbot.waitUntil(lambda: workspace.is_ready, timeout=5000)
    return workspace


def test_mpr_console_switches_three_one_plus_two_and_single_layouts(qtbot):
    workspace = _ready_workspace(qtbot)

    assert workspace.layout_mode is MprLayoutMode.THREE_COLUMNS
    assert all(panel.isVisible() for panel in workspace._plane_panels.values())

    workspace.set_layout_mode(MprLayoutMode.ONE_PLUS_TWO)
    assert workspace.layout_mode is MprLayoutMode.ONE_PLUS_TWO
    assert all(panel.isVisible() for panel in workspace._plane_panels.values())

    workspace.toggle_maximize(MprPlane.CORONAL)
    assert workspace.layout_mode is MprLayoutMode.SINGLE
    assert workspace._plane_panels[MprPlane.CORONAL].isVisible()
    assert not workspace._plane_panels[MprPlane.AXIAL].isVisible()

    workspace.toggle_maximize(MprPlane.CORONAL)
    assert workspace.layout_mode is MprLayoutMode.ONE_PLUS_TWO
    assert all(panel.isVisible() for panel in workspace._plane_panels.values())


def test_mpr_console_slice_sliders_share_one_patient_space_cursor(qtbot):
    workspace = _ready_workspace(qtbot)
    slider = workspace._slice_sliders[MprPlane.AXIAL]
    assert slider.maximum() >= 1
    before = workspace._state.cursor_lps.copy()

    slider.setValue(min(slider.maximum(), slider.value() + 1))
    qtbot.waitUntil(lambda: not np.allclose(workspace._state.cursor_lps, before), timeout=1000)

    assert workspace._state.cursor_lps[2] > before[2]
    assert workspace._slice_labels[MprPlane.AXIAL].text()
    assert all(candidate.value() >= candidate.minimum() for candidate in workspace._slice_sliders.values())


def test_mpr_console_quick_controls_apply_per_view_and_sync_lines(qtbot):
    workspace = _ready_workspace(qtbot)
    coronal = workspace.viewports[MprPlane.CORONAL]

    workspace._apply_wl_preset(MprPlane.CORONAL, 2)
    assert coronal.presentation_state.window_width == 1500.0
    assert coronal.presentation_state.window_level == -600.0

    workspace.set_intersection_lines_visible(False)
    assert not workspace._intersection_lines_visible
    assert all(not viewport._intersection_lines_visible for viewport in workspace.viewports.values())
    assert all(not button.isChecked() for button in workspace._line_buttons.values())

