"""Per-view presentation state for a shared image series.

The pixel volume and annotations belong to :class:`ImageDataModel`, while the
state in this module belongs to one viewport.  Keeping these concerns separate
allows the same series to be displayed with different slices, VOI settings and
geometric transforms in multiple viewports.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Iterator, Optional

from PySide6.QtCore import QPointF


class InterpolationMode(str, Enum):
    """Image sampling policy used by a viewport."""

    ADAPTIVE = "adaptive"
    SMOOTH = "smooth"
    PIXEL_EXACT = "pixel_exact"

    @classmethod
    def coerce(cls, value: object) -> "InterpolationMode":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "auto": cls.ADAPTIVE,
            "adaptive": cls.ADAPTIVE,
            "linear": cls.SMOOTH,
            "smooth": cls.SMOOTH,
            "nearest": cls.PIXEL_EXACT,
            "fast": cls.PIXEL_EXACT,
            "pixel": cls.PIXEL_EXACT,
            "pixel_exact": cls.PIXEL_EXACT,
        }
        return aliases.get(text, cls.ADAPTIVE)


@dataclass
class ViewPresentationState:
    """All mutable display choices that are local to one viewport."""

    series_id: Optional[str] = None
    slice_index: int = 0
    window_width: float = 400.0
    window_level: float = 40.0
    use_dicom_voi_lut: bool = False
    voi_lut_index: Optional[int] = None
    zoom: float = 1.0
    pan_center: QPointF = field(default_factory=QPointF)
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    inverted: bool = False
    interpolation: InterpolationMode = InterpolationMode.ADAPTIVE
    magnifier_enabled: bool = False
    fit_mode: bool = True
    use_physical_pixel_aspect: bool = True

    MIN_ZOOM = 0.05
    MAX_ZOOM = 32.0

    @classmethod
    def from_model(
        cls,
        model,
        *,
        series_id: Optional[str] = None,
        interpolation: object = InterpolationMode.ADAPTIVE,
    ) -> "ViewPresentationState":
        return cls(
            series_id=series_id,
            slice_index=max(0, int(getattr(model, "current_slice_index", 0))),
            window_width=max(1.0, float(getattr(model, "window_width", 400.0))),
            window_level=float(getattr(model, "window_level", 40.0)),
            use_dicom_voi_lut=bool(getattr(model, "_use_dicom_voi_lut", False)),
            interpolation=InterpolationMode.coerce(interpolation),
        )

    def clamp(self, slice_count: Optional[int] = None) -> None:
        self.window_width = max(1.0, float(self.window_width))
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(self.zoom)))
        self.rotation = int(round(self.rotation / 90.0) * 90) % 360
        self.interpolation = InterpolationMode.coerce(self.interpolation)
        if slice_count is not None:
            self.slice_index = max(0, min(int(self.slice_index), max(0, slice_count - 1)))
        else:
            self.slice_index = max(0, int(self.slice_index))

    def copy_fields_from(
        self,
        source: "ViewPresentationState",
        fields: Iterable[str],
    ) -> None:
        """Copy only explicitly selected presentation fields."""

        for name in fields:
            if not hasattr(self, name) or not hasattr(source, name):
                continue
            value = getattr(source, name)
            setattr(self, name, QPointF(value) if isinstance(value, QPointF) else value)
        self.clamp()


@contextmanager
def model_presentation_context(model, state: ViewPresentationState) -> Iterator[None]:
    """Temporarily expose a view state to legacy model rendering methods.

    ``ImageDataModel.get_display_slice`` currently reads WW/WL from the model.
    Qt GUI rendering is single-threaded, so assigning the fields without
    emitting signals for the duration of one render is safe and lets us reuse
    the model's DICOM-correct VOI implementation.  All values are restored even
    when rendering raises.
    """

    names = (
        "current_slice_index",
        "window_width",
        "window_level",
        "_use_dicom_voi_lut",
        "_voi_lut_index",
    )
    saved = {name: getattr(model, name, None) for name in names}
    model.current_slice_index = int(state.slice_index)
    model.window_width = float(state.window_width)
    model.window_level = float(state.window_level)
    model._use_dicom_voi_lut = bool(state.use_dicom_voi_lut)
    model._voi_lut_index = int(state.voi_lut_index or 0)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(model, name, value)


def render_display_slice(model, state: ViewPresentationState):
    """Render one slice using the presentation choices of one viewport."""

    state.clamp(getattr(model, "get_slice_count", lambda: 0)())
    with model_presentation_context(model, state):
        return model.get_display_slice(state.slice_index)


def pixel_value_for_view(model, state: ViewPresentationState, x: int, y: int):
    """Return a raw pixel value without consulting the model's shared cursor."""

    data = model.get_slice_data(state.slice_index)
    if data is None or not (0 <= y < data.shape[0] and 0 <= x < data.shape[1]):
        return None
    value = data[y, x]
    try:
        import numpy as np

        if np.isscalar(value):
            return float(value)
        channels = np.asarray(value).reshape(-1)
        if channels.size in (3, 4) and np.issubdtype(channels.dtype, np.number):
            return tuple(float(channel) for channel in channels)
    except (TypeError, ValueError):
        return None
    return None
