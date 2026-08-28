# 使用 pydicom 处理 DICOM 文件的加载和解析
from copy import copy
from hashlib import sha1
from typing import List, Optional, Dict, Any, Union
import os
import pydicom
import numpy as np
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.pixels import (
    apply_color_lut,
    apply_icc_profile,
    apply_modality_lut,
    pixel_array as decode_pixel_array,
)
from PySide6.QtCore import QObject, Signal
from medimager.utils.logger import get_logger
from medimager.core.lazy_pixel_volume import LazyPixelVolume


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
        # _source_datasets are the physical files. _datasets map one-to-one to
        # displayed frames, including synthetic per-frame datasets for enhanced
        # multi-frame objects.
        self._source_datasets: List[pydicom.FileDataset] = []
        self._datasets: List[pydicom.FileDataset] = []
        self._frame_sources: List[tuple[pydicom.FileDataset, int]] = []
        self._frame_paths: List[str] = []
        self._pixel_array: Optional[Union[np.ndarray, LazyPixelVolume]] = None
        self._image_mode = "grayscale_volume"

    def _reset_loaded_state(self) -> None:
        if isinstance(self._pixel_array, LazyPixelVolume):
            self._pixel_array.close()
        self._source_datasets = []
        self._datasets = []
        self._frame_sources = []
        self._frame_paths = []
        self._pixel_array = None
        self._image_mode = "grayscale_volume"

    def clear(self) -> None:
        """Release decoded-frame caches and loaded metadata."""
        self._reset_loaded_state()

    def load_file(self, file_path: str) -> bool:
        """加载单个 DICOM 文件

        Args:
            file_path: DICOM 文件的路径

        Returns:
            bool: 加载是否成功
        """
        return self.load_series([file_path])

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
        self._reset_loaded_state()
        try:
            # Read metadata only. Pixel data is decoded per-frame on demand,
            # avoiding both retained PixelData and a full float32 volume.
            datasets: list[pydicom.FileDataset] = []
            source_paths: dict[int, str] = {}
            for file_path in file_paths:
                try:
                    normalized_path = os.path.abspath(os.fspath(file_path))
                    ds = pydicom.dcmread(normalized_path, stop_before_pixels=True)
                    datasets.append(ds)
                    source_paths[id(ds)] = normalized_path
                except Exception as e:
                    self.logger.warning(f"Could not read {file_path}: {e}")
                    continue

            if not datasets:
                self.logger.error("No valid DICOM files could be read.")
                return False

            # 2. Sort the datasets into slice order
            self._source_datasets = self._sort_dicom_slices(datasets)

            # 3. Build a frame index and a small decoded-frame cache.
            pixel_data = self._build_lazy_pixel_volume(
                self._source_datasets,
                source_paths,
            )

            if pixel_data is None:
                self.logger.error("Failed to extract pixel data from the series.")
                return False
            self._pixel_array = pixel_data

            self.logger.info(
                f"Successfully loaded and parsed DICOM series. Shape: {self._pixel_array.shape}"
            )
            self.data_loaded.emit()
            return True

        except Exception as e:
            self.logger.error(
                f"An unexpected error occurred during DICOM series loading: {e}",
                exc_info=True,
            )
            self._reset_loaded_state()
            return False

    def _sort_dicom_slices(
        self, dicom_datasets: List[pydicom.FileDataset]
    ) -> List[pydicom.FileDataset]:
        """Sort slices without collapsing temporal or multi-stack dimensions.

        Patient-space projection remains the preferred spatial key. Temporal
        position and stack identity are used ahead of that projection so a
        directly loaded 4-D acquisition is at least ordered as complete
        volumes instead of interleaving equal slice locations.
        """
        try:
            geometries = [(ds, self._slice_geometry(ds)) for ds in dicom_datasets]
            if geometries and all(geometry is not None for _, geometry in geometries):
                valid_geometries = [
                    (ds, geometry)
                    for ds, geometry in geometries
                    if geometry is not None
                ]
                reference_normal = valid_geometries[0][1][1]
                self._log_geometry_consistency(valid_geometries, reference_normal)
                indexed = list(enumerate(valid_geometries))
                indexed.sort(
                    key=lambda item: (
                        self._temporal_sort_key(item[1][0]),
                        self._stack_sort_key(item[1][0]),
                        float(np.dot(item[1][1][0], reference_normal)),
                        self._numeric_sort_key(item[1][0], "InStackPositionNumber"),
                        self._numeric_sort_key(item[1][0], "InstanceNumber"),
                        item[0],
                    )
                )
                dicom_datasets[:] = [item[1][0] for item in indexed]
                self.logger.debug(
                    "Sorted slices by ImageOrientationPatient/ImagePositionPatient."
                )
                return dicom_datasets

            if all(
                self._numeric_value(ds, "SliceLocation") is not None
                for ds in dicom_datasets
            ):
                indexed = list(enumerate(dicom_datasets))
                indexed.sort(
                    key=lambda item: (
                        self._temporal_sort_key(item[1]),
                        self._stack_sort_key(item[1]),
                        self._numeric_sort_key(item[1], "SliceLocation"),
                        self._numeric_sort_key(item[1], "InstanceNumber"),
                        item[0],
                    )
                )
                dicom_datasets[:] = [ds for _, ds in indexed]
                self.logger.debug("Sorted slices by SliceLocation.")
            elif any(
                self._numeric_value(ds, "InstanceNumber") is not None
                for ds in dicom_datasets
            ):
                # InstanceNumber=0 is valid and must not disable sorting.
                indexed = list(enumerate(dicom_datasets))
                indexed.sort(
                    key=lambda item: (
                        self._temporal_sort_key(item[1]),
                        self._stack_sort_key(item[1]),
                        self._numeric_sort_key(item[1], "InstanceNumber"),
                        item[0],
                    )
                )
                dicom_datasets[:] = [ds for _, ds in indexed]
                self.logger.debug("Sorted slices by InstanceNumber.")
            else:
                self.logger.warning(
                    "Could not determine slice order. Using file list order."
                )
        except Exception as e:
            self.logger.warning(f"Slice sorting failed, using file list order: {e}")

        return dicom_datasets

    def _numeric_value(self, dataset: Dataset, keyword: str) -> Optional[float]:
        value = getattr(dataset, keyword, None)
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _numeric_sort_key(self, dataset: Dataset, keyword: str) -> tuple[int, float]:
        value = self._numeric_value(dataset, keyword)
        return (1, 0.0) if value is None else (0, value)

    def _temporal_sort_key(self, dataset: Dataset) -> tuple[int, float, str]:
        for keyword in ("TemporalPositionIndex", "TemporalPositionIdentifier"):
            value = self._numeric_value(dataset, keyword)
            if value is not None:
                return (0, value, "")
        value = getattr(dataset, "TemporalPositionIdentifier", None)
        return (1, 0.0, "" if value is None else str(value))

    def _stack_sort_key(self, dataset: Dataset) -> tuple[int, str]:
        value = getattr(dataset, "StackID", None)
        return (1, "") if value in (None, "") else (0, str(value))

    def _can_sort_by_patient_position(
        self, datasets: List[pydicom.FileDataset]
    ) -> bool:
        return all(self._slice_geometry(ds) is not None for ds in datasets)

    def _image_position(self, dataset: pydicom.FileDataset) -> np.ndarray:
        position = self._numeric_tag_sequence(dataset, "ImagePositionPatient", 3)
        if position is None:
            raise ValueError("Missing or invalid ImagePositionPatient")
        return position

    def _slice_normal(self, dataset: pydicom.FileDataset) -> Optional[np.ndarray]:
        orientation = self._numeric_tag_sequence(dataset, "ImageOrientationPatient", 6)
        if orientation is None:
            return None
        return self._normal_from_orientation(orientation)

    def _slice_geometry(
        self, dataset: pydicom.FileDataset
    ) -> Optional[tuple[np.ndarray, np.ndarray]]:
        position = self._numeric_tag_sequence(dataset, "ImagePositionPatient", 3)
        orientation = self._numeric_tag_sequence(dataset, "ImageOrientationPatient", 6)
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
            return np.asarray(
                [float(v) for v in value[:minimum_length]], dtype=np.float64
            )
        except (TypeError, ValueError):
            self.logger.warning(
                f"Invalid {tag_name}; falling back to secondary slice sorting tags."
            )
            return None

    def _normal_from_orientation(self, orientation: np.ndarray) -> Optional[np.ndarray]:
        try:
            row = orientation[:3]
            col = orientation[3:]
            normal = np.cross(row, col)
            norm = np.linalg.norm(normal)
            if norm == 0:
                self.logger.warning(
                    "Invalid ImageOrientationPatient: zero slice normal."
                )
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
                self.logger.warning(
                    "Inconsistent ImageOrientationPatient found within one series."
                )
                break

        projections = [
            float(np.dot(position, reference_normal)) for _, (position, _) in geometries
        ]
        if len(projections) >= 3:
            spacings = np.diff(sorted(projections))
            positive_spacings = spacings[np.abs(spacings) > 1e-6]
            if positive_spacings.size and np.ptp(positive_spacings) > 1e-3:
                self.logger.warning(
                    "Non-uniform slice spacing detected in DICOM series."
                )

        reference_spacing = self._pixel_spacing(geometries[0][0])
        if reference_spacing is not None:
            for ds, _ in geometries[1:]:
                spacing = self._pixel_spacing(ds)
                if spacing is not None and not np.allclose(
                    spacing, reference_spacing, atol=1e-6
                ):
                    self.logger.warning(
                        "Inconsistent PixelSpacing found within one DICOM series."
                    )
                    break

    def _pixel_spacing(
        self,
        dataset: pydicom.FileDataset,
        frame_index: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """Return row/column spacing, including enhanced functional groups."""
        values = []
        if frame_index is not None:
            values.append(
                self._functional_group_value(
                    dataset,
                    "PerFrameFunctionalGroupsSequence",
                    frame_index,
                    "PixelMeasuresSequence",
                    "PixelSpacing",
                )
            )
        values.extend(
            [
                getattr(dataset, "PixelSpacing", None),
                self._functional_group_value(
                    dataset,
                    "SharedFunctionalGroupsSequence",
                    0,
                    "PixelMeasuresSequence",
                    "PixelSpacing",
                ),
                getattr(dataset, "ImagerPixelSpacing", None),
            ]
        )
        for value in values:
            try:
                if value is None or len(value) < 2:
                    continue
                spacing = np.asarray(
                    [float(value[0]), float(value[1])], dtype=np.float64
                )
                if np.all(np.isfinite(spacing)) and np.all(spacing > 0):
                    return spacing
            except (TypeError, ValueError, IndexError):
                continue
        return None

    @staticmethod
    def _functional_group_value(
        dataset: Dataset,
        functional_group_keyword: str,
        group_index: int,
        nested_sequence_keyword: str,
        value_keyword: str,
    ) -> Any:
        try:
            groups = getattr(dataset, functional_group_keyword, None)
            if not groups or not (0 <= group_index < len(groups)):
                return None
            nested = getattr(groups[group_index], nested_sequence_keyword, None)
            if not nested:
                return None
            return getattr(nested[0], value_keyword, None)
        except (AttributeError, IndexError, TypeError):
            return None

    def _build_lazy_pixel_volume(
        self,
        datasets: List[pydicom.FileDataset],
        source_paths: Dict[int, str],
    ) -> LazyPixelVolume:
        """Index displayed frames without retaining source PixelData."""
        frame_datasets: list[pydicom.FileDataset] = []
        frame_sources: list[tuple[pydicom.FileDataset, int]] = []
        frame_paths: list[str] = []

        for dataset in datasets:
            path = source_paths.get(id(dataset)) or getattr(dataset, "filename", None)
            if not path:
                raise ValueError("DICOM source path is unavailable for lazy decoding")
            frame_count = max(1, int(getattr(dataset, "NumberOfFrames", 1) or 1))
            for frame_index in range(frame_count):
                frame_dataset = (
                    self._build_frame_dataset(dataset, frame_index)
                    if frame_count > 1
                    else dataset
                )
                frame_datasets.append(frame_dataset)
                frame_sources.append((dataset, frame_index))
                frame_paths.append(os.fspath(path))

        if not frame_datasets:
            raise ValueError("DICOM series contains no displayable frames")

        self._datasets = frame_datasets
        self._frame_sources = frame_sources
        self._frame_paths = frame_paths
        volume = LazyPixelVolume(
            len(frame_datasets),
            self._decode_lazy_frame,
            cache_limit_bytes=128 * 1024 * 1024,
            prefetch_radius=2,
        )
        self._image_mode = (
            "rgb_volume"
            if len(volume.shape) == 4 and volume.shape[-1] in (3, 4)
            else "grayscale_volume"
        )
        volume.prefetch(range(1, min(len(volume), 3)))
        return volume

    def _decode_lazy_frame(self, display_index: int) -> np.ndarray:
        source, frame_index = self._frame_sources[display_index]
        source_path = self._frame_paths[display_index]
        frame_dataset = self._datasets[display_index]
        try:
            pixels = decode_pixel_array(source_path, index=frame_index, raw=False)
        except Exception as exc:
            transfer_syntax = getattr(
                getattr(source, "file_meta", None), "TransferSyntaxUID", None
            )
            syntax_description = (
                f" TransferSyntaxUID={transfer_syntax} ({transfer_syntax.name})."
                if transfer_syntax is not None
                else ""
            )
            raise RuntimeError(
                f"Failed to decode DICOM frame {display_index}.{syntax_description}"
            ) from exc
        return self._prepare_frame_pixels(pixels, frame_dataset)

    def _prepare_frame_pixels(
        self,
        pixel_array: np.ndarray,
        dataset: pydicom.FileDataset,
    ) -> np.ndarray:
        """Apply the quantitative or colour transform appropriate to a frame."""
        pixels = np.asarray(pixel_array)
        photometric = str(
            getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
        ).upper()
        if photometric == "PALETTE COLOR":
            pixels = apply_color_lut(pixels, dataset)

        is_colour = (
            int(getattr(dataset, "SamplesPerPixel", 1) or 1) > 1
            or (pixels.ndim >= 3 and pixels.shape[-1] in (3, 4))
            or photometric == "PALETTE COLOR"
        )
        if is_colour:
            if getattr(dataset, "ICCProfile", None) is not None:
                try:
                    pixels = apply_icc_profile(pixels, dataset)
                except Exception as exc:
                    self.logger.warning("Could not apply DICOM ICC profile: %s", exc)
            self._image_mode = "rgb_volume"
            return np.asarray(pixels)

        return self._apply_modality_transform(pixels, dataset)

    def _extract_pixel_data(
        self, datasets: List[pydicom.FileDataset]
    ) -> Optional[np.ndarray]:
        """Extracts pixel data from a list of sorted datasets."""
        self._datasets = []
        self._frame_sources = []
        self._frame_paths = []
        pixel_arrays = []
        frame_datasets: List[pydicom.FileDataset] = []
        frame_sources: List[tuple[pydicom.FileDataset, int]] = []
        i = -1
        try:
            for i, ds in enumerate(datasets):
                pixel_array = self._read_pixel_array(ds, i)
                if pixel_array is None:
                    return None

                frames = self._normalize_pixel_array_frames(pixel_array, ds, i)
                if frames is None:
                    return None

                is_multiframe = (
                    len(frames) > 1 or int(getattr(ds, "NumberOfFrames", 1)) > 1
                )
                for frame_index, frame in enumerate(frames):
                    frame_dataset = (
                        self._build_frame_dataset(ds, frame_index)
                        if is_multiframe
                        else ds
                    )
                    transformed = self._prepare_frame_pixels(frame, frame_dataset)
                    pixel_arrays.append(transformed)
                    frame_datasets.append(frame_dataset)
                    frame_sources.append((ds, frame_index))

            if not pixel_arrays:
                return None

            self._datasets = frame_datasets
            self._frame_sources = frame_sources
            stacked = np.stack(pixel_arrays, axis=0)
            self._image_mode = (
                "rgb_volume"
                if stacked.ndim == 4 and stacked.shape[-1] in (3, 4)
                else "grayscale_volume"
            )
            return stacked
        except Exception as e:
            self.logger.error(
                f"Failed to extract pixel data from slice {i}: {e}", exc_info=True
            )
            self._datasets = []
            self._frame_sources = []
            return None

    def _read_pixel_array(
        self, dataset: pydicom.FileDataset, slice_index: int
    ) -> Optional[np.ndarray]:
        try:
            return dataset.pixel_array
        except Exception as e:
            transfer_syntax = getattr(
                getattr(dataset, "file_meta", None), "TransferSyntaxUID", None
            )
            if transfer_syntax is not None and getattr(
                transfer_syntax, "is_compressed", False
            ):
                self.logger.error(
                    "Failed to decode compressed DICOM pixel data for slice "
                    f"{slice_index}. TransferSyntaxUID={transfer_syntax} "
                    f"({transfer_syntax.name}). Install a compatible pydicom pixel data "
                    "decoder such as pylibjpeg plugins or gdcm.",
                    exc_info=True,
                )
            else:
                self.logger.error(
                    f"Failed to decode DICOM pixel data for slice {slice_index}: {e}",
                    exc_info=True,
                )
            return None

    def _normalize_pixel_array_frames(
        self,
        pixel_array: np.ndarray,
        dataset: pydicom.FileDataset,
        slice_index: int,
    ) -> Optional[List[np.ndarray]]:
        if pixel_array.ndim == 2:
            return [pixel_array]

        samples_per_pixel = int(getattr(dataset, "SamplesPerPixel", 1))
        number_of_frames = int(getattr(dataset, "NumberOfFrames", 1))

        if (
            pixel_array.ndim == 3
            and samples_per_pixel > 1
            and pixel_array.shape[-1] in (3, 4)
            and number_of_frames == 1
        ):
            return [pixel_array]

        if pixel_array.ndim == 3 and samples_per_pixel == 1 and number_of_frames > 1:
            self.logger.info(
                f"Expanding multi-frame DICOM slice {slice_index}: {number_of_frames} frames."
            )
            return [
                pixel_array[frame_index] for frame_index in range(pixel_array.shape[0])
            ]

        if (
            pixel_array.ndim == 4
            and samples_per_pixel > 1
            and pixel_array.shape[-1] in (3, 4)
            and number_of_frames > 1
        ):
            return [pixel_array[index] for index in range(pixel_array.shape[0])]

        self.logger.error(
            "Unsupported DICOM pixel array shape "
            f"{pixel_array.shape} for slice {slice_index}. "
            "Expected grayscale, RGB/YBR, or palette-colour image frames."
        )
        return None

    def _apply_modality_transform(
        self, pixel_array: np.ndarray, dataset: pydicom.FileDataset
    ) -> np.ndarray:
        """Apply the standard modality LUT/rescale while retaining quantities.

        VOI transforms deliberately remain in the display pipeline so ROI and
        measurement statistics continue to use modality-rescaled values.
        """
        try:
            transformed = apply_modality_lut(np.asarray(pixel_array), dataset)
        except Exception as e:
            self.logger.warning(
                f"pydicom modality LUT failed; using rescale fallback: {e}"
            )
            slope = float(getattr(dataset, "RescaleSlope", 1.0))
            intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
            transformed = np.asarray(pixel_array, dtype=np.float64) * slope + intercept
        return np.asarray(transformed, dtype=np.float32)

    def _build_frame_dataset(
        self,
        source: pydicom.FileDataset,
        frame_index: int,
    ) -> pydicom.FileDataset:
        """Build a lightweight dataset with shared/per-frame tags overlaid."""
        frame = Dataset()
        if hasattr(source, "file_meta"):
            frame.file_meta = source.file_meta

        for elem in source:
            if elem.keyword in {
                "PixelData",
                "SharedFunctionalGroupsSequence",
                "PerFrameFunctionalGroupsSequence",
            }:
                continue
            frame.add(copy(elem))

        shared_groups = getattr(source, "SharedFunctionalGroupsSequence", None)
        if shared_groups:
            frame.SharedFunctionalGroupsSequence = DicomSequence([shared_groups[0]])
            self._overlay_functional_group(frame, shared_groups[0])

        per_frame_groups = getattr(source, "PerFrameFunctionalGroupsSequence", None)
        if per_frame_groups and 0 <= frame_index < len(per_frame_groups):
            group = per_frame_groups[frame_index]
            frame.PerFrameFunctionalGroupsSequence = DicomSequence([group])
            self._overlay_functional_group(frame, group)

        return frame

    def _overlay_functional_group(self, target: Dataset, group: Dataset) -> None:
        """Expose nested functional-group attributes through normal tag access."""
        for elem in group:
            if elem.VR != "SQ":
                target.add(copy(elem))
                continue
            # Preserve the functional sequence for complete tag inspection
            # while also flattening its leaf attributes for normal keyword
            # access (PixelSpacing, ImagePositionPatient, rescale, VOI, etc.).
            target.add(copy(elem))
            for nested_dataset in elem.value:
                self._overlay_functional_group(target, nested_dataset)

    def get_pixel_array(self) -> Optional[Union[np.ndarray, LazyPixelVolume]]:
        """Return the array-like frame store (lazy for path-loaded DICOM)."""
        return self._pixel_array

    def get_image_mode(self) -> str:
        return self._image_mode

    def is_lazy(self) -> bool:
        return isinstance(self._pixel_array, LazyPixelVolume)

    def get_pixel_cache_info(self) -> Dict[str, int]:
        if isinstance(self._pixel_array, LazyPixelVolume):
            return {
                "usage_bytes": self._pixel_array.cache_bytes,
                "limit_bytes": self._pixel_array.cache_limit_bytes,
            }
        usage = int(getattr(self._pixel_array, "nbytes", 0))
        return {"usage_bytes": usage, "limit_bytes": usage}

    def get_datasets(self) -> List[pydicom.FileDataset]:
        """Return one dataset per displayed slice/frame."""
        return self._datasets

    def get_source_datasets(self) -> List[pydicom.FileDataset]:
        """Return the physical source-file datasets."""
        return self._source_datasets

    def get_frame_source(
        self, frame_index: int
    ) -> Optional[tuple[pydicom.FileDataset, int]]:
        """Return the source dataset and source-frame index for a display frame."""
        if 0 <= frame_index < len(self._frame_sources):
            return self._frame_sources[frame_index]
        return None

    def get_metadata(self, frame_index: int = 0) -> Dict[str, Any]:
        """
        Extract metadata for a displayed frame (the first frame by default).
        """
        if not self._datasets or not (0 <= frame_index < len(self._datasets)):
            return {}

        ds = self._datasets[frame_index]
        metadata = {}
        for elem in ds:
            if elem.keyword == "PixelData":
                continue
            # 使用标准的DICOM关键字作为键
            key = elem.keyword if elem.keyword else elem.name
            value = elem.value

            if isinstance(value, pydicom.multival.MultiValue):
                if elem.VR == "PN":  # Special handling for PersonName
                    metadata[key] = str(value)
                else:
                    metadata[key] = [item for item in value]
            elif elem.VR == "SQ" or isinstance(
                value, (pydicom.dataelem.DataElement, pydicom.dataset.Dataset)
            ):
                # Retain flattened frame attributes separately and keep the
                # original sequence printable for the tag inspector.
                metadata[key] = str(value)
            elif elem.VR == "PN":
                metadata[key] = str(value)
            else:
                metadata[key] = value

        # 确保关键信息存在
        if "WindowCenter" not in metadata and hasattr(ds, "WindowCenter"):
            metadata["WindowCenter"] = ds.WindowCenter
        if "WindowWidth" not in metadata and hasattr(ds, "WindowWidth"):
            metadata["WindowWidth"] = ds.WindowWidth
        metadata["Number of Slices"] = len(self._datasets)
        metadata["DisplayFrameIndex"] = frame_index
        source = self.get_frame_source(frame_index)
        if source is not None and int(getattr(source[0], "NumberOfFrames", 1)) > 1:
            metadata["SourceFrameNumber"] = source[1] + 1

        return metadata

    def get_pixel_spacing(self, frame_index: int = 0) -> Optional[tuple[float, float]]:
        """Return positive row/column spacing in millimetres."""
        if not self._datasets or not (0 <= frame_index < len(self._datasets)):
            return None
        spacing = self._pixel_spacing(self._datasets[frame_index])
        if spacing is None:
            source = self.get_frame_source(frame_index)
            if source is not None:
                spacing = self._pixel_spacing(source[0], source[1])
        if spacing is None:
            return None
        return float(spacing[0]), float(spacing[1])

    def get_window_center_width(self) -> tuple[float, float]:
        """获取窗位和窗宽

        Returns:
            tuple[float, float]: (窗位, 窗宽)，如果未指定则返回默认值
        """
        if not self._datasets:
            return 40.0, 400.0  # 默认值

        ds = self._datasets[0]

        # 获取窗位和窗宽，可能是单个值或列表
        center = getattr(ds, "WindowCenter", 40.0)
        width = getattr(ds, "WindowWidth", 400.0)

        # DICOM DS values may be MultiValue rather than a Python list.
        if isinstance(center, (list, tuple, pydicom.multival.MultiValue)):
            center = center[0]
        if isinstance(width, (list, tuple, pydicom.multival.MultiValue)):
            width = width[0]

        try:
            center_value = float(center)
            width_value = float(width)
            if (
                not np.isfinite(center_value)
                or not np.isfinite(width_value)
                or width_value < 1
            ):
                raise ValueError("WindowWidth must be finite and at least 1")
            return center_value, width_value
        except (TypeError, ValueError, IndexError) as e:
            self.logger.warning(
                f"Invalid DICOM window center/width; using defaults: {e}"
            )
            return 40.0, 400.0

    def _group_files_by_series(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """将DICOM文件按序列分组

        Args:
            file_paths: DICOM文件路径列表

        Returns:
            Dict[str, List[str]]: 序列UID到文件路径列表的映射
        """
        self.logger.debug(
            f"[DicomParser._group_files_by_series] 开始分组 {len(file_paths)} 个文件"
        )

        series_groups = {}

        for file_path in file_paths:
            try:
                # 只读取元数据，不读取像素数据以提高性能
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)

                # Keep unsupported temporal/stack dimensions out of a single
                # 3-D volume. Missing UIDs receive a stable metadata-derived
                # identity instead of collapsing every such file into Unknown.
                series_uid = self._series_group_key(ds, file_path)

                if series_uid not in series_groups:
                    series_groups[series_uid] = []

                series_groups[series_uid].append(file_path)

                self.logger.debug(
                    f"[DicomParser._group_files_by_series] 文件 {os.path.basename(file_path)} 分组到序列 {series_uid}"
                )

            except Exception as e:
                self.logger.warning(
                    f"[DicomParser._group_files_by_series] 无法读取文件 {file_path}: {e}"
                )
                continue

        self.logger.info(
            f"[DicomParser._group_files_by_series] 分组完成: 发现 {len(series_groups)} 个序列，包含 {sum(len(files) for files in series_groups.values())} 个文件"
        )

        return series_groups

    def _series_group_key(self, dataset: Dataset, file_path: str) -> str:
        raw_uid = getattr(dataset, "SeriesInstanceUID", None)
        if raw_uid not in (None, ""):
            base = str(raw_uid)
        else:
            orientation = getattr(dataset, "ImageOrientationPatient", "")
            identity = "|".join(
                [
                    os.path.normcase(os.path.abspath(os.path.dirname(file_path))),
                    str(getattr(dataset, "StudyInstanceUID", "")),
                    str(getattr(dataset, "SeriesNumber", "")),
                    str(getattr(dataset, "SeriesDescription", "")),
                    str(getattr(dataset, "Modality", "")),
                    str(getattr(dataset, "SOPClassUID", "")),
                    str(getattr(dataset, "Rows", "")),
                    str(getattr(dataset, "Columns", "")),
                    str(orientation),
                ]
            )
            base = f"missing-series-{sha1(identity.encode('utf-8')).hexdigest()[:16]}"

        dimensions = []
        stack_id = getattr(dataset, "StackID", None)
        temporal_id = getattr(
            dataset,
            "TemporalPositionIndex",
            getattr(dataset, "TemporalPositionIdentifier", None),
        )
        if stack_id not in (None, ""):
            dimensions.append(f"stack={stack_id}")
        if temporal_id not in (None, ""):
            dimensions.append(f"temporal={temporal_id}")
        return base if not dimensions else f"{base}::{'::'.join(dimensions)}"

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
                "series_instance_uid": getattr(ds, "SeriesInstanceUID", "Unknown"),
                "series_number": getattr(ds, "SeriesNumber", "Unknown"),
                "series_description": getattr(ds, "SeriesDescription", "Unknown"),
                "modality": getattr(ds, "Modality", "Unknown"),
                "patient_name": getattr(ds, "PatientName", "Unknown"),
                "patient_id": getattr(ds, "PatientID", "Unknown"),
                "study_instance_uid": getattr(ds, "StudyInstanceUID", "Unknown"),
                "study_description": getattr(ds, "StudyDescription", "Unknown"),
                "study_date": getattr(ds, "StudyDate", "Unknown"),
                "acquisition_date": getattr(ds, "AcquisitionDate", "Unknown"),
                "slice_thickness": getattr(ds, "SliceThickness", "Unknown"),
                "pixel_spacing": getattr(ds, "PixelSpacing", "Unknown"),
                "rows": getattr(ds, "Rows", "Unknown"),
                "columns": getattr(ds, "Columns", "Unknown"),
            }

            # 转换一些字段为字符串格式以便显示
            if hasattr(ds, "PatientName"):
                info["patient_name"] = str(ds.PatientName)
            if hasattr(ds, "PixelSpacing") and ds.PixelSpacing:
                info["pixel_spacing"] = (
                    f"{ds.PixelSpacing[0]:.2f} x {ds.PixelSpacing[1]:.2f} mm"
                )
            if hasattr(ds, "SliceThickness"):
                info["slice_thickness"] = f"{ds.SliceThickness} mm"

            return info

        except Exception as e:
            self.logger.error(
                f"[DicomParser.get_series_info] 无法读取文件信息 {file_path}: {e}"
            )
            return {}
