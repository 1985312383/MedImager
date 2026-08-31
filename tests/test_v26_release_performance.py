from __future__ import annotations

import copy
import json

import pytest

from medimager.performance.v26_release import (
    DEFAULT_REGRESSION_METRICS,
    QUICK_PROFILE,
    SCHEMA,
    SCHEMA_VERSION,
    compare_release_baselines,
    load_release_baseline,
    run_v26_release_baseline,
)


def test_v26_quick_release_baseline_exercises_real_pipeline(tmp_path, qapp):
    output = tmp_path / "v26-baseline.json"

    result = run_v26_release_baseline(
        profile=QUICK_PROFILE,
        sync_samples=4,
        timeout_seconds=15,
        output_path=output,
        work_parent=tmp_path,
        event_app=qapp,
    )

    assert result["schema"] == SCHEMA
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["studies"] == [
        "ct_multiphase",
        "mr_brain",
        "geometry_lab",
    ]
    benchmarks = result["benchmarks"]
    assert benchmarks["demo_generation"]["deterministic"]
    assert set(benchmarks["demo_generation"]["studies_ms"]) == set(
        result["studies"]
    )
    assert benchmarks["folder_scan"]["study_count"] == 1
    assert benchmarks["folder_scan"]["series_count"] == 4
    readiness = benchmarks["series_readiness_proxy"]
    assert readiness["successful_series"] == readiness["total_series"] == 4
    assert 0 < readiness["first_series_ms"] <= readiness["all_series_ms"]
    assert benchmarks["cache_second_open"]["cache_hit"]
    assert benchmarks["cache_second_open"]["new_service_instance"] is True
    assert benchmarks["mpr"]["volume_build_ms"] > 0
    assert benchmarks["mpr"]["first_frame_ms"] > 0
    assert benchmarks["mpr"]["interaction_p95_ms"] > 0
    assert benchmarks["sync_interaction"]["p95_ms"] > 0
    heartbeat = benchmarks["gui_heartbeat"]
    assert heartbeat["sample_count"] > 0
    assert heartbeat["max_gap_ms"] < heartbeat["target_ms"] == 100.0
    assert heartbeat["within_target"]
    assert result["regression_policy"]["baseline_version"] == "2.6"
    assert result["regression_policy"]["relative_limit"] == 1.2

    saved = load_release_baseline(output)
    assert saved["schema"] == SCHEMA
    assert saved["benchmarks"]["demo_generation"]["semantic_digest"] == (
        benchmarks["demo_generation"]["semantic_digest"]
    )


def test_regression_comparison_enforces_twenty_percent_boundary():
    baseline = _comparison_document(100.0)
    exactly_at_limit = _comparison_document(120.0)
    regressed = _comparison_document(120.001)

    passing_report = compare_release_baselines(exactly_at_limit, baseline)
    failing_report = compare_release_baselines(regressed, baseline)

    assert passing_report.comparable
    assert passing_report.passed
    assert failing_report.comparable
    assert not failing_report.passed
    assert len(failing_report.regressions) == len(DEFAULT_REGRESSION_METRICS)
    assert all(item.ratio > 1.2 for item in failing_report.regressions)


def test_regression_comparison_reports_missing_and_rejects_wrong_schema():
    baseline = _comparison_document(100.0)
    incomplete = copy.deepcopy(baseline)
    del incomplete["benchmarks"]["mpr"]["first_frame_ms"]

    report = compare_release_baselines(incomplete, baseline)

    assert not report.comparable
    assert not report.passed
    assert any(
        item.metric == "benchmarks.mpr.first_frame_ms"
        and item.status == "missing"
        for item in report.findings
    )

    invalid = copy.deepcopy(baseline)
    invalid["schema_version"] = 99
    with pytest.raises(ValueError, match="Unsupported performance schema version"):
        compare_release_baselines(invalid, baseline)


def test_load_release_baseline_rejects_non_object(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_release_baseline(path)


def _comparison_document(value: float) -> dict:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "benchmarks": {
            "demo_generation": {"total_ms": value, "python_peak_mb": value},
            "folder_scan": {"total_ms": value},
            "series_readiness_proxy": {
                "first_series_ms": value,
                "all_series_ms": value,
            },
            "cache_second_open": {"total_ms": value},
            "mpr": {
                "volume_build_ms": value,
                "first_frame_ms": value,
                "interaction_p95_ms": value,
            },
            "sync_interaction": {"p95_ms": value},
            "gui_heartbeat": {"max_gap_ms": value},
        },
    }
