# 处理统计计算 (HU 值统计等) 

import numpy as np
from typing import Optional, Dict, Union, Any

# These imports will be conditionally available due to the project structure.
# We expect them to be available when run from the main application.
try:
    from medimager.core.image_data_model import ImageDataModel
    from medimager.core.roi import BaseROI
except ImportError:
    # This allows the module to be imported in contexts where sibling modules aren't available,
    # though the functions will not be usable.
    ImageDataModel = None
    BaseROI = None


def calculate_roi_statistics(model: 'ImageDataModel', roi: 'BaseROI') -> Optional[Dict[str, float]]:
    """
    Calculates statistics for a given ROI from the raw pixel data.

    Args:
        model: The ImageDataModel containing the pixel data.
        roi: The BaseROI object defining the region.

    Returns:
        A dictionary with statistics (mean, std, max, min, count) or None if calculation fails.
    """
    if not ImageDataModel or not model or model.pixel_array is None:
        return None

    # Get the raw slice data (already has rescale slope/intercept applied by DicomParser)
    slice_data = model.get_slice_data(roi.slice_index)
    if slice_data is None:
        return None

    height, width = slice_data.shape[:2]
    mask = roi.get_mask(height, width)

    # Check if the mask covers any pixels
    if not np.any(mask):
        return None

    pixels_in_roi = slice_data[mask]
    if pixels_in_roi.ndim > 1:
        pixels_in_roi = pixels_in_roi.mean(axis=-1)

    pixel_count = int(np.sum(mask))

    stats = {
        "max": float(np.max(pixels_in_roi)),
        "min": float(np.min(pixels_in_roi)),
        "mean": float(np.mean(pixels_in_roi)),
        "std": float(np.std(pixels_in_roi)),
        "count": pixel_count,
        "area_px": float(pixel_count),
    }

    pixel_spacing = _get_pixel_spacing(model.dicom_header)
    if pixel_spacing:
        row_spacing, col_spacing = pixel_spacing
        stats["area_mm2"] = float(pixel_count * row_spacing * col_spacing)

    return stats 


def _get_pixel_spacing(metadata: Dict[str, Any]) -> Optional[tuple[float, float]]:
    for key in ("PixelSpacing", "Pixel Spacing", "ImagerPixelSpacing", "Imager Pixel Spacing"):
        value = metadata.get(key)
        if value is None:
            continue
        try:
            if len(value) >= 2:
                return float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            continue
    return None
