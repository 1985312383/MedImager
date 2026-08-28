"""Pure display rendering shared by 2-D and MPR viewports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import warnings

import numpy as np
from pydicom.pixels import apply_voi_lut


@dataclass(frozen=True)
class RenderRequest:
    pixels: np.ndarray
    window_width: float
    window_level: float
    voi_function: str = "LINEAR"
    inverted: bool = False
    monochrome1: bool = False
    presentation_lut_shape: str = "IDENTITY"
    use_dicom_voi_lut: bool = False
    voi_lut_index: int = 0
    dataset: Optional[object] = None


@dataclass(frozen=True)
class RenderedFrame:
    pixels_uint8: np.ndarray
    source_min: float
    source_max: float


def render_frame(request: RenderRequest) -> RenderedFrame:
    """Render without reading or mutating shared model presentation fields."""
    width = float(request.window_width)
    center = float(request.window_level)
    if not np.isfinite(width) or width < 1 or not np.isfinite(center):
        raise ValueError("window width/level must be finite and width must be >= 1")
    data = np.asarray(request.pixels, dtype=np.float32)
    if data.ndim != 2:
        raise ValueError("RenderRequest pixels must be a two-dimensional image")
    finite = data[np.isfinite(data)]
    source_min = float(finite.min()) if finite.size else 0.0
    source_max = float(finite.max()) if finite.size else 0.0

    dataset = request.dataset
    sequence = getattr(dataset, "VOILUTSequence", None) if dataset is not None else None
    if request.use_dicom_voi_lut and sequence:
        index = max(0, min(int(request.voi_lut_index), len(sequence) - 1))
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Applying a VOI LUT on a float input array may give incorrect results",
                category=UserWarning,
            )
            voi = np.asarray(
                apply_voi_lut(data, dataset, index=index, prefer_lut=True),
                dtype=np.float64,
            )
        descriptor = sequence[index].LUTDescriptor
        bits = int(descriptor[2]) if len(descriptor) >= 3 else 8
        maximum = float((1 << max(1, bits)) - 1)
        output = np.clip(
            np.nan_to_num(voi / maximum * 255.0, nan=0.0, posinf=255.0, neginf=0.0),
            0.0,
            255.0,
        ).astype(np.uint8)
    else:
        function = str(request.voi_function or "LINEAR").upper()
        if function == "SIGMOID":
            exponent = np.clip(-4.0 * (data - center) / width, -700.0, 700.0)
            normalized = 255.0 / (1.0 + np.exp(exponent))
        elif function == "LINEAR_EXACT":
            normalized = (data - (center - width / 2.0)) / width * 255.0
        elif width == 1:
            normalized = np.where(data <= center - 0.5, 0.0, 255.0)
        else:
            lower = center - 0.5 - (width - 1.0) / 2.0
            upper = center - 0.5 + (width - 1.0) / 2.0
            normalized = ((data - (center - 0.5)) / (width - 1.0) + 0.5) * 255.0
            normalized = np.where(data <= lower, 0.0, normalized)
            normalized = np.where(data > upper, 255.0, normalized)
        output = np.clip(
            np.nan_to_num(normalized, nan=0.0, posinf=255.0, neginf=0.0),
            0.0,
            255.0,
        ).astype(np.uint8)

    inverse = bool(request.monochrome1)
    if str(request.presentation_lut_shape).upper() == "INVERSE":
        inverse = not inverse
    if request.inverted:
        inverse = not inverse
    if inverse:
        output = 255 - output
    output.setflags(write=False)
    return RenderedFrame(output, source_min=source_min, source_max=source_max)
