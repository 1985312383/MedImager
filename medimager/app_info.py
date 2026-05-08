"""Application metadata helpers used by UI and release packaging."""

from __future__ import annotations

from html import escape
from importlib import metadata
from pathlib import Path


APP_NAME = "MedImager"
AUTHOR = "1985312383 / MedImager contributors"
PROJECT_URL = "https://github.com/1985312383/MedImager"
DESCRIPTION = "面向 RadiAnt 级工作流演进的开源 DICOM 查看器与医学图像分析工具"
LICENSE_NAME = "GPL-3.0-or-later"


def get_version() -> str:
    """Return the release/build version, falling back to local project metadata."""
    build_version = _get_build_value("VERSION")
    if build_version:
        return build_version

    try:
        return metadata.version("medimager")
    except metadata.PackageNotFoundError:
        pass

    pyproject_version = _read_pyproject_version()
    if pyproject_version:
        return pyproject_version

    return "0.0.0"


def get_latest_release_changelog() -> str:
    """Return the most recent release changelog text."""
    build_changelog = _get_build_value("RELEASE_CHANGELOG")
    if build_changelog:
        return build_changelog

    changelog_path = _project_root() / "CHANGELOG.md"
    if not changelog_path.exists():
        return "暂无 release changelog。"

    return _extract_latest_changelog(changelog_path.read_text(encoding="utf-8"))


def get_about_html() -> str:
    """Return rich text for the About dialog."""
    changelog_html = _markdown_changelog_to_html(get_latest_release_changelog())
    return f"""
    <h3>{escape(APP_NAME)}</h3>
    <p>{escape(DESCRIPTION)}</p>
    <p><b>版本:</b> {escape(get_version())}</p>
    <p><b>作者:</b> {escape(AUTHOR)}</p>
    <p><b>项目地址:</b> <a href="{escape(PROJECT_URL)}">{escape(PROJECT_URL)}</a></p>
    <p><b>许可证:</b> {escape(LICENSE_NAME)}</p>
    <h4>最近一次 Release Changelog</h4>
    {changelog_html}
    """


def _get_build_value(name: str) -> str:
    try:
        from medimager import _build_info

        value = getattr(_build_info, name, "")
        return str(value).strip()
    except Exception:
        return ""


def _read_pyproject_version() -> str:
    pyproject_path = _project_root() / "pyproject.toml"
    if not pyproject_path.exists():
        return ""

    try:
        import tomllib
    except ModuleNotFoundError:
        return ""

    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "")).strip()
    except Exception:
        return ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _extract_latest_changelog(changelog_text: str) -> str:
    lines = changelog_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## "):
            start = index
            break

    if start is None:
        return changelog_text.strip() or "暂无 release changelog。"

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    latest = "\n".join(lines[start:end]).strip()
    return latest or "暂无 release changelog。"


def _markdown_changelog_to_html(changelog_text: str) -> str:
    html_lines: list[str] = []
    in_list = False

    for raw_line in changelog_text.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        if line.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p><b>{escape(line[3:].strip())}</b></p>")
        elif line.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p><b>{escape(line[4:].strip())}</b></p>")
        elif line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{escape(line[2:].strip())}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{escape(line)}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines) or "<p>暂无 release changelog。</p>"
