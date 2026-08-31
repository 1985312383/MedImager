from medimager.main import (
    MedImagerApplication,
    StartupRequest,
    parse_startup_arguments,
    qt_application_arguments,
)


class _Window:
    def __init__(self):
        self.paths = None
        self.demo = None

    def _open_dropped_paths(self, paths):
        self.paths = tuple(paths)

    def _request_demo_study(self, demo):
        self.demo = demo


def test_startup_arguments_support_paths_and_automated_demo(tmp_path):
    path_request = parse_startup_arguments(["medimager", str(tmp_path)])
    assert path_request.paths == (str(tmp_path),)
    assert path_request.demo is None

    demo_request = parse_startup_arguments(
        ["medimager", "--demo", "geometry_lab"]
    )
    assert demo_request == StartupRequest(demo="geometry_lab")
    assert parse_startup_arguments(
        ["medimager", "--style", "Fusion", "--demo", "geometry_lab"]
    ) == demo_request
    assert qt_application_arguments(
        ["medimager", "--style", "Fusion", "--demo", "geometry_lab"],
        demo_request,
    ) == ["medimager", "--style", "Fusion"]


def test_startup_dispatch_reuses_normal_local_and_demo_pipelines(qapp, tmp_path):
    window = _Window()
    application = MedImagerApplication(qapp, StartupRequest(paths=(str(tmp_path),)))
    application.main_window = window
    application._dispatch_startup_request()
    assert window.paths == (str(tmp_path),)
    assert window.demo is None

    application.startup_request = StartupRequest(demo="ct_multiphase")
    application._dispatch_startup_request()
    assert window.demo == "ct_multiphase"
