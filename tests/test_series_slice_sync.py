import numpy as np

from medimager.core.image_data_model import ImageDataModel
from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.series_view_binding import BindingStrategy
from medimager.ui.main_window import MainWindow
from medimager.ui.multi_viewer_grid import MultiViewerGrid


def make_model(slice_count: int = 4) -> ImageDataModel:
    model = ImageDataModel()
    data = np.arange(slice_count * 5 * 5, dtype=np.float32).reshape(slice_count, 5, 5)
    assert model.load_single_image(data)
    return model


def add_loaded_series(manager: MultiSeriesManager, series_id: str) -> ImageDataModel:
    model = make_model()
    info = SeriesInfo(
        series_id=series_id,
        patient_name="Synthetic",
        series_description=series_id,
        modality="CT",
        series_number=series_id[-1],
        slice_count=model.get_slice_count(),
    )
    manager.add_series(info)
    assert manager.load_series_data(series_id, model)
    return model


def test_drop_into_view_activates_target_view(qapp):
    manager = MultiSeriesManager()
    assert manager.set_layout(1, 2)
    grid = MultiViewerGrid(manager)

    assert manager.get_active_view_id() == "view_0_0"

    grid._on_view_frame_drop_requested("view_0_1", "series_2")

    assert manager.get_active_view_id() == "view_0_1"
    grid.deleteLater()
    qapp.processEvents()


def test_active_view_rebind_reconnects_main_window_slice_model(qapp):
    window = MainWindow()
    window.binding_manager.set_binding_strategy(BindingStrategy.PRESERVE_EXISTING)

    model_1 = add_loaded_series(window.series_manager, "series_1")
    model_2 = add_loaded_series(window.series_manager, "series_2")

    assert window.series_manager.bind_series_to_view("view_0_0", "series_1")
    qapp.processEvents()
    assert window._current_active_model is model_1

    assert window.series_manager.bind_series_to_view("view_0_0", "series_2")
    qapp.processEvents()

    assert window._current_active_model is model_2
    model_2.set_current_slice(2)
    qapp.processEvents()
    assert model_2.current_slice_index == 2

    window.close()
    qapp.processEvents()
