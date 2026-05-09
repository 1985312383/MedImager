from medimager import app_info
import re


def test_version_falls_back_to_pyproject():
    assert app_info.get_version() == "2.0.0"


def test_latest_changelog_and_about_include_release_metadata():
    changelog = app_info.get_latest_release_changelog()
    about_html = app_info.get_about_html()

    assert changelog.startswith("## ")
    assert "Project URL" in about_html
    assert app_info.PROJECT_URL in about_html
    assert "Latest Release Changelog" in about_html
    assert not re.search(r"[\u4e00-\u9fff]", about_html)
