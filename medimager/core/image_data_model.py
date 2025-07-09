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
import pydicom
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from PySide6.QtCore import QObject, Signal, QRect

from medimager.utils.logger import get_logger
from medimager.core.dicom_parser import DicomParser
from medimager.core.roi import BaseROI


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
    slice_changed = Signal(int)
    window_level_changed = Signal(int, int)
    roi_added = Signal(BaseROI)
    
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.logger = get_logger(__name__)
        
        # DICOM parser
        self.parser = DicomParser(self)
        self.parser.data_loaded.connect(self._on_dicom_data_loaded)
        
        self.pixel_array: Optional[np.ndarray] = None
        self.dicom_header: Dict[str, Any] = {}
        self.dicom_files: List[pydicom.FileDataset] = []
        
        # Display state
        self.current_slice_index: int = 0
        self.window_width: int = 400
        self.window_level: int = 40
        
        # ROI data
        self.rois: List[BaseROI] = []
        self.selected_indices: set[int] = set()  # 新增：多选ROI索引集合
        
    def clear_all_data(self) -> None:
        """Clears all data and resets the model to its initial state."""
        self.logger.info("Clearing all image data.")
        self.pixel_array = None
        self.dicom_header.clear()
        self.dicom_files.clear()
        self.current_slice_index = 0
        self.window_width = 400
        self.window_level = 40
        self.rois.clear()
        
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
        self.dicom_files = self.parser.get_datasets()
        self.dicom_header = self.parser.get_metadata()
        
        if self.pixel_array is None:
            self.logger.error("DicomParser finished but pixel_array is None. Aborting.")
            return

        self._set_default_window_level()
        self.current_slice_index = 0
            
        self.logger.info(f"ImageDataModel updated. Shape: {self.pixel_array.shape}, Slices: {len(self.dicom_files)}")
        self.image_loaded.emit()
            
    def load_single_image(self, image_data: np.ndarray, metadata: Optional[Dict] = None) -> bool:
        """Loads a single non-DICOM image from a numpy array."""
        try:
            self.logger.info(f"Loading single image from numpy array. Shape: {image_data.shape}")
            self.clear_all_data()
            
            if image_data.ndim == 2:
                self.pixel_array = image_data[np.newaxis, ...]
            elif image_data.ndim == 3:
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
        # Try to get from DICOM metadata first
        if "WindowWidth" in self.dicom_header and "WindowCenter" in self.dicom_header:
            ww = self.dicom_header.get("WindowWidth")
            wc = self.dicom_header.get("WindowCenter")
            if ww is not None and wc is not None:
                try:
                    # DICOM standard allows multiple values, we take the first.
                    width = int(ww[0] if isinstance(ww, (list, pydicom.multival.MultiValue)) else ww)
                    level = int(wc[0] if isinstance(wc, (list, pydicom.multival.MultiValue)) else wc)
                    self.logger.info(f"Set W/L from DICOM: W={width}, L={level}")
                    self.set_window(width, level)
                    return
                except (TypeError, ValueError) as e:
                    self.logger.warning(f"Could not parse W/L from DICOM header: {e}")

        # Fallback to calculating from pixel data if available
        if self.pixel_array is not None and self.pixel_array.size > 0:
            # 使用2%到98%的像素值范围来计算一个合理的默认窗位
            p2 = np.percentile(self.pixel_array, 2)
            p98 = np.percentile(self.pixel_array, 98)
            width = int(p98 - p2)
            level = int(p2 + width / 2)
            self.logger.info(f"Calculated W/L from pixel data: W={width}, L={level}")
            self.set_window(width, level)
            return

        # Fallback to hardcoded default values
        self.set_window(400, 40)
        self.logger.info("Using hardcoded default W/L: W=400, L=40")

    def set_window(self, width: int, level: int) -> None:
        """Sets the window width and level."""
        if width <= 0:
            self.logger.warning(f"Window width must be > 0, got {width}")
            return
            
        self.window_width = width
        self.window_level = level
        self.window_level_changed.emit(width, level)
        self.data_changed.emit()
        
    def set_current_slice(self, slice_index: int) -> bool:
        """Sets the currently active slice index."""
        if self.pixel_array is None or not (0 <= slice_index < self.pixel_array.shape[0]):
            return False
            
        if slice_index != self.current_slice_index:
            self.current_slice_index = slice_index
            self.slice_changed.emit(slice_index)
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
        
    def get_dicom_header(self) -> Dict[str, Any]:
        """Returns the entire DICOM header dictionary."""
        return self.dicom_header

    def add_roi(self, roi: BaseROI) -> None:
        """Adds an ROI to the model."""
        self.rois.append(roi)
        self.roi_added.emit(roi)
        self.data_changed.emit()

    def is_dicom(self) -> bool:
        """Checks if the current data is from a DICOM series."""
        return bool(self.dicom_files)

    def apply_window_level(self, slice_data: np.ndarray) -> np.ndarray:
        """Applies the current window/level to slice data for display."""
        try:
            min_val = self.window_level - self.window_width / 2
            max_val = self.window_level + self.window_width / 2
            
            windowed_data = np.clip(slice_data, min_val, max_val)
            
            if max_val > min_val:
                normalized_data = ((windowed_data - min_val) / (max_val - min_val) * 255).astype(np.uint8)
            else:
                normalized_data = np.zeros_like(windowed_data, dtype=np.uint8)
                
            return normalized_data
        except Exception as e:
            self.logger.error(f"Failed to apply window/level: {e}")
            return np.zeros_like(slice_data, dtype=np.uint8)

    def get_pixel_value(self, x: int, y: int) -> Optional[float]:
        """Gets the raw pixel value at a specific coordinate for the current slice."""
        slice_data = self.get_current_slice_data()
        if slice_data is not None and 0 <= y < slice_data.shape[0] and 0 <= x < slice_data.shape[1]:
            return float(slice_data[y, x])
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

    def get_display_slice(self, slice_index: Optional[int] = None) -> Optional[np.ndarray]:
        """
        Gets slice data, applies window/level, and returns it for display.
        
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
            
        return self.apply_window_level(slice_data)

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
        for idx in list(self.selected_indices): # Iterate over a copy
            if 0 <= idx < len(self.rois):
                self.rois[idx].selected = False
        self.selected_indices.clear()
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
        
        self.clear_selection() # This also emits data_changed
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

    def _sort_dicom_slices(self, dicom_datasets: List[pydicom.FileDataset]) -> List[pydicom.FileDataset]:
        """按切片位置排序DICOM数据
        
        Args:
            dicom_datasets: DICOM数据集列表
            
        Returns:
            List[pydicom.FileDataset]: 排序后的数据集列表
        """
        try:
            # 尝试按ImagePositionPatient的Z坐标排序
            if all(hasattr(ds, 'ImagePositionPatient') and ds.ImagePositionPatient for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: float(ds.ImagePositionPatient[2]))
                self.logger.debug("按ImagePositionPatient排序")
            # 尝试按SliceLocation排序
            elif all(hasattr(ds, 'SliceLocation') and ds.SliceLocation is not None for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: float(ds.SliceLocation))
                self.logger.debug("按SliceLocation排序")
            # 尝试按InstanceNumber排序
            elif all(hasattr(ds, 'InstanceNumber') and ds.InstanceNumber for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: int(ds.InstanceNumber))
                self.logger.debug("按InstanceNumber排序")
            else:
                self.logger.warning("无法确定切片排序方式，保持原始顺序")
                
        except Exception as e:
            self.logger.warning(f"切片排序失败，保持原始顺序: {e}")
            
        return dicom_datasets
        
    def _extract_pixel_data(self) -> bool:
        """提取像素数据
        
        Returns:
            bool: 是否成功提取
        """
        try:
            pixel_arrays = []
            
            for i, ds in enumerate(self.dicom_files):
                try:
                    # 获取像素数组
                    pixel_array = ds.pixel_array.astype(np.float32)
                    
                    # 应用斜率和截距
                    if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
                        slope = float(ds.RescaleSlope)
                        intercept = float(ds.RescaleIntercept)
                        pixel_array = pixel_array * slope + intercept
                        
                    pixel_arrays.append(pixel_array)
                    
                except Exception as e:
                    self.logger.error(f"提取第{i}张切片像素数据失败: {e}")
                    return False
                    
            if not pixel_arrays:
                self.logger.error("没有成功提取任何像素数据")
                return False
                
            # 堆叠成3D数组
            self.pixel_array = np.stack(pixel_arrays, axis=0)
            
            self.logger.info(f"像素数据提取完成，形状: {self.pixel_array.shape}")
            return True
            
        except Exception as e:
            self.logger.error(f"提取像素数据失败: {e}")
            return False
            
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
                    if elem.VR == 'PN':
                        self.dicom_header[elem.name] = str(value)
                    else:
                        self.dicom_header[elem.name] = [item for item in value]
                elif isinstance(value, (pydicom.dataelem.DataElement, pydicom.dataset.Dataset)):
                    self.dicom_header[elem.name] = str(value)
                else:
                    self.dicom_header[elem.name] = value

            # 确保关键信息存在
            if 'WindowCenter' not in self.dicom_header:
                self.dicom_header['WindowCenter'] = self.window_level
            if 'WindowWidth' not in self.dicom_header:
                self.dicom_header['WindowWidth'] = self.window_width
            self.dicom_header['Number of Slices'] = len(self.dicom_files)
            
        except Exception as e:
            self.logger.error(f"提取元数据失败: {e}")

    def _update_dicom_header_with_wl(self) -> None:
        """Helper to update DICOM header with current W/L values."""
        if not self.dicom_header:
            return
        # Use standard DICOM keywords
        if 'WindowWidth' not in self.dicom_header:
            self.dicom_header['WindowWidth'] = self.window_width
        if 'WindowCenter' not in self.dicom_header:
            self.dicom_header['WindowCenter'] = self.window_level 