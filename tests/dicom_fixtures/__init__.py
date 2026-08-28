"""Synthetic, de-identified DICOM fixtures for parser tests."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import (
    CTImageStorage,
    ComputedRadiographyImageStorage,
    ExplicitVRLittleEndian,
    JPEGBaseline8Bit,
    JPEG2000Lossless,
    JPEGLSLossless,
    MRImageStorage,
    PositronEmissionTomographyImageStorage,
    RLELossless,
    SecondaryCaptureImageStorage,
    UltrasoundImageStorage,
    UID,
    generate_uid,
)


SOP_CLASS_BY_MODALITY = {
    "CT": CTImageStorage,
    "MR": MRImageStorage,
    "CR": ComputedRadiographyImageStorage,
    "US": UltrasoundImageStorage,
    "PT": PositronEmissionTomographyImageStorage,
}


COMPRESSED_TRANSFER_SYNTAXES = {
    "jpeg_baseline": JPEGBaseline8Bit,
    "jpeg2000_lossless": JPEG2000Lossless,
    "jpeg_ls_lossless": JPEGLSLossless,
    "rle_lossless": RLELossless,
}


def make_dicom_dataset(
    pixel_data: np.ndarray,
    *,
    modality: str = "CT",
    transfer_syntax: UID = ExplicitVRLittleEndian,
    orientation: Sequence[float] | None = (1, 0, 0, 0, 1, 0),
    position: Sequence[float] | None = (0, 0, 0),
    pixel_spacing: Sequence[float] | None = (0.5, 0.5),
    instance_number: int | None = 1,
    slice_location: float | None = None,
    photometric: str = "MONOCHROME2",
    slope: float = 1.0,
    intercept: float = 0.0,
    window_center: float | None = 40.0,
    window_width: float | None = 400.0,
    bits_allocated: int = 16,
) -> FileDataset:
    array = np.asarray(pixel_data)
    if array.ndim == 2:
        rows, cols = array.shape
        number_of_frames = None
    elif array.ndim == 3:
        number_of_frames, rows, cols = array.shape
    else:
        raise ValueError("Only 2D and grayscale 3D multi-frame arrays are supported")

    sop_class_uid = SOP_CLASS_BY_MODALITY.get(modality, SecondaryCaptureImageStorage)
    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = transfer_syntax
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = "Synthetic^Patient"
    ds.PatientID = "SYNTHETIC"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = modality
    ds.SeriesNumber = 1
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = bits_allocated
    ds.BitsStored = bits_allocated
    ds.HighBit = bits_allocated - 1
    ds.PixelRepresentation = 1 if np.issubdtype(array.dtype, np.signedinteger) else 0
    ds.RescaleSlope = slope
    ds.RescaleIntercept = intercept

    if number_of_frames is not None:
        ds.NumberOfFrames = str(number_of_frames)
    if orientation is not None:
        ds.ImageOrientationPatient = list(orientation)
    if position is not None:
        ds.ImagePositionPatient = list(position)
    if pixel_spacing is not None:
        ds.PixelSpacing = list(pixel_spacing)
    if instance_number is not None:
        ds.InstanceNumber = instance_number
    if slice_location is not None:
        ds.SliceLocation = slice_location
    if window_center is not None:
        ds.WindowCenter = window_center
    if window_width is not None:
        ds.WindowWidth = window_width

    if transfer_syntax.is_compressed:
        ds.PixelData = encapsulate([b"not-a-valid-compressed-frame"])
        ds["PixelData"].is_undefined_length = True
    else:
        ds.PixelData = array.tobytes()

    return ds


def write_dicom(path: Path, dataset: FileDataset) -> Path:
    dataset.save_as(path, enforce_file_format=True)
    return path
