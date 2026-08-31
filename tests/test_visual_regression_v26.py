from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from medimager.qa.visual_release import main as visual_release_main
from medimager.qa.visual_regression import (
    BaselineUpdateNotAllowed,
    GuiHeartbeatProbe,
    VisualBaselineStore,
    VisualRegressionHarness,
    VisualRunMode,
    VisualScenario,
    VisualDiffThresholds,
    assert_visual_match,
    capture_widget_surface,
    check_widget_visibility_at_scale,
    compare_images,
    default_v26_manifest_metadata,
    default_v26_scenarios,
    find_visibility_violations,
    run_visibility_matrix,
    save_diff_image,
)
from medimager.qa.visual_surfaces import (
    RealMedImagerSurfaceProvider,
    VisualWorkbenchShell,
)
from medimager.ui.dialogs.settings_dialog import SettingsDialog
from medimager.ui.main_toolbar import ViewerToolbar
from medimager.ui.mpr_workspace import MprWorkspace
from medimager.ui.multi_viewer_grid import MultiViewerGrid
from medimager.ui.panels.series_panel import SeriesPanel
from medimager.ui.start_center import StartCenter


def _wcag_contrast(foreground: QColor, background: QColor) -> float:
    def luminance(color: QColor) -> float:
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def test_v26_visual_thresholds_match_release_contract(tmp_path):
    reference = np.zeros((20, 20, 4), dtype=np.uint8)
    reference[..., 3] = 255
    actual = reference.copy()
    actual[0, 0, :3] = 13

    thresholds = VisualDiffThresholds()
    metrics = compare_images(actual, reference, thresholds)

    assert thresholds.mae == 2.0
    assert thresholds.outlier_delta == 12
    assert thresholds.outlier_ratio == 0.005
    assert metrics.outlier_ratio == 1 / 400
    assert metrics.passes(thresholds)
    assert assert_visual_match(actual, reference) == metrics
    assert save_diff_image(actual, reference, tmp_path / "diff.png").is_file()


def test_v26_visual_scenario_matrix_is_complete():
    scenarios = default_v26_scenarios()
    assert len(scenarios) == 12
    assert all(
        (item.width, item.height, item.dpr) == (1280, 800, 1.0) for item in scenarios
    )
    assert {item.language for item in scenarios} == {"zh_CN", "en_US"}
    assert {item.theme for item in scenarios} == {"dark", "light"}
    assert {item.surface for item in scenarios} >= {
        "start_center",
        "ct_2x2",
        "mr_2x2",
        "mpr",
        "settings",
    }


def test_checked_native_windows_release_baseline_is_complete():
    root = (
        Path(__file__).resolve().parents[1]
        / "release"
        / "visual-baselines"
        / "v2.6"
    )
    store = VisualBaselineStore(root)
    manifest = store.load_manifest()
    expected_keys = {scenario.key for scenario in default_v26_scenarios()}

    assert set(manifest["scenarios"]) == expected_keys
    assert manifest["metadata"] == default_v26_manifest_metadata()
    for entry in manifest["scenarios"].values():
        path = store.resolve_entry_path(entry)
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size == (1280, 800)
            assert image.mode == "RGBA"


def test_visibility_probe_detects_controls_outside_window(qtbot):
    root = QWidget()
    root.resize(200, 100)
    qtbot.addWidget(root)
    inside = QLabel("inside", root)
    inside.setObjectName("inside")
    inside.setGeometry(10, 10, 50, 20)
    outside = QLabel("outside", root)
    outside.setObjectName("outside")
    outside.setGeometry(250, 10, 50, 20)
    root.show()

    assert find_visibility_violations(root) == ("outside",)


def test_gui_heartbeat_probe_records_event_loop_ticks(qtbot):
    probe = GuiHeartbeatProbe(interval_ms=5)
    probe.start()
    qtbot.waitUntil(lambda: probe.sample_count >= 3, timeout=500)
    probe.stop()

    assert probe.max_gap_ms > 0
    assert probe.max_gap_ms < 100


def test_gui_heartbeat_probe_excludes_delay_before_first_timer_tick(qapp, qtbot):
    probe = GuiHeartbeatProbe(interval_ms=5)
    probe.start()

    # Simulate cold-start/event-queue delay before Qt can deliver the first
    # timeout.  It is outside the interval between two actual heartbeat ticks.
    time.sleep(0.12)
    qapp.processEvents()
    assert probe.is_armed
    assert probe.sample_count == 0

    qtbot.waitUntil(lambda: probe.sample_count >= 2, timeout=500)
    probe.stop()

    assert probe.max_gap_ms < 100


def test_gui_heartbeat_probe_keeps_real_post_arm_stalls(qapp, qtbot):
    probe = GuiHeartbeatProbe(interval_ms=5)
    probe.start()
    qtbot.waitUntil(lambda: probe.is_armed, timeout=500)

    time.sleep(0.12)
    qapp.processEvents()
    probe.stop()

    assert probe.sample_count >= 1
    assert probe.max_gap_ms >= 100


def test_widget_capture_uses_scenario_size_and_restores_widget(qtbot):
    widget = QLabel("MedImager")
    widget.resize(91, 47)
    qtbot.addWidget(widget)
    scenario = VisualScenario("capture", "dark", "en_US", "label", 64, 32, 1.0)

    image = capture_widget_surface(widget, scenario)

    assert (image.width(), image.height(), image.devicePixelRatio()) == (64, 32, 1.0)
    assert widget.size().toTuple() == (91, 47)
    assert not widget.isVisible()


def test_widget_capture_neutralizes_host_pointer_hover(qtbot):
    root = QWidget()
    root.resize(160, 60)
    button = QPushButton("Open study", root)
    button.setGeometry(20, 10, 120, 40)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setStyleSheet(
        "QPushButton { background: #20242a; } "
        "QPushButton:hover { background: #d05020; }"
    )
    qtbot.addWidget(root)
    scenario = VisualScenario("hover", "dark", "en_US", "button", 160, 60)

    neutral = capture_widget_surface(root, scenario)
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    inherited_hover = capture_widget_surface(root, scenario)

    neutral_pixels = np.asarray(neutral.constBits()).reshape(60, 160, 4).copy()
    hover_pixels = np.asarray(inherited_hover.constBits()).reshape(60, 160, 4).copy()
    assert np.array_equal(neutral_pixels, hover_pixels)
    assert not root.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )


def test_baseline_workflow_requires_opt_in_and_writes_comparison_artifacts(tmp_path):
    scenario = VisualScenario("small", "dark", "en_US", "test", 20, 10, 1.0)
    baseline_root = tmp_path / "baselines"
    artifact_root = tmp_path / "artifacts"
    harness = VisualRegressionHarness(
        baseline_root,
        artifact_root,
        enforce_release_contract=False,
    )
    capture = np.zeros((10, 20, 4), dtype=np.uint8)
    capture[..., 3] = 255

    with pytest.raises(BaselineUpdateNotAllowed):
        harness.run(
            {scenario.key: capture},
            scenarios=(scenario,),
            mode=VisualRunMode.UPDATE,
        )

    update = harness.run(
        {scenario.key: capture},
        scenarios=(scenario,),
        mode=VisualRunMode.UPDATE,
        allow_baseline_update=True,
        manifest_metadata={"fixture": "synthetic"},
    )
    manifest = json.loads(update.baseline_manifest_path.read_text(encoding="utf-8"))
    entry = manifest["scenarios"][scenario.key]

    assert update.passed
    assert manifest["metadata"]["fixture"] == "synthetic"
    assert entry["file"].startswith("images/small.")
    assert len(entry["sha256_rgba"]) == 64
    assert not tuple(baseline_root.rglob("*.tmp"))

    baseline_path = baseline_root / entry["file"]
    baseline_path.write_bytes(b"damaged cache")
    harness.run(
        {scenario.key: capture},
        scenarios=(scenario,),
        mode="update",
        allow_baseline_update=True,
    )
    repaired_manifest = json.loads(
        harness.baselines.manifest_path.read_text(encoding="utf-8")
    )
    assert repaired_manifest["metadata"]["fixture"] == "synthetic"

    comparison = harness.run({scenario.key: capture}, scenarios=(scenario,))
    result = comparison.results[0]
    report = json.loads(comparison.report_path.read_text(encoding="utf-8"))

    assert comparison.passed
    assert result.status == "passed"
    assert result.actual_path and result.actual_path.is_file()
    assert result.diff_path and result.diff_path.is_file()
    assert report["thresholds"] == {
        "mae": 2.0,
        "outlier_delta": 12,
        "outlier_ratio": 0.005,
    }
    assert report["results"][0]["metrics"]["same_size"] is True

    regression = capture.copy()
    regression[:, :2, :3] = 255
    failed = harness.run({scenario.key: regression}, scenarios=(scenario,))

    assert not failed.passed
    assert failed.results[0].status == "failed"
    assert failed.results[0].metrics.outlier_ratio == 0.1
    assert failed.results[0].diff_path.is_file()


def test_failed_batch_capture_cannot_partially_update_manifest(tmp_path):
    first = VisualScenario("first", "dark", "en_US", "test", 8, 8)
    second = VisualScenario("second", "dark", "en_US", "test", 8, 8)
    image = np.zeros((8, 8, 4), dtype=np.uint8)
    harness = VisualRegressionHarness(
        tmp_path / "baselines",
        tmp_path / "artifacts",
        enforce_release_contract=False,
    )
    harness.run(
        {first.key: image},
        scenarios=(first,),
        mode="update",
        allow_baseline_update=True,
    )
    before = harness.baselines.manifest_path.read_bytes()

    def provider(scenario):
        if scenario.key == second.key:
            raise RuntimeError("capture setup failed")
        return image

    with pytest.raises(RuntimeError, match="aborted before mutation"):
        harness.run(
            provider,
            scenarios=(first, second),
            mode="update",
            allow_baseline_update=True,
        )

    assert harness.baselines.manifest_path.read_bytes() == before


def test_release_harness_rejects_noncanonical_pixel_baseline(tmp_path):
    scenario = VisualScenario("small", "dark", "en_US", "test", 20, 10)
    harness = VisualRegressionHarness(tmp_path / "baseline", tmp_path / "actual")

    with pytest.raises(ValueError, match="1280x800 at DPR 1"):
        harness.run({scenario.key: np.zeros((10, 20, 4))}, scenarios=(scenario,))


def test_high_dpi_visibility_checks_are_geometry_only_and_reported(qtbot, tmp_path):
    root = QWidget()
    root.resize(1280, 800)
    qtbot.addWidget(root)
    required = QLabel("required", root)
    required.setObjectName("required")
    required.setGeometry(10, 10, 100, 24)
    clipped = QLabel("clipped", root)
    clipped.setObjectName("clipped")
    clipped.setGeometry(830, 510, 100, 30)
    scenario = VisualScenario("dpi", "dark", "en_US", "test")

    result = check_widget_visibility_at_scale(
        root,
        scenario,
        1.5,
        widgets=(required, clipped),
    )

    assert (result.logical_width, result.logical_height) == (853, 533)
    assert result.violations == ("clipped:clipped",)
    report = run_visibility_matrix(
        {scenario.key: root},
        scenarios=(scenario,),
        required_widgets=lambda _scenario, _root: (required,),
        artifact_root=tmp_path,
    )
    document = json.loads(report.report_path.read_text(encoding="utf-8"))

    assert report.passed
    assert [
        (item.scale_factor, item.logical_width, item.logical_height)
        for item in report.results
    ] == [
        (1.25, 1024, 640),
        (1.5, 853, 533),
    ]
    assert document["mode"] == "visibility_only"
    assert document["passed"] is True


def test_real_provider_builds_every_release_scenario_from_medimager_widgets(qtbot):
    expected_types = {
        "start_center": StartCenter,
        "ct_2x2": MultiViewerGrid,
        "reference_lines": MultiViewerGrid,
        "mr_2x2": MultiViewerGrid,
        "mpr": MprWorkspace,
        "geometry_rejection": MprWorkspace,
        "settings": SettingsDialog,
    }

    with RealMedImagerSurfaceProvider() as provider:
        for scenario in default_v26_scenarios():
            surface = provider(scenario)
            assert type(surface) is VisualWorkbenchShell
            assert type(surface.toolbar) is ViewerToolbar
            assert type(surface.navigator) is SeriesPanel
            assert surface.toolbar.active_tool_chip.maximumWidth() == 196
            primary = surface.primary_surface
            assert type(primary) is expected_types[scenario.surface]
            assert surface.property("visualScenarioKey") == scenario.key
            assert surface.property("visualScenarioSurface") == scenario.surface
            assert primary.property("visualScenarioKey") == scenario.key
            assert primary.property("visualScenarioSurface") == scenario.surface
            if isinstance(primary, MultiViewerGrid):
                assert primary._series_manager.get_series_count() == 4
                assert len(primary._visual_models) == 4
                assert all(
                    frame.has_bound_model()
                    for frame in primary.get_all_view_frames().values()
                )
                series_list = surface.navigator._series_list
                proxy = series_list._browser_proxy
                patient_index = proxy.index(0, 0)
                study_index = proxy.index(0, 0, patient_index)
                assert proxy.rowCount() == 1
                assert proxy.rowCount(patient_index) == 1
                assert proxy.rowCount(study_index) == 4
                assert series_list._browser_view.isExpanded(patient_index)
                assert series_list._browser_view.isExpanded(study_index)
                assert series_list._browser_delegate._card_mode
            elif scenario.surface == "mpr":
                assert primary.is_ready
            elif scenario.surface == "geometry_rejection":
                assert not primary.is_ready
                assert primary._status.text() != "mpr.non_uniform_spacing"
            assert (not surface.navigator.isHidden()) is (
                scenario.surface
                not in {"start_center", "settings"}
            )
    qtbot.wait(1)


def test_real_workbench_active_tool_chip_uses_contrasting_theme_text(qtbot):
    scenarios = {
        scenario.key: scenario
        for scenario in default_v26_scenarios()
    }

    with RealMedImagerSurfaceProvider() as provider:
        for key in ("dark_zh_start_center", "light_en_settings_center"):
            scenario = scenarios[key]
            surface = provider(scenario)
            chip = surface.toolbar.active_tool_chip
            foreground = QColor(str(chip.property("contrastForeground")))
            background = QColor(str(chip.property("contrastBackground")))
            shortcut_foreground = QColor(
                str(chip.property("shortcutContrastForeground"))
            )
            shortcut_background = QColor(
                str(chip.property("shortcutContrastBackground"))
            )
            theme_text = QColor(
                provider.theme_manager.get_theme_tokens(scenario.theme)["text_color"]
            )
            palette_text = chip.name_label.palette().color(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.Text,
            )

            assert chip.isEnabled()
            assert chip.name_label.isEnabled()
            assert foreground == theme_text
            assert palette_text == theme_text
            assert _wcag_contrast(foreground, background) >= 4.5
            assert _wcag_contrast(shortcut_foreground, shortcut_background) >= 4.5
            assert float(chip.property("minimumContrastRatio")) >= 4.5
    qtbot.wait(1)


def test_real_start_center_surface_runs_through_update_and_compare_gate(
    qtbot, tmp_path
):
    scenario = default_v26_scenarios()[0]
    harness = VisualRegressionHarness(
        tmp_path / "real-baselines",
        tmp_path / "real-artifacts",
    )

    with RealMedImagerSurfaceProvider() as provider:
        update = harness.run(
            provider,
            scenarios=(scenario,),
            mode="update",
            allow_baseline_update=True,
        )
    with RealMedImagerSurfaceProvider() as provider:
        comparison = harness.run(provider, scenarios=(scenario,), mode="compare")

    assert update.passed
    assert comparison.passed
    assert comparison.results[0].metrics.mae == 0.0
    qtbot.wait(1)


def test_release_cli_requires_second_opt_in_for_baseline_update(tmp_path):
    with pytest.raises(SystemExit) as error:
        visual_release_main(
            [
                "--mode",
                "update",
                "--baseline-root",
                str(tmp_path / "baselines"),
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )

    assert error.value.code == 2
    assert not (tmp_path / "baselines").exists()
