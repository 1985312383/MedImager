# 使用 pydicom 处理 DICOM 文件的加载和解析 
from typing import List, Optional, Dict, Any
import os
import pydicom
import numpy as np
from PySide6.QtCore import QObject, Signal
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
            dataset = pydicom.dcmread(file_path)
            self._datasets = [dataset]
            self._pixel_array = self._extract_pixel_data(self._datasets)
            if self._pixel_array is None:
                return False
            self.data_loaded.emit()
            return True
        except Exception as e:
            self.logger.error(f"加载 DICOM 文件失败: {str(e)}")
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
        """Sort DICOM slices using patient-space geometry when available."""
        try:
            geometries = [(ds, self._slice_geometry(ds)) for ds in dicom_datasets]
            if geometries and all(geometry is not None for _, geometry in geometries):
                valid_geometries = [
                    (ds, geometry) for ds, geometry in geometries if geometry is not None
                ]
                reference_normal = valid_geometries[0][1][1]
                self._log_geometry_consistency(valid_geometries, reference_normal)
                valid_geometries.sort(
                    key=lambda item: float(np.dot(item[1][0], reference_normal))
                )
                dicom_datasets[:] = [ds for ds, _ in valid_geometries]
                self.logger.debug("Sorted slices by ImageOrientationPatient/ImagePositionPatient.")
                return dicom_datasets

            if all(hasattr(ds, 'SliceLocation') and ds.SliceLocation is not None for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: float(ds.SliceLocation))
                self.logger.debug("Sorted slices by SliceLocation.")
            elif all(hasattr(ds, 'InstanceNumber') and ds.InstanceNumber for ds in dicom_datasets):
                dicom_datasets.sort(key=lambda ds: int(ds.InstanceNumber))
                self.logger.debug("Sorted slices by InstanceNumber.")
            else:
                self.logger.warning("Could not determine slice order. Using file list order.")
        except Exception as e:
            self.logger.warning(f"Slice sorting failed, using file list order: {e}")
            
        return dicom_datasets

    def _can_sort_by_patient_position(self, datasets: List[pydicom.FileDataset]) -> bool:
        return all(self._slice_geometry(ds) is not None for ds in datasets)

    def _image_position(self, dataset: pydicom.FileDataset) -> np.ndarray:
        position = self._numeric_tag_sequence(dataset, 'ImagePositionPatient', 3)
        if position is None:
            raise ValueError("Missing or invalid ImagePositionPatient")
        return position

    def _slice_normal(self, dataset: pydicom.FileDataset) -> Optional[np.ndarray]:
        orientation = self._numeric_tag_sequence(dataset, 'ImageOrientationPatient', 6)
        if orientation is None:
            return None
        return self._normal_from_orientation(orientation)

    def _slice_geometry(self, dataset: pydicom.FileDataset) -> Optional[tuple[np.ndarray, np.ndarray]]:
        position = self._numeric_tag_sequence(dataset, 'ImagePositionPatient', 3)
        orientation = self._numeric_tag_sequence(dataset, 'ImageOrientationPatient', 6)
        if position is None or orientation is None:
            return None

        normal = self._normal_from_orientation(orientation)
        if normal is None:
            return None
        return position, normal

    def _numeric_tag_sequence(
        self,
        dataset: pydicom.FileDataset,
        tag_name: str,
        minimum_length: int,
    ) -> Optional[np.ndarray]:
        value = getattr(dataset, tag_name, None)
        try:
            if value is None or len(value) < minimum_length:
                return None
            return np.asarray([float(v) for v in value[:minimum_length]], dtype=np.float64)
        except (TypeError, ValueError):
            self.logger.warning(f"Invalid {tag_name}; falling back to secondary slice sorting tags.")
            return None

    def _normal_from_orientation(self, orientation: np.ndarray) -> Optional[np.ndarray]:
        try:
            row = orientation[:3]
            col = orientation[3:]
            normal = np.cross(row, col)
            norm = np.linalg.norm(normal)
            if norm == 0:
                self.logger.warning("Invalid ImageOrientationPatient: zero slice normal.")
                return None
            return normal / norm
        except Exception as e:
            self.logger.warning(f"Could not calculate DICOM slice normal: {e}")
            return None

    def _log_geometry_consistency(
        self,
        geometries: List[tuple[pydicom.FileDataset, tuple[np.ndarray, np.ndarray]]],
        reference_normal: np.ndarray,
    ) -> None:
        for _, (_, normal) in geometries[1:]:
            if not np.allclose(normal, reference_normal, atol=1e-4):
                self.logger.warning("Inconsistent ImageOrientationPatient found within one series.")
                break

        projections = [float(np.dot(position, reference_normal)) for _, (position, _) in geometries]
        if len(projections) >= 3:
            spacings = np.diff(sorted(projections))
            positive_spacings = spacings[np.abs(spacings) > 1e-6]
            if positive_spacings.size and np.ptp(positive_spacings) > 1e-3:
                self.logger.warning("Non-uniform slice spacing detected in DICOM series.")

    def _extract_pixel_data(self, datasets: List[pydicom.FileDataset]) -> Optional[np.ndarray]:
        """Extracts pixel data from a list of sorted datasets."""
        pixel_arrays = []
        try:
            for i, ds in enumerate(datasets):
                pixel_array = self._apply_modality_transform(ds.pixel_array.astype(np.float32), ds)
                    
                pixel_arrays.append(pixel_array)
            
            if not pixel_arrays:
                return None
            
            return np.stack(pixel_arrays, axis=0)
        except Exception as e:
            self.logger.error(f"Failed to extract pixel data from slice {i}: {e}", exc_info=True)
            return None

    def _apply_modality_transform(self, pixel_array: np.ndarray, dataset: pydicom.FileDataset) -> np.ndarray:
        """Apply the minimal modality transform used by the 1.0 display path."""
        slope = float(getattr(dataset, 'RescaleSlope', 1.0))
        intercept = float(getattr(dataset, 'RescaleIntercept', 0.0))
        return pixel_array * slope + intercept

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
            # 使用标准的DICOM关键字作为键
            key = elem.keyword if elem.keyword else elem.name
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
        if not self._datasets:
            return 40.0, 400.0  # 默认值

        ds = self._datasets[0]

        # 获取窗位和窗宽，可能是单个值或列表
        center = getattr(ds, 'WindowCenter', 40.0)
        width = getattr(ds, 'WindowWidth', 400.0)
        
        # 如果是列表，取第一个值
        if isinstance(center, list):
            center = center[0]
        if isinstance(width, list):
            width = width[0]
            
        return float(center), float(width) 
    
    def _group_files_by_series(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """将DICOM文件按序列分组
        
        Args:
            file_paths: DICOM文件路径列表
            
        Returns:
            Dict[str, List[str]]: 序列UID到文件路径列表的映射
        """
        self.logger.debug(f"[DicomParser._group_files_by_series] 开始分组 {len(file_paths)} 个文件")
        
        series_groups = {}
        
        for file_path in file_paths:
            try:
                # 只读取元数据，不读取像素数据以提高性能
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                
                # 获取序列实例UID，这是标准的序列标识符
                series_uid = getattr(ds, 'SeriesInstanceUID', 'Unknown')
                
                if series_uid not in series_groups:
                    series_groups[series_uid] = []
                    
                series_groups[series_uid].append(file_path)
                
                self.logger.debug(f"[DicomParser._group_files_by_series] 文件 {os.path.basename(file_path)} 分组到序列 {series_uid}")
                
            except Exception as e:
                self.logger.warning(f"[DicomParser._group_files_by_series] 无法读取文件 {file_path}: {e}")
                continue
        
        self.logger.info(f"[DicomParser._group_files_by_series] 分组完成: 发现 {len(series_groups)} 个序列，包含 {sum(len(files) for files in series_groups.values())} 个文件")
        
        return series_groups
    
    def get_series_info(self, file_path: str) -> Dict[str, Any]:
        """获取单个DICOM文件的序列信息
        
        Args:
            file_path: DICOM文件路径
            
        Returns:
            Dict[str, Any]: 包含序列信息的字典
        """
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
            
            info = {
                'series_instance_uid': getattr(ds, 'SeriesInstanceUID', 'Unknown'),
                'series_number': getattr(ds, 'SeriesNumber', 'Unknown'),
                'series_description': getattr(ds, 'SeriesDescription', 'Unknown'),
                'modality': getattr(ds, 'Modality', 'Unknown'),
                'patient_name': getattr(ds, 'PatientName', 'Unknown'),
                'patient_id': getattr(ds, 'PatientID', 'Unknown'),
                'study_instance_uid': getattr(ds, 'StudyInstanceUID', 'Unknown'),
                'study_description': getattr(ds, 'StudyDescription', 'Unknown'),
                'study_date': getattr(ds, 'StudyDate', 'Unknown'),
                'acquisition_date': getattr(ds, 'AcquisitionDate', 'Unknown'),
                'slice_thickness': getattr(ds, 'SliceThickness', 'Unknown'),
                'pixel_spacing': getattr(ds, 'PixelSpacing', 'Unknown'),
                'rows': getattr(ds, 'Rows', 'Unknown'),
                'columns': getattr(ds, 'Columns', 'Unknown'),
            }
            
            # 转换一些字段为字符串格式以便显示
            if hasattr(ds, 'PatientName'):
                info['patient_name'] = str(ds.PatientName)
            if hasattr(ds, 'PixelSpacing') and ds.PixelSpacing:
                info['pixel_spacing'] = f"{ds.PixelSpacing[0]:.2f} x {ds.PixelSpacing[1]:.2f} mm"
            if hasattr(ds, 'SliceThickness'):
                info['slice_thickness'] = f"{ds.SliceThickness} mm"
                
            return info
            
        except Exception as e:
            self.logger.error(f"[DicomParser.get_series_info] 无法读取文件信息 {file_path}: {e}")
            return {} 
