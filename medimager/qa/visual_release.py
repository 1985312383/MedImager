"""Command-line release gate for MedImager v2.6 visual regression.

Run with ``python -m medimager.qa.visual_release --help``.  Baseline mutation
requires two explicit switches; normal invocation is compare-only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m medimager.qa.visual_release",
        description=(
            "Capture all 12 real MedImager v2.6 surfaces and compare them with "
            "the reviewed Windows visual baselines."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("compare", "update"),
        default="compare",
        help="Compare by default; update writes a new atomic baseline manifest.",
    )
    parser.add_argument(
        "--allow-baseline-update",
        action="store_true",
        help="Required together with --mode update to permit baseline mutation.",
    )
    parser.add_argument(
        "--baseline-root",
        type=Path,
        default=Path("release/visual-baselines/v2.6"),
        help="Reviewed baseline directory (default: release/visual-baselines/v2.6).",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("build/visual-regression/v2.6"),
        help="Actual, diff, metrics, and visibility output directory.",
    )
    parser.add_argument(
        "--visibility-only",
        action="store_true",
        help="Run 125%%/150%% geometry checks without pixel capture or baselines.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.mode == "update" and not args.allow_baseline_update:
        parser.error("--mode update requires --allow-baseline-update")
    if args.mode != "update" and args.allow_baseline_update:
        parser.error("--allow-baseline-update is only valid with --mode update")
    if args.visibility_only and args.mode == "update":
        parser.error("--visibility-only cannot be combined with --mode update")


def run_release_gate(args: argparse.Namespace) -> int:
    """Execute a parsed release run and return a process-style exit code."""

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from medimager.qa.visual_regression import (
        VisualRegressionHarness,
        default_v26_manifest_metadata,
        default_v26_scenarios,
        run_visibility_matrix,
    )
    from medimager.qa.visual_surfaces import (
        RealMedImagerSurfaceProvider,
        critical_widgets_for_surface,
    )

    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(["medimager-visual-release"])
    app.setApplicationName("MedImager Visual Release Gate")
    app.setFont(QFont("Segoe UI", 9))

    try:
        with RealMedImagerSurfaceProvider() as provider:
            if args.visibility_only:
                report = run_visibility_matrix(
                    provider,
                    scenarios=default_v26_scenarios(),
                    required_widgets=critical_widgets_for_surface,
                    artifact_root=args.artifact_root,
                )
                payload = {
                    "mode": "visibility_only",
                    "passed": report.passed,
                    "scenario_checks": len(report.results),
                    "report": str(report.report_path),
                }
            else:
                harness = VisualRegressionHarness(
                    args.baseline_root,
                    args.artifact_root,
                )
                report = harness.run(
                    provider,
                    scenarios=default_v26_scenarios(),
                    mode=args.mode,
                    allow_baseline_update=args.allow_baseline_update,
                    manifest_metadata=default_v26_manifest_metadata(),
                )
                payload = {
                    "mode": args.mode,
                    "passed": report.passed,
                    "scenario_count": len(report.results),
                    "failed": list(report.failed_keys),
                    "report": str(report.report_path),
                    "baseline_manifest": str(report.baseline_manifest_path),
                }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if report.passed else 1
    finally:
        if owns_application:
            app.quit()


def main(argv: Sequence[str] | None = None) -> int:
    # Set deterministic scale inputs before the first QApplication is created.
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return run_release_gate(args)


if __name__ == "__main__":
    raise SystemExit(main())
