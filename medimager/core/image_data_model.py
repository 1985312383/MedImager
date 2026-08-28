#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像数据模型模块
单张图像或 DICOM 序列的数据模型

职责:
- 作为单个图像序列（如一个CT扫描）的独立数据容器
- 完全独立于UI，只负责数据的存储、处理和状态维护
- 提供数据访问和处理的标准接口
"""

import numpy as np
from contextlib import contextmanager
import pydicom
import warnings
from pydicom.pixels import apply_modality_lut, apply_voi_lut
from typing import List, Dict, Any, Optional
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, QPointF

from medimager.utils.logger import get_logger
from medimager.utils.settings import get_performance_manager, get_settings_manager
from medimager.core.dicom_parser import DicomParser
from medimager.core.roi import BaseROI
from dataclasses import dataclass


@dataclass
class MeasurementData:
    """测量数据类"""

    id: str
    slice_index: int
    start_point: QPointF
    end_point: QPointF
    distance: float
    unit: str = "mm"

    def __post_init__(self):
        """初始化后处理"""
        pass


@dataclass
class AngleMeasurementData:
    """角度测量数据类"""

    id: str
    slice_index: int
    point1: QPointF  # 第一条射线端点
    vertex: QPointF  # 顶点
    point3: QPointF  # 第二条射线端点
    angle_degrees: float


@dataclass(frozen=True)
class PixelSpacingInfo:
    """Pixel geometry with an explicit measurement provenance."""

    row_spacing: float
    col_spacing: float
    source: str
    measurement_calibrated: bool

    @property
    def values(self) -> tuple[float, float]:
        return self.row_spacing, self.col_spacing

    @property
    def unit(self) -> str:
        return "mm" if self.measurement_calibrated else "px"


class ImageDataModel(QObject):
    """
    Manages the data and state for a single image series.

    This class acts as a container for image data (e.g., a DICOM series),
    handling everything from pixel data to display parameters like window/level
    and ROIs. It is designed to be independent of the UI.
    """

    # Signals
    image_loaded = Signal()
    data_changed = Signal()
    pixels_changed = Signal()
    presentation_changed = Signal()
    annotations_changed = Signal()
    metadata_changed = Signal()
    slice_changed = Signal(int)
    window_level_changed = Signal(float, float)
    roi_added = Signal(BaseROI)
    measurement_added = Signal(object)  # MeasurementData
    annotation_changed = Signal()
    annotation_dirty_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # DICOM parser
        self.parser = DicomParser(self)
        self.parser.data_loaded.connect(self._on_dicom_data_loaded)

        self.pixel_array: Optional[np.ndarray] = None
        self.image_mode: str = "grayscale_volume"
        self.dicom_header: Dict[str, Any] = {}
        self.dicom_files: List[pydicom.FileDataset] = []

        # Display state
        self.current_slice_index: int = 0
        self.window_width: float = 400.0
        self.window_level: float = 40.0
        self._use_dicom_voi_lut: bool = False
        self._voi_lut_index: int = 0
        self._cache_namespace = uuid4().hex

        # ROI data
        self.rois: List[BaseROI] = []
        self.selected_indices: set[int] = set()  # 新增：多选ROI索引集合

        # Measurement data
        self.measurements: List[MeasurementData] = []
        self.selected_measurement_indices: set[int] = set()  # 选中的测量索引集合
        self.angle_measurements: List[AngleMeasurementData] = []
        self.selected_angle_measurement_ids: set[str] = set()
        self._annotations_dirty: bool = False
        self._annotation_transaction_depth = 0
        self._annotation_change_pending = False
        self._data_revision: int = 0

    def clear_all_data(self) -> None:
        """Clears all data and resets the model to its initial state."""
        self.logger.info("Clearing all image data.")
        self._data_revision += 1
        self.parser.clear()
        self.pixel_array = None
        self.image_mode = "grayscale_volume"
        self.dicom_header.clear()
        self.dicom_files.clear()
        self.current_slice_index = 0
        self.window_width = 400.0
        self.window_level = 40.0
        self._use_dicom_voi_lut = False
        self._voi_lut_index = 0
        self.rois.clear()
        self.selected_indices.clear()  # 确保清除ROI选择状态
        self.measurements.clear()  # 清除测量数据
        self.selected_measurement_indices.clear()  # 清除测量选择状态
        self.angle_measurements.clear()  # 清除角度测量数据
        self.selected_angle_measurement_ids.clear()
        self._set_annotations_dirty(False)

        self.pixels_changed.emit()
        self.metadata_changed.emit()
        self.data_changed.emit()

    def load_dicom_series(self, file_paths: List[str]) -> bool:
        """
        Loads a DICOM series by delegating to the DicomParser.

        Args:
            file_paths: List of paths to the DICOM files.

        Returns:
            The result from the parser's load_series call.
        """
        self.clear_all_data()
        return self.parser.load_series(file_paths)

    def _on_dicom_data_loaded(self) -> None:
        """
        Slot function called when the DicomParser has finished loading data.
        """
        self.logger.info("Received data from DicomParser. Populating model.")

        self.pixel_array = self.parser.get_pixel_array()
        self.image_mode = self.parser.get_image_mode()
        self.dicom_files = self.parser.get_datasets()
        self.dicom_header = self.parser.get_metadata(0)

        if self.pixel_array is None:
            self.logger.error("DicomParser finished but pixel_array is None. Aborting.")
            return

        self._set_default_window_level()
        self.current_slice_index = 0

        self.logger.info(
            f"ImageDataModel updated. Shape: {self.pixel_array.shape}, "
            f"Slices/frames: {self.get_slice_count()}"
        )
        self.metadata_changed.emit()
        self.pixels_changed.emit()
        self.image_loaded.emit()

    def load_single_image(
        self, image_data: np.ndarray, metadata: Optional[Dict] = None
    ) -> bool:
        """Loads a single non-DICOM image from a numpy array."""
        try:
            self.logger.info(
                f"Loading single image from numpy array. Shape: {image_data.shape}"
            )
            self.clear_all_data()

            if image_data.ndim == 2:
                self.image_mode = "grayscale_volume"
                self.pixel_array = image_data[np.newaxis, ...]
            elif image_data.ndim == 3 and image_data.shape[-1] in (3, 4):
                self.image_mode = "rgb_image"
                self.pixel_array = image_data[np.newaxis, ...]
            elif image_data.ndim == 3:
                self.image_mode = "grayscale_volume"
                self.pixel_array = image_data
            else:
                self.logger.error(f"Unsupported image dimension: {image_data.ndim}")
                return False

            if metadata:
                self.dicom_header.update(metadata)

            self._set_default_window_level()
            self.current_slice_index = 0

            self.logger.info("Single image loaded successfully.")
            self.image_loaded.emit()
            return True

        except Exception as e:
            self.logger.error(f"Failed to load single image: {e}", exc_info=True)
            return False

    def _set_default_window_level(self) -> None:
        """Sets the default window width and level."""
        self._use_dicom_voi_lut = False
        self._voi_lut_index = 0
        if self.image_mode.startswith("rgb"):
            self.set_window(255, 127)
            return

        try:
            strategy = get_settings_manager().get_setting(
                "display.window_level_strategy", "dicom"
            )
        except Exception:
            strategy = "dicom"

        if strategy == "fixed":
            self.set_window(400, 40)
            self.logger.info("Using fixed default W/L: W=400, L=40")
            return

        # Try to get from DICOM metadata first
        if (
            strategy == "dicom"
            and "WindowWidth" in self.dicom_header
            and "WindowCenter" in self.dicom_header
        ):
            ww = self.dicom_header.get("WindowWidth")
            wc = self.dicom_header.get("WindowCenter")
            if ww is not None and wc is not None:
                try:
                    width = float(
                        ww[0]
                        if isinstance(ww, (list, pydicom.multival.MultiValue))
                        else ww
                    )
                    level = float(
                        wc[0]
                        if isinstance(wc, (list, pydicom.multival.MultiValue))
                        else wc
                    )
                    self.logger.info(f"Set W/L from DICOM: W={width}, L={level}")
                    self.set_window(width, level)
                    return
                except (TypeError, ValueError) as e:
                    self.logger.warning(f"Could not parse W/L from DICOM header: {e}")

        if strategy == "dicom":
            dataset = self.get_dicom_file(0)
            if dataset is not None and getattr(dataset, "VOILUTSequence", None):
                self._use_dicom_voi_lut = True
                self._voi_lut_index = 0
                self.presentation_changed.emit()
                self.logger.info("Using the DICOM VOI LUT for default display.")
                return

        # Fallback to calculating from pixel data if available
        if self.pixel_array is not None and self.pixel_array.size > 0:
            valid_pixels = self._sample_valid_pixels_for_auto_window()
            if valid_pixels.size:
                p2, p98 = np.percentile(valid_pixels, (2.0, 98.0))
                width = max(1.0, float(p98 - p2))
                level = float(p2 + width / 2.0)
                self.logger.info(
                    f"Calculated W/L from pixel data: W={width}, L={level}"
                )
                self.set_window(width, level)
                return

        # Fallback to hardcoded default values
        self.set_window(400, 40)
        self.logger.info("Using hardcoded default W/L: W=400, L=40")

    def _sample_valid_pixels_for_auto_window(self) -> np.ndarray:
        """Sample a large series without materialising its complete volume."""
        if self.pixel_array is None or self.image_mode.startswith("rgb"):
            return np.empty(0, dtype=np.float32)
        frame_count = self.get_slice_count()
        if frame_count <= 0:
            return np.empty(0, dtype=np.float32)

        sample_count = min(frame_count, 32)
        frame_indices = np.unique(
            np.linspace(0, frame_count - 1, sample_count, dtype=np.int64)
        )
        samples: list[np.ndarray] = []
        for frame_index in frame_indices:
            frame = self.get_slice_data(int(frame_index))
            if frame is None:
                continue
            valid = self.get_valid_pixel_mask(int(frame_index), frame)
            values = np.asarray(frame)[valid]
            if values.size > 32768:
                stride = int(np.ceil(values.size / 32768))
                values = values[::stride]
            if values.size:
                samples.append(values.astype(np.float32, copy=False))
        return np.concatenate(samples) if samples else np.empty(0, dtype=np.float32)

    def set_window(self, width: float, level: float) -> None:
        """Set the window width and level for display."""
        try:
            width_value = float(width)
            level_value = float(level)
        except (TypeError, ValueError) as e:
            raise ValueError("Window width and level must be numeric") from e
        if not np.isfinite(width_value) or width_value < 1:
            raise ValueError("Window width must be finite and at least 1")
        if not np.isfinite(level_value):
            raise ValueError("Window level must be finite")

        width_value = max(1.0, width_value)
        voi_was_active = self._use_dicom_voi_lut
        self._use_dicom_voi_lut = False
        if (
            width_value != self.window_width
            or level_value != self.window_level
            or voi_was_active
        ):
            self.window_width = width_value
            self.window_level = level_value

            # 发射窗宽窗位变化信号
            self.window_level_changed.emit(width_value, level_value)
            self.presentation_changed.emit()
            self.data_changed.emit()

            self.logger.debug(f"Window/Level set to: {width_value}/{level_value}")

    def set_current_slice(self, slice_index: int) -> bool:
        """Sets the currently active slice index."""
        if self.pixel_array is None or not (
            0 <= slice_index < self.pixel_array.shape[0]
        ):
            return False

        if slice_index != self.current_slice_index:
            self.current_slice_index = slice_index
            self.slice_changed.emit(slice_index)
            self.pixels_changed.emit()
            self.data_changed.emit()

        return True

    def get_current_slice_data(self) -> Optional[np.ndarray]:
        """Gets the raw data for the current slice."""
        if self.pixel_array is None:
            return None
        return self.pixel_array[self.current_slice_index]

    def get_slice_count(self) -> int:
        """Returns the total number of slices."""
        if self.pixel_array is None:
            return 0
        return self.pixel_array.shape[0]

    def get_image_shape(self) -> Optional[tuple]:
        """Returns the shape of the image volume (slices, height, width)."""
        if self.pixel_array is None:
            return None
        return self.pixel_array.shape

    def get_slice_data(self, slice_index: int) -> Optional[np.ndarray]:
        """Gets the raw data for a specific slice index."""
        if self.pixel_array is None or not (0 <= slice_index < self.get_slice_count()):
            return None
        return self.pixel_array[slice_index]

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Gets a specific metadata value by key."""
        return self.dicom_header.get(key, default)

    def get_slice_metadata(self, slice_index: Optional[int] = None) -> Dict[str, Any]:
        """Return metadata for a displayed slice/frame."""
        if slice_index is None:
            slice_index = self.current_slice_index
        if self.is_dicom():
            metadata = self.parser.get_metadata(slice_index)
            if metadata:
                return metadata
        return dict(self.dicom_header)

    def get_pixel_spacing_info(
        self, slice_index: Optional[int] = None
    ) -> Optional[PixelSpacingInfo]:
        """Return spacing together with its patient/detector provenance."""
        if slice_index is None:
            slice_index = self.current_slice_index
        metadata = self.get_slice_metadata(slice_index)
        for key in ("PixelSpacing", "Pixel Spacing"):
            spacing = self._coerce_pixel_spacing(metadata.get(key))
            if spacing is not None:
                return PixelSpacingInfo(
                    *spacing,
                    source="PixelSpacing",
                    measurement_calibrated=True,
                )
        for key in ("ImagerPixelSpacing", "Imager Pixel Spacing"):
            spacing = self._coerce_pixel_spacing(metadata.get(key))
            if spacing is not None:
                return PixelSpacingInfo(
                    *spacing,
                    source="ImagerPixelSpacing",
                    measurement_calibrated=False,
                )
        return None

    def get_pixel_spacing(
        self, slice_index: Optional[int] = None
    ) -> Optional[tuple[float, float]]:
        """Return spacing for display geometry, including detector spacing."""
        info = self.get_pixel_spacing_info(slice_index)
        return info.values if info is not None else None

    def get_measurement_pixel_spacing(
        self, slice_index: Optional[int] = None
    ) -> Optional[tuple[float, float]]:
        """Return only patient-plane/calibrated spacing suitable for mm labels."""
        info = self.get_pixel_spacing_info(slice_index)
        if info is None or not info.measurement_calibrated:
            return None
        return info.values

    @staticmethod
    def _coerce_pixel_spacing(value: Any) -> Optional[tuple[float, float]]:
        try:
            if value is None or len(value) < 2:
                return None
            row_spacing = float(value[0])
            col_spacing = float(value[1])
            if (
                not np.isfinite(row_spacing)
                or not np.isfinite(col_spacing)
                or row_spacing <= 0
                or col_spacing <= 0
            ):
                return None
            return row_spacing, col_spacing
        except (TypeError, ValueError, IndexError):
            return None

    def get_pixel_aspect_ratio(self, slice_index: Optional[int] = None) -> float:
        """Return display width/height ratio without asserting measurement units."""
        spacing = self.get_pixel_spacing(slice_index)
        if spacing is not None:
            row_spacing, col_spacing = spacing
            return col_spacing / row_spacing

        metadata = self.get_slice_metadata(slice_index)
        for key in ("PixelAspectRatio", "Pixel Aspect Ratio"):
            ratio = self._coerce_pixel_spacing(metadata.get(key))
            if ratio is not None:
                vertical, horizontal = ratio
                return horizontal / vertical
        return 1.0

    def get_valid_pixel_mask(
        self,
        slice_index: Optional[int] = None,
        slice_data: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Return pixels valid for automatic windowing and quantitative ROI stats."""
        if slice_index is None:
            slice_index = self.current_slice_index
        if slice_data is None:
            slice_data = self.get_slice_data(slice_index)
        if slice_data is None:
            return np.zeros((0, 0), dtype=bool)

        data = np.asarray(slice_data)
        if data.ndim > 2:
            return np.all(np.isfinite(data), axis=-1)
        valid = np.isfinite(data)
        metadata = self.get_slice_metadata(slice_index)
        padding = metadata.get("PixelPaddingValue", metadata.get("Pixel Padding Value"))
        if padding is None:
            return valid
        range_limit = metadata.get(
            "PixelPaddingRangeLimit",
            metadata.get("Pixel Padding Range Limit", padding),
        )
        try:
            transformed = self._transform_stored_values(
                [float(padding), float(range_limit)], slice_index
            )
            low, high = sorted(float(value) for value in transformed)
            valid &= ~((data >= low) & (data <= high))
        except (TypeError, ValueError, IndexError):
            self.logger.warning("Ignoring invalid Pixel Padding values")
        return valid

    def _transform_stored_values(
        self, values: list[float], slice_index: int
    ) -> np.ndarray:
        dataset = self.get_dicom_file(slice_index)
        if dataset is not None and getattr(dataset, "ModalityLUTSequence", None):
            try:
                return np.asarray(
                    apply_modality_lut(np.asarray(values, dtype=np.int64), dataset),
                    dtype=np.float64,
                )
            except Exception:
                pass
        metadata = self.get_slice_metadata(slice_index)
        slope = float(metadata.get("RescaleSlope", 1.0) or 1.0)
        intercept = float(metadata.get("RescaleIntercept", 0.0) or 0.0)
        return np.asarray(values, dtype=np.float64) * slope + intercept

    @staticmethod
    def _as_value_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, pydicom.multival.MultiValue)):
            return list(value)
        return [value]

    def get_dicom_voi_options(self, slice_index: Optional[int] = None) -> list[dict]:
        """Expose all DICOM window pairs and VOI LUT choices for the UI."""
        if slice_index is None:
            slice_index = self.current_slice_index
        metadata = self.get_slice_metadata(slice_index)
        centers = self._as_value_list(metadata.get("WindowCenter"))
        widths = self._as_value_list(metadata.get("WindowWidth"))
        explanations = self._as_value_list(metadata.get("WindowCenterWidthExplanation"))
        options: list[dict] = []
        for index, (center, width) in enumerate(zip(centers, widths)):
            try:
                center_value = float(center)
                width_value = float(width)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(width_value) or width_value < 1:
                continue
            label = (
                str(explanations[index])
                if index < len(explanations) and explanations[index]
                else f"DICOM W{width_value:g}/L{center_value:g}"
            )
            options.append(
                {
                    "kind": "window",
                    "index": index,
                    "label": label,
                    "width": width_value,
                    "center": center_value,
                }
            )
        dataset = self.get_dicom_file(slice_index)
        for index, item in enumerate(getattr(dataset, "VOILUTSequence", []) or []):
            explanation = getattr(item, "LUTExplanation", None)
            options.append(
                {
                    "kind": "lut",
                    "index": index,
                    "label": str(explanation or f"DICOM VOI LUT {index + 1}"),
                }
            )
        return options

    def activate_dicom_voi_option(self, option: dict) -> bool:
        kind = option.get("kind")
        if kind == "window":
            self.set_window(float(option["width"]), float(option["center"]))
            return True
        if kind == "lut":
            dataset = self.get_dicom_file(self.current_slice_index)
            sequence = getattr(dataset, "VOILUTSequence", None)
            index = int(option.get("index", 0))
            if not sequence or not 0 <= index < len(sequence):
                return False
            self._voi_lut_index = index
            self._use_dicom_voi_lut = True
            self.presentation_changed.emit()
            self.data_changed.emit()
            return True
        return False

    def get_frame_interval_ms(
        self, slice_index: Optional[int] = None
    ) -> Optional[float]:
        metadata = self.get_slice_metadata(slice_index)
        vector = self._as_value_list(metadata.get("FrameTimeVector"))
        if vector:
            index = (
                self.current_slice_index if slice_index is None else int(slice_index)
            )
            try:
                value = float(vector[min(index, len(vector) - 1)])
                if np.isfinite(value) and value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        for key in ("FrameTime",):
            try:
                value = float(metadata.get(key))
                if np.isfinite(value) and value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        for key in ("RecommendedDisplayFrameRate", "CineRate"):
            try:
                rate = float(metadata.get(key))
                if np.isfinite(rate) and rate > 0:
                    return 1000.0 / rate
            except (TypeError, ValueError):
                pass
        return None

    def get_lossy_compression_info(
        self, slice_index: Optional[int] = None
    ) -> Optional[dict[str, str]]:
        metadata = self.get_slice_metadata(slice_index)
        flag = str(metadata.get("LossyImageCompression", "00")).strip().upper()
        if flag not in {"01", "1", "YES", "TRUE"}:
            return None
        return {
            "ratio": str(metadata.get("LossyImageCompressionRatio", "")),
            "method": str(metadata.get("LossyImageCompressionMethod", "")),
        }

    def get_dicom_header(self) -> Dict[str, Any]:
        """Returns the entire DICOM header dictionary."""
        return self.dicom_header

    def add_roi(self, roi: BaseROI) -> None:
        """Adds an ROI to the model."""
        self.rois.append(roi)
        self.roi_added.emit(roi)
        self.data_changed.emit()
        self._mark_annotations_changed()

    def _set_annotations_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty != self._annotations_dirty:
            self._annotations_dirty = dirty
            self.annotation_dirty_changed.emit(dirty)

    def _mark_annotations_changed(self) -> None:
        if self._annotation_transaction_depth > 0:
            self._annotation_change_pending = True
            return
        self._set_annotations_dirty(True)
        self.annotation_changed.emit()
        self.annotations_changed.emit()

    @contextmanager
    def annotation_transaction(self):
        """把一次用户操作中的多类标注变更合并为一个撤销快照。"""
        self._annotation_transaction_depth += 1
        try:
            yield
        finally:
            self._annotation_transaction_depth -= 1
            if (
                self._annotation_transaction_depth == 0
                and self._annotation_change_pending
            ):
                self._annotation_change_pending = False
                self._set_annotations_dirty(True)
                self.annotation_changed.emit()
                self.annotations_changed.emit()

    def mark_annotations_dirty(self) -> None:
        """Mark direct ROI/measurement edits as unsaved."""
        self._mark_annotations_changed()

    def mark_annotations_saved(self) -> None:
        """Clear dirty state after a successful annotation export."""
        self._set_annotations_dirty(False)

    def has_unsaved_annotations(self) -> bool:
        return self._annotations_dirty

    def is_dicom(self) -> bool:
        """Checks if the current data is from a DICOM series."""
        return bool(self.dicom_files)

    def apply_window_level(
        self,
        slice_data: np.ndarray,
        slice_index: Optional[int] = None,
    ) -> np.ndarray:
        """Apply DICOM PS3.3 VOI windowing to modality-rescaled pixels."""
        try:
            width = float(self.window_width)
            center = float(self.window_level)
            if not np.isfinite(width) or width < 1 or not np.isfinite(center):
                raise ValueError("Invalid window width/level")

            data = np.asarray(slice_data, dtype=np.float32)
            metadata = self.get_slice_metadata(slice_index)
            voi_function = str(metadata.get("VOILUTFunction", "LINEAR")).upper()

            dataset = self.get_dicom_file(
                self.current_slice_index if slice_index is None else slice_index
            )
            if (
                self._use_dicom_voi_lut
                and dataset is not None
                and getattr(dataset, "VOILUTSequence", None)
            ):
                normalized_data = self._apply_dicom_voi_lut(data, dataset)
            elif voi_function == "SIGMOID":
                exponent = np.clip(-4.0 * (data - center) / width, -700.0, 700.0)
                normalized = 255.0 / (1.0 + np.exp(exponent))
            elif voi_function == "LINEAR_EXACT":
                lower = center - width / 2.0
                normalized = (data - lower) / width * 255.0
            else:
                # DICOM LINEAR uses the half-unit offset and a width-1 span.
                if width == 1:
                    normalized = np.where(data <= center - 0.5, 0.0, 255.0)
                else:
                    lower = center - 0.5 - (width - 1.0) / 2.0
                    normalized = ((data - (center - 0.5)) / (width - 1.0) + 0.5) * 255.0
                    normalized = np.where(data <= lower, 0.0, normalized)
                    normalized = np.where(
                        data > center - 0.5 + (width - 1.0) / 2.0,
                        255.0,
                        normalized,
                    )

            if not (
                self._use_dicom_voi_lut
                and dataset is not None
                and getattr(dataset, "VOILUTSequence", None)
            ):
                normalized_data = np.nan_to_num(
                    normalized, nan=0.0, posinf=255.0, neginf=0.0
                )
                normalized_data = np.clip(normalized_data, 0.0, 255.0).astype(np.uint8)

            presentation_shape = str(
                metadata.get("PresentationLUTShape", "IDENTITY")
            ).upper()
            invert_output = self._is_monochrome1(slice_index)
            if presentation_shape == "INVERSE":
                invert_output = not invert_output
            if invert_output:
                normalized_data = 255 - normalized_data

            return normalized_data
        except Exception as e:
            self.logger.error(f"Failed to apply window/level: {e}")
            return np.zeros_like(slice_data, dtype=np.uint8)

    def _apply_dicom_voi_lut(
        self,
        modality_data: np.ndarray,
        dataset: pydicom.dataset.Dataset,
    ) -> np.ndarray:
        """Apply a DICOM VOI LUT for display without altering stored pixels."""
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Applying a VOI LUT on a float input array may give incorrect results",
                category=UserWarning,
            )
            voi_data = np.asarray(
                apply_voi_lut(
                    modality_data,
                    dataset,
                    index=self._voi_lut_index,
                    prefer_lut=True,
                ),
                dtype=np.float64,
            )
        descriptor = dataset.VOILUTSequence[self._voi_lut_index].LUTDescriptor
        bits = int(descriptor[2]) if len(descriptor) >= 3 else 8
        maximum = float((1 << max(1, bits)) - 1)
        normalized = np.nan_to_num(
            voi_data / maximum * 255.0,
            nan=0.0,
            posinf=255.0,
            neginf=0.0,
        )
        return np.clip(normalized, 0.0, 255.0).astype(np.uint8)

    def get_pixel_value(self, x: int, y: int) -> Optional[Any]:
        """Gets the raw pixel value at a specific coordinate for the current slice."""
        slice_data = self.get_current_slice_data()
        if (
            slice_data is not None
            and 0 <= y < slice_data.shape[0]
            and 0 <= x < slice_data.shape[1]
        ):
            value = slice_data[y, x]
            if np.isscalar(value):
                return float(value)
            channels = np.asarray(value).reshape(-1)
            if channels.size in (3, 4) and np.issubdtype(channels.dtype, np.number):
                return tuple(float(channel) for channel in channels)
        return None

    def get_dicom_file(self, slice_index: int) -> Optional[pydicom.FileDataset]:
        """Gets the pydicom dataset for a specific slice index."""
        if self.dicom_files and 0 <= slice_index < len(self.dicom_files):
            return self.dicom_files[slice_index]
        return None

    def get_series_description(self) -> str:
        """Constructs a description string for the loaded series."""
        if not self.has_image():
            return "N/A"

        if self.is_dicom():
            return self.get_metadata("SeriesDescription", "DICOM Series")

        return "Image"

    def get_display_slice(
        self, slice_index: Optional[int] = None
    ) -> Optional[np.ndarray]:
        """
        Gets slice data, applies window/level, and returns it for display.
        Uses PerformanceManager cache to avoid redundant window/level computations.

        Args:
            slice_index: The index of the slice to get. If None, uses the current slice.

        Returns:
            A 2D numpy array of uint8, ready for QImage conversion.
        """
        if slice_index is None:
            slice_index = self.current_slice_index

        slice_data = self.get_slice_data(slice_index)
        if slice_data is None:
            return None

        if self.image_mode.startswith("rgb"):
            return self._as_uint8_rgb(slice_data)

        # 构建缓存键：模型ID + 切片索引 + 窗宽窗位
        metadata = self.get_slice_metadata(slice_index)
        voi_function = str(metadata.get("VOILUTFunction", "LINEAR")).upper()
        presentation_shape = str(
            metadata.get("PresentationLUTShape", "IDENTITY")
        ).upper()
        cache_key = (
            f"display_{self._cache_namespace}_{self._data_revision}_{self.image_mode}_"
            f"{slice_index}_{self.window_width}_{self.window_level}_"
            f"{voi_function}_{presentation_shape}_{self._use_dicom_voi_lut}_"
            f"{self._voi_lut_index}_"
            f"{self._is_monochrome1(slice_index)}"
        )

        try:
            perf = get_performance_manager()
            cached = perf.get_from_cache(cache_key)
            if cached is not None:
                return cached
        except Exception:
            pass  # 缓存不可用时回退到直接计算

        result = self.apply_window_level(slice_data, slice_index)

        try:
            perf = get_performance_manager()
            perf.add_to_cache(cache_key, result)
        except Exception:
            pass

        return result

    def _as_uint8_rgb(self, slice_data: np.ndarray) -> np.ndarray:
        """Return an RGB/RGBA slice as uint8 display data."""
        if slice_data.dtype == np.uint8:
            return slice_data

        data = slice_data.astype(np.float32)
        if data.size == 0:
            return data.astype(np.uint8)

        min_val = float(np.nanmin(data))
        max_val = float(np.nanmax(data))
        if max_val > min_val:
            data = (data - min_val) / (max_val - min_val) * 255.0
        else:
            data = np.zeros_like(data)
        return np.clip(data, 0, 255).astype(np.uint8)

    def _is_monochrome1(self, slice_index: Optional[int] = None) -> bool:
        metadata = self.get_slice_metadata(slice_index)
        photometric = metadata.get("PhotometricInterpretation")
        if photometric is None:
            photometric = metadata.get("Photometric Interpretation")
        return str(photometric).upper() == "MONOCHROME1"

    def has_image(self) -> bool:
        """Check if any image data is loaded."""
        return self.pixel_array is not None

    def get_roi_by_id(self, roi_id: str) -> Optional[BaseROI]:
        """Finds and returns an ROI by its unique ID."""
        for roi in self.rois:
            if roi.id == roi_id:
                return roi
        return None

    def select_roi(self, roi_id: str, multi: bool = False) -> None:
        """
        Selects an ROI by its unique ID.
        Args:
            roi_id: The unique ID of the ROI to select.
            multi: If True, adds to the current selection (multi-select).
        """
        roi_to_select = self.get_roi_by_id(roi_id)
        if not roi_to_select:
            return

        if not multi:
            self.clear_selection()

        # We store indices in selected_indices, so we need to find it
        try:
            idx = self.rois.index(roi_to_select)
            self.selected_indices.add(idx)
            roi_to_select.selected = True
            self.data_changed.emit()
        except ValueError:
            self.logger.warning(f"ROI with id {roi_id} found but not in list?")

    def deselect_roi(self, roi_id: str) -> None:
        """Deselects an ROI by its unique ID."""
        roi_to_deselect = self.get_roi_by_id(roi_id)
        if not roi_to_deselect:
            return

        try:
            idx = self.rois.index(roi_to_deselect)
            if idx in self.selected_indices:
                self.selected_indices.remove(idx)
                roi_to_deselect.selected = False
                self.data_changed.emit()
        except ValueError:
            pass

    def clear_selection(self) -> None:
        """Clears the current ROI selection."""
        for idx in list(self.selected_indices):  # Iterate over a copy
            if 0 <= idx < len(self.rois):
                self.rois[idx].selected = False
        self.selected_indices.clear()
        self.data_changed.emit()

    def clear_annotation_selection(self) -> None:
        """一次清除 ROI、距离和角度选择，并只触发一次视图刷新。"""
        had_selection = bool(
            self.selected_indices
            or self.selected_measurement_indices
            or self.selected_angle_measurement_ids
        )
        for idx in list(self.selected_indices):
            if 0 <= idx < len(self.rois):
                self.rois[idx].selected = False
        self.selected_indices.clear()
        self.selected_measurement_indices.clear()
        self.selected_angle_measurement_ids.clear()
        if had_selection:
            self.data_changed.emit()

    def delete_selected_rois(self) -> List[str]:
        """
        Deletes all currently selected ROIs from the model.
        Returns:
            A list of the deleted ROI IDs.
        """
        deleted_roi_ids = []
        # Sort indices in reverse to avoid index shifting issues during deletion
        indices_to_delete = sorted(list(self.selected_indices), reverse=True)

        for idx in indices_to_delete:
            if 0 <= idx < len(self.rois):
                deleted_roi = self.rois.pop(idx)
                deleted_roi_ids.append(deleted_roi.id)

        self.clear_selection()  # This also emits data_changed
        if deleted_roi_ids:
            self._mark_annotations_changed()
        return deleted_roi_ids

    def get_active_roi(self) -> Optional[BaseROI]:
        """
        Gets the 'active' ROI, defined as the most recently selected one.
        This is useful for displaying context-sensitive information like stats.
        """
        if self.selected_indices:
            # Return the last added index. A more sophisticated model might
            # use a dedicated "active_roi_index" attribute.
            last_selected_index = list(self.selected_indices)[-1]
            if 0 <= last_selected_index < len(self.rois):
                return self.rois[last_selected_index]
        return None

    def clear_all_rois(self) -> None:
        """清除所有ROI数据"""
        self.logger.debug("清除所有ROI数据")
        had_rois = bool(self.rois)
        self.rois.clear()
        self.selected_indices.clear()
        self.data_changed.emit()
        if had_rois:
            self._mark_annotations_changed()

    def _sort_dicom_slices(
        self, dicom_datasets: List[pydicom.FileDataset]
    ) -> List[pydicom.FileDataset]:
        """Compatibility wrapper around the canonical parser sort."""
        return self.parser._sort_dicom_slices(dicom_datasets)

    def _extract_pixel_data(self) -> bool:
        """Compatibility wrapper around the canonical parser extraction."""
        sources = self.parser.get_source_datasets() or self.dicom_files
        pixels = self.parser._extract_pixel_data(sources)
        if pixels is None:
            return False
        self.pixel_array = pixels
        self.dicom_files = self.parser.get_datasets()
        return True

    def _extract_metadata(self) -> None:
        """从DICOM文件头提取元数据"""
        if not self.dicom_files:
            return

        try:
            # 使用第一张切片作为代表
            ds = self.dicom_files[0]
            self.dicom_header = {}

            # 遍历所有数据元并存入字典
            for elem in ds:
                # 将pydicom的特殊数值类型转为Python原生类型
                value = elem.value
                if isinstance(value, pydicom.multival.MultiValue):
                    # 对人类可读的名字(PersonName)做特殊处理
                    if elem.VR == "PN":
                        self.dicom_header[elem.name] = str(value)
                    else:
                        self.dicom_header[elem.name] = [item for item in value]
                elif isinstance(
                    value, (pydicom.dataelem.DataElement, pydicom.dataset.Dataset)
                ):
                    self.dicom_header[elem.name] = str(value)
                else:
                    self.dicom_header[elem.name] = value

            # 确保关键信息存在
            if "WindowCenter" not in self.dicom_header:
                self.dicom_header["WindowCenter"] = self.window_level
            if "WindowWidth" not in self.dicom_header:
                self.dicom_header["WindowWidth"] = self.window_width
            self.dicom_header["Number of Slices"] = len(self.dicom_files)

        except Exception as e:
            self.logger.error(f"提取元数据失败: {e}")

    def _update_dicom_header_with_wl(self) -> None:
        """Helper to update DICOM header with current W/L values."""
        if not self.dicom_header:
            return
        # Use standard DICOM keywords
        if "WindowWidth" not in self.dicom_header:
            self.dicom_header["WindowWidth"] = self.window_width
        if "WindowCenter" not in self.dicom_header:
            self.dicom_header["WindowCenter"] = self.window_level

    # 测量数据管理方法
    def add_measurement(self, measurement: MeasurementData) -> None:
        """添加测量数据到模型"""
        self.measurements.append(measurement)
        self.measurement_added.emit(measurement)
        self.data_changed.emit()
        self._mark_annotations_changed()

    def remove_measurement(self, measurement_id: str) -> bool:
        """根据ID移除测量数据"""
        for i, measurement in enumerate(self.measurements):
            if measurement.id == measurement_id:
                self.measurements.pop(i)
                # 更新选中索引
                if i in self.selected_measurement_indices:
                    self.selected_measurement_indices.remove(i)
                # 调整其他选中索引
                new_selected = set()
                for idx in self.selected_measurement_indices:
                    if idx > i:
                        new_selected.add(idx - 1)
                    elif idx < i:
                        new_selected.add(idx)
                self.selected_measurement_indices = new_selected
                self.data_changed.emit()
                self._mark_annotations_changed()
                return True
        return False

    def get_measurement_by_id(self, measurement_id: str) -> Optional[MeasurementData]:
        """根据ID获取测量数据"""
        for measurement in self.measurements:
            if measurement.id == measurement_id:
                return measurement
        return None

    def select_measurement(self, index: int) -> bool:
        """选中指定索引的测量"""
        if 0 <= index < len(self.measurements):
            self.selected_measurement_indices.add(index)
            self.data_changed.emit()
            return True
        return False

    def deselect_measurement(self, index: int) -> bool:
        """取消选中指定索引的测量"""
        if index in self.selected_measurement_indices:
            self.selected_measurement_indices.remove(index)
            self.data_changed.emit()
            return True
        return False

    def clear_measurement_selection(self) -> None:
        """清除所有测量选择状态"""
        if self.selected_measurement_indices:
            self.selected_measurement_indices.clear()
            self.data_changed.emit()

    def delete_selected_measurements(self) -> List[str]:
        """删除所有选中的测量数据"""
        deleted_measurement_ids = []
        # 按索引逆序删除，避免索引偏移问题
        indices_to_delete = sorted(
            list(self.selected_measurement_indices), reverse=True
        )

        for idx in indices_to_delete:
            if 0 <= idx < len(self.measurements):
                deleted_measurement = self.measurements.pop(idx)
                deleted_measurement_ids.append(deleted_measurement.id)

        self.clear_measurement_selection()  # 这也会发出data_changed信号
        if deleted_measurement_ids:
            self._mark_annotations_changed()
        return deleted_measurement_ids

    def get_measurements_for_slice(self, slice_index: int) -> List[MeasurementData]:
        """获取指定切片的所有测量数据"""
        return [m for m in self.measurements if m.slice_index == slice_index]

    def clear_all_measurements(self) -> None:
        """清除所有测量数据"""
        had_measurements = bool(self.measurements or self.angle_measurements)
        self.measurements.clear()
        self.selected_measurement_indices.clear()
        self.angle_measurements.clear()
        self.selected_angle_measurement_ids.clear()
        self.data_changed.emit()
        if had_measurements:
            self._mark_annotations_changed()

    def add_angle_measurement(self, data: AngleMeasurementData) -> None:
        """添加角度测量数据"""
        self.angle_measurements.append(data)
        self.data_changed.emit()
        self._mark_annotations_changed()

    def get_angle_measurements_for_slice(
        self, slice_index: int
    ) -> List[AngleMeasurementData]:
        """获取指定切片的所有角度测量数据"""
        return [m for m in self.angle_measurements if m.slice_index == slice_index]

    def get_angle_measurement_by_id(
        self, measurement_id: str
    ) -> Optional[AngleMeasurementData]:
        return next(
            (m for m in self.angle_measurements if m.id == measurement_id),
            None,
        )

    def select_angle_measurement(
        self, measurement_id: str, multi: bool = False
    ) -> bool:
        if self.get_angle_measurement_by_id(measurement_id) is None:
            return False
        if not multi:
            self.selected_angle_measurement_ids.clear()
        self.selected_angle_measurement_ids.add(measurement_id)
        self.data_changed.emit()
        return True

    def deselect_angle_measurement(self, measurement_id: str) -> bool:
        if measurement_id not in self.selected_angle_measurement_ids:
            return False
        self.selected_angle_measurement_ids.remove(measurement_id)
        self.data_changed.emit()
        return True

    def clear_angle_measurement_selection(self) -> None:
        if self.selected_angle_measurement_ids:
            self.selected_angle_measurement_ids.clear()
            self.data_changed.emit()

    def remove_angle_measurement(self, measurement_id: str) -> bool:
        for index, measurement in enumerate(self.angle_measurements):
            if measurement.id == measurement_id:
                self.angle_measurements.pop(index)
                self.selected_angle_measurement_ids.discard(measurement_id)
                self.data_changed.emit()
                self._mark_annotations_changed()
                return True
        return False

    def delete_selected_angle_measurements(self) -> List[str]:
        selected = set(self.selected_angle_measurement_ids)
        if not selected:
            return []
        deleted = [
            measurement.id
            for measurement in self.angle_measurements
            if measurement.id in selected
        ]
        self.angle_measurements[:] = [
            measurement
            for measurement in self.angle_measurements
            if measurement.id not in selected
        ]
        self.selected_angle_measurement_ids.clear()
        if deleted:
            self.data_changed.emit()
            self._mark_annotations_changed()
        return deleted
