"""Qt image conversion helpers for display-ready numpy arrays."""

import numpy as np
from PySide6.QtGui import QImage


def qimage_from_display_data(display_data: np.ndarray) -> QImage:
    """Create a QImage from grayscale, RGB, or RGBA uint8 display data."""
    image_data = np.ascontiguousarray(display_data)

    if image_data.ndim == 2:
        height, width = image_data.shape
        q_image = QImage(image_data.data, width, height, width, QImage.Format_Grayscale8)
    elif image_data.ndim == 3 and image_data.shape[2] == 3:
        height, width, _ = image_data.shape
        q_image = QImage(image_data.data, width, height, width * 3, QImage.Format_RGB888)
    elif image_data.ndim == 3 and image_data.shape[2] == 4:
        height, width, _ = image_data.shape
        q_image = QImage(image_data.data, width, height, width * 4, QImage.Format_RGBA8888)
    else:
        raise ValueError(f"Unsupported display data shape: {image_data.shape}")

    return q_image.copy()
