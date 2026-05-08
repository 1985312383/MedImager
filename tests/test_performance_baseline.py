import json

from medimager.performance.baseline import SCHEMA, SCHEMA_VERSION, run_baseline


def test_performance_baseline_outputs_stable_schema(tmp_path):
    output_path = tmp_path / "baseline.json"

    result = run_baseline(
        slices=4,
        rows=16,
        cols=16,
        repeats=1,
        display_samples=3,
        output_path=output_path,
    )

    assert result["schema"] == SCHEMA
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["dataset"]["slices"] == 4
    assert result["dataset"]["rows"] == 16
    assert result["dataset"]["cols"] == 16
    assert result["dataset"]["display_samples"] == 3
    assert result["benchmarks"]["dicom_series_load"]["slices_per_second"] > 0
    assert result["benchmarks"]["display_windowing_cold"]["slices_per_second"] > 0
    assert result["benchmarks"]["display_windowing_cached"]["slices_per_second"] > 0
    assert result["benchmarks"]["display_qimage_conversion"]["images_per_second"] > 0

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["schema"] == SCHEMA
    assert saved["schema_version"] == SCHEMA_VERSION
