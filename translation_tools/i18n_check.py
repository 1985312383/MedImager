#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate compiled MedImager i18n catalogs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPILED_DIR = PROJECT_ROOT / "medimager" / "i18n" / "compiled"
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def check_catalogs(compiled_dir: Path = COMPILED_DIR) -> list[str]:
    issues: list[str] = []
    for catalog_file in sorted(compiled_dir.glob("*.json")):
        if catalog_file.stem == "zh_CN":
            continue

        payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        messages = payload.get("messages", {})
        for key, value in sorted(messages.items()):
            if CHINESE_RE.search(str(value)):
                issues.append(f"{catalog_file.name}: {key} still contains Chinese text: {value}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled-dir", type=Path, default=COMPILED_DIR)
    args = parser.parse_args()

    issues = check_catalogs(args.compiled_dir)
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        return 1

    print("[OK] No Chinese text remains in non-Chinese compiled catalogs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

