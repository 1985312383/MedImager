from medimager import app_info


def test_version_falls_back_to_pyproject():
    assert app_info.get_version() == "1.0.1"


def test_latest_changelog_and_about_include_release_metadata():
    changelog = app_info.get_latest_release_changelog()
    about_html = app_info.get_about_html()

    assert changelog.startswith("## 1.0.1")
    assert "项目地址" in about_html
    assert app_info.PROJECT_URL in about_html
    assert "最近一次 Release Changelog" in about_html
