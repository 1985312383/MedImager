# 使用 pydicom 处理 DICOM 文件的加载和解析 
from typing import List, Optional, Dict, Any
import os
import pydicom
import numpy as np
from PySide6.QtCore import QObject, Signal, QObject
from medimager.utils.logger import get_logger

class DicomParser(QObject):
    """
    Handles the loading and parsing of DICOM files.

    This class is responsible for reading DICOM files from disk, sorting them
    into the correct slice order, extracting pixel data (including applying
    rescale slope/intercept), and providing access to the data and metadata.

    It operates independently of the main application's data model and emits
    a signal when data has been successfully loaded.
    """
    
    data_loaded = Signal()
    
    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化 DicomParser"""
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self._datasets: List[pydicom.FileDataset] = []
        self._pixel_array: Optional[np.ndarray] = None
        
    def load_file(self, file_path: str) -> bool:
        """加载单个 DICOM 文件
        
        Args:
            file_path: DICOM 文件的路径
            
        Returns:
            bool: 加载是否成功
        """
        try:
            self._dataset = pydicom.dcmread(file_path)
            self._pixel_array = self._dataset.pixel_array
            self.data_loaded.emit()
            return True
        except Exception as e:
            print(f"加载 DICOM 文件失败: {str(e)}")
            return False
            
    def load_series(self, file_paths: List[str]) -> bool:
        """
        Loads a series of DICOM files from a list of paths.

        Args:
            file_paths: A list of strings, where each string is a path to a
                        .dcm file.

        Returns:
            True if the series was loaded successfully, False otherwise.
        """
        self.logger.info(f"Attempting to load {len(file_paths)} DICOM files.")
        try:
            # 1. Load datasets from paths
            datasets = []
            for file_path in file_paths:
                try:
                    ds = pydicom.dcmread(file_path)
                    datasets.append(ds)
                except Exception as e:
                    self.logger.warning(f"Could not read {file_path}: {e}")
                    continue
            
            if not datasets:
                self.logger.error("No valid DICOM files could be read.")
                return False

            # 2. Sort the datasets into slice order
            self._datasets = self._sort_dicom_slices(datasets)

            # 3. Extract pixel data into a 3D numpy array
            pixel_data = self._extract_pixel_data(self._datasets)

            if pixel_data is None:
                self.logger.error("Failed to extract pixel data from the series.")
                return False
            self._pixel_array = pixel_data

            self.logger.info(f"Successfully loaded and parsed DICOM series. Shape: {self._pixel_array.shape}")
            self.data_loaded.emit()
            return True
            
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during DICOM series loading: {e}", exc_info=True)
            self._datasets = []
            self._pixel_array = None
            return False

    def _sort_dicom_slices(self, dicom_datasets: List[pydicom.FileDataset]) -> List[pydicom.FileDataset]:
        """Sorts a list of pydicom datasets based on slice position."""
        try:
            # Try to sort by ImagePositionPatient Z coordinate
            if all(hasattr(ds, 'ImagePositionPatient') and ds.ImagePositionPatient for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: float(ds.ImagePositionPatient[2]))
                self.logger.debug("Sorted slices by ImagePositionPatient (Z-axis).")
            # Fallback to SliceLocation
            elif all(hasattr(ds, 'SliceLocation') and ds.SliceLocation is not None for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: float(ds.SliceLocation))
                self.logger.debug("Sorted slices by SliceLocation.")
            # Fallback to InstanceNumber
            elif all(hasattr(ds, 'InstanceNumber') and ds.InstanceNumber for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: int(ds.InstanceNumber))
                self.logger.debug("Sorted slices by InstanceNumber.")
            else:
                self.logger.warning("Could not determine slice order. Using file list order.")
        except Exception as e:
            self.logger.warning(f"Slice sorting failed, using file list order: {e}")
            
        return dicom_datasets

    def _extract_pixel_data(self, datasets: List[pydicom.FileDataset]) -> Optional[np.ndarray]:
        """Extracts pixel data from a list of sorted datasets."""
        pixel_arrays = []
        try:
            for i, ds in enumerate(datasets):
                pixel_array = ds.pixel_array.astype(np.float32)
                
                # Apply rescale slope and intercept if they exist
                if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
                    slope = float(ds.RescaleSlope)
                    intercept = float(ds.RescaleIntercept)
                    pixel_array = pixel_array * slope + intercept
                    
                pixel_arrays.append(pixel_array)
            
            if not pixel_arrays:
                return None
            
            return np.stack(pixel_arrays, axis=0)
        except Exception as e:
            self.logger.error(f"Failed to extract pixel data from slice {i}: {e}", exc_info=True)
            return None

    def get_pixel_array(self) -> Optional[np.ndarray]:
        """Returns the loaded 3D pixel data array."""
        return self._pixel_array
        
    def get_datasets(self) -> List[pydicom.FileDataset]:
        """Returns the list of loaded and sorted pydicom datasets."""
        return self._datasets

    def get_metadata(self) -> Dict[str, Any]:
        """
        Extracts metadata from the first slice of the loaded series.
        """
        if not self._datasets:
            return {}
        
        ds = self._datasets[0]
        metadata = {}
        for elem in ds:
            # 使用标准的DICOM关键字 (tag name) 作为键，而不是描述性名称
            # 例如：使用 "WindowWidth" 而不是 "Window Width"
            key = elem.name 
            value = elem.value
            
            if isinstance(value, pydicom.multival.MultiValue):
                if elem.VR == 'PN': # Special handling for PersonName
                    metadata[key] = str(value)
                else:
                    metadata[key] = [item for item in value]
            elif isinstance(value, (pydicom.dataelem.DataElement, pydicom.dataset.Dataset)):
                 # 对于嵌套的序列，只记录其字符串表示形式，避免复杂性
                metadata[key] = str(value)
            else:
                metadata[key] = value
        
        # 确保关键信息存在
        if 'WindowCenter' not in metadata and hasattr(ds, 'WindowCenter'):
             metadata['WindowCenter'] = ds.WindowCenter
        if 'WindowWidth' not in metadata and hasattr(ds, 'WindowWidth'):
             metadata['WindowWidth'] = ds.WindowWidth
        metadata['Number of Slices'] = len(self._datasets)

        return metadata
        
    def get_window_center_width(self) -> tuple[float, float]:
        """获取窗位和窗宽
        
        Returns:
            tuple[float, float]: (窗位, 窗宽)，如果未指定则返回默认值
        """
        if not self._dataset:
            return 40.0, 400.0  # 默认值
            
        # 获取窗位和窗宽，可能是单个值或列表
        center = getattr(self._dataset, 'WindowCenter', 40.0)
        width = getattr(self._dataset, 'WindowWidth', 400.0)
        
        # 如果是列表，取第一个值
        if isinstance(center, list):
            center = center[0]
        if isinstance(width, list):
            width = width[0]
            
        return float(center), float(width) 