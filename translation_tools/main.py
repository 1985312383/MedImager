#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MedImager i18n toolchain entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent


def run_script(script_name: str, *args: str) -> int:
    command = [sys.executable, str(TOOL_DIR / script_name), *args]
    print(" ".join(command))
    return subprocess.call(command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    code = run_script("i18n_compile.py")
    if code != 0:
        return code
    return run_script("i18n_check.py")


if __name__ == "__main__":
    raise SystemExit(main())
