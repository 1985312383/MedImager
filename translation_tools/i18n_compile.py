#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile MedImager YAML translation sources to runtime JSON catalogs.

This intentionally supports a small YAML subset:
- indentation-based mappings
- string, integer, boolean, and null scalar values
- quoted strings via Python-style single or double quotes

That keeps runtime free of a YAML dependency while making translation files
pleasant to maintain by hand.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = PROJECT_ROOT / "medimager" / "i18n" / "locales"
COMPILED_DIR = PROJECT_ROOT / "medimager" / "i18n" / "compiled"
DEFAULT_LANGUAGE = "en_US"
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class I18nCompileError(RuntimeError):
    pass


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent % 2 != 0:
            raise I18nCompileError(f"{path}:{line_number}: indentation must use multiples of two spaces")

        line = raw_line.strip()
        key, sep, value = line.partition(":")
        if not sep:
            raise I18nCompileError(f"{path}:{line_number}: expected 'key: value'")
        key = key.strip()
        value = value.strip()
        if not key:
            raise I18nCompileError(f"{path}:{line_number}: empty key")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise I18nCompileError(f"{path}:{line_number}: invalid indentation")

        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(value, path, line_number)

    return root


def parse_scalar(value: str, path: Path, line_number: int) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value.startswith(("'", '"')):
        try:
            return ast.literal_eval(value)
        except Exception as exc:
            raise I18nCompileError(f"{path}:{line_number}: invalid quoted string: {exc}") from exc
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def flatten_messages(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    messages: dict[str, str] = {}
    for key, value in data.items():
        if key in {"meta", "legacy"} and prefix == "":
            continue
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            messages.update(flatten_messages(value, full_key))
        elif value is None:
            messages[full_key] = ""
        else:
            messages[full_key] = str(value)
    return messages


def catalog_messages(data: dict[str, Any]) -> dict[str, str]:
    explicit_messages = data.get("messages")
    if isinstance(explicit_messages, dict):
        return flatten_messages(explicit_messages)
    return flatten_messages(data)


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def compile_catalogs(locales_dir: Path = LOCALES_DIR, compiled_dir: Path = COMPILED_DIR) -> list[Path]:
    source_file = locales_dir / f"{DEFAULT_LANGUAGE}.yml"
    if not source_file.exists():
        raise I18nCompileError(f"Missing default locale: {source_file}")

    default_payload = parse_simple_yaml(source_file)
    default_messages = catalog_messages(default_payload)
    default_keys = set(default_messages)

    compiled_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for locale_file in sorted(locales_dir.glob("*.yml")):
        payload = parse_simple_yaml(locale_file)
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            raise I18nCompileError(f"{locale_file}: meta must be a mapping")

        language = str(meta.get("language", locale_file.stem))
        messages = catalog_messages(payload)
        missing = sorted(default_keys - set(messages))
        extra = sorted(set(messages) - default_keys)

        if language != DEFAULT_LANGUAGE:
            for key in sorted(default_keys & set(messages)):
                expected = placeholders(default_messages[key])
                actual = placeholders(messages[key])
                if expected != actual:
                    raise I18nCompileError(
                        f"{locale_file}: placeholder mismatch for {key}: "
                        f"expected {sorted(expected)}, got {sorted(actual)}"
                    )

        output = {
            "meta": {
                "language": language,
                "name": str(meta.get("name", language)),
                "fallback": meta.get("fallback", DEFAULT_LANGUAGE if language != DEFAULT_LANGUAGE else None),
            },
            "messages": messages,
            "diagnostics": {
                "missing": missing,
                "extra": extra,
            },
        }
        output_file = compiled_dir / f"{language}.json"
        output_file.write_text(
            json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(output_file)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locales-dir", type=Path, default=LOCALES_DIR)
    parser.add_argument("--compiled-dir", type=Path, default=COMPILED_DIR)
    args = parser.parse_args()

    try:
        written = compile_catalogs(args.locales_dir, args.compiled_dir)
    except I18nCompileError as exc:
        print(f"[FAIL] {exc}")
        return 1

    for path in written:
        print(f"[OK] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
