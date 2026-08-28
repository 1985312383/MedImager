import numpy as np
from PySide6.QtCore import QPointF

from medimager.core.view_presentation_state import (
    InterpolationMode,
    ViewPresentationState,
    pixel_value_for_view,
    render_display_slice,
)


class _SharedModel:
    def __init__(self):
        self.current_slice_index = 2
        self.window_width = 400
        self.window_level = 40
        self._use_dicom_voi_lut = False
        self._voi_lut_index = 0
        self._pixels = np.arange(4 * 3 * 3).reshape(4, 3, 3)

    def get_slice_count(self):
        return len(self._pixels)

    def get_display_slice(self, index):
        return (
            index,
            self.current_slice_index,
            self.window_width,
            self.window_level,
            self._use_dicom_voi_lut,
            self._voi_lut_index,
        )

    def get_slice_data(self, index):
        return self._pixels[index]


def test_two_view_states_render_independently_and_restore_shared_model():
    model = _SharedModel()
    first = ViewPresentationState(
        slice_index=0, window_width=80, window_level=20,
        use_dicom_voi_lut=True, voi_lut_index=2,
    )
    second = ViewPresentationState(
        slice_index=3, window_width=1200, window_level=-150,
    )

    assert render_display_slice(model, first) == (0, 0, 80, 20, True, 2)
    assert render_display_slice(model, second) == (3, 3, 1200, -150, False, 0)
    assert (
        model.current_slice_index,
        model.window_width,
        model.window_level,
        model._use_dicom_voi_lut,
        model._voi_lut_index,
    ) == (2, 400, 40, False, 0)


def test_copy_fields_only_syncs_explicit_presentation_choices():
    source = ViewPresentationState(
        slice_index=3,
        window_width=900,
        window_level=100,
        zoom=4.0,
        pan_center=QPointF(8.0, 9.0),
        rotation=90,
    )
    target = ViewPresentationState(slice_index=1, zoom=1.5, rotation=270)

    target.copy_fields_from(source, ("slice_index", "window_width", "window_level"))

    assert target.slice_index == 3
    assert target.window_width == 900
    assert target.window_level == 100
    assert target.zoom == 1.5
    assert target.rotation == 270


def test_zoom_interpolation_and_pixel_lookup_are_pane_local():
    state = ViewPresentationState(
        slice_index=3, zoom=100, interpolation=InterpolationMode.coerce("nearest")
    )
    state.clamp(4)

    assert state.zoom == ViewPresentationState.MAX_ZOOM
    assert state.interpolation is InterpolationMode.PIXEL_EXACT
    assert pixel_value_for_view(_SharedModel(), state, 1, 2) == 34.0
