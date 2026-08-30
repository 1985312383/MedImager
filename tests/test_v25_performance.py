import numpy as np

from medimager.core.image_data_model import ImageDataModel
from medimager.core.view_presentation_state import (
    ViewPresentationState,
    build_render_request,
    prefetch_display_slices,
    render_display_slice,
)
from medimager.ui.panels.series_panel import _fit_thumbnail_array
from medimager.utils.settings import get_performance_manager


def test_view_render_path_reuses_the_shared_lru_cache(qapp):
    model = ImageDataModel()
    assert model.load_single_image(np.arange(64, dtype=np.float32).reshape(8, 8))
    state = ViewPresentationState.from_model(model)
    perf = get_performance_manager()
    perf.clear_cache()

    first = render_display_slice(model, state)
    second = render_display_slice(model, state)

    assert second is first
    assert perf.get_cache_info()["item_count"] == 1


def test_neighbor_prefetch_populates_the_exact_view_render_key(qapp):
    model = ImageDataModel()
    volume = np.stack(
        [np.full((12, 10), value, dtype=np.float32) for value in range(5)]
    )
    assert model.load_single_image(volume)
    state = ViewPresentationState.from_model(model)
    state.slice_index = 2
    perf = get_performance_manager()
    perf.clear_cache()

    futures = prefetch_display_slices(model, state, (3, 1))
    for _, future in futures:
        future.result(timeout=5)

    state.slice_index = 3
    key, _ = build_render_request(model, state)
    cached = perf.get_from_cache(key)
    assert cached is not None
    assert render_display_slice(model, state) is cached


def test_thumbnail_worker_letterboxes_to_a_fixed_contiguous_canvas():
    source = np.arange(200, dtype=np.uint8).reshape(10, 20)
    thumbnail = _fit_thumbnail_array(source)
    assert thumbnail.shape == (56, 72)
    assert thumbnail.dtype == np.uint8
    assert thumbnail.flags.c_contiguous
    assert np.all(thumbnail[:10] == 22)
