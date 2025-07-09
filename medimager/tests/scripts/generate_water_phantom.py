#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成一个带有完整元数据的 DICOM 水模文件，用于测试。
"""

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid
from pathlib import Path
import datetime

def generate_water_phantom_pixels(size: int = 512) -> np.ndarray:
    """
    生成水模的原始像素数据。

    Args:
        size (int): 图像的边长。

    Returns:
        np.ndarray: 代表水模HU值的NumPy数组。
    """
    center = size // 2
    y, x = np.ogrid[:size, :size]
    distances = np.sqrt((x - center) ** 2 + (y - center) ** 2)

    # 参数
    outer_radius = size // 2 - 20
    wall_thickness = 8
    inner_radius = outer_radius - wall_thickness

    # 1. 初始化为空气 (-1000 HU)
    image_data = np.full((size, size), -1000, dtype=np.int16)

    # 2. 填充 PMMA 薄壁 (120 HU)
    pmma_mask = (distances > inner_radius) & (distances <= outer_radius)
    image_data[pmma_mask] = 120

    # 3. 填充水 (0 HU)
    water_mask = distances <= inner_radius
    image_data[water_mask] = 0

    # 添加噪声
    noise = np.random.normal(0, 5, (size, size)).astype(np.int16)
    image_data += noise
    
    return image_data

def create_water_phantom_dcm(output_path: Path) -> None:
    """
    生成并保存一个 DICOM 格式的水模图像。

    Args:
        output_path (Path): 保存 .dcm 文件的完整路径。
    """
    print(f"开始生成 DICOM 水模文件，将保存至: {output_path}")

    # --- 1. 文件元信息 ---
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    file_meta.ImplementationVersionName = "MedImager_PhantomGen_v1"

    # --- 2. 主数据集 ---
    ds = Dataset()
    ds.file_meta = file_meta

    # --- 3. 患者与研究信息 ---
    ds.PatientName = "PHANTOM^WATER"
    ds.PatientID = "Phantom_001"
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "O"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyID = "STUDY_001"
    ds.SeriesNumber = 1
    ds.AcquisitionNumber = 1
    ds.InstanceNumber = 1

    # 日期和时间
    now = datetime.datetime.now()
    ds.StudyDate = now.strftime('%Y%m%d')
    ds.SeriesDate = now.strftime('%Y%m%d')
    ds.AcquisitionDate = now.strftime('%Y%m%d')
    ds.ContentDate = now.strftime('%Y%m%d')
    ds.StudyTime = now.strftime('%H%M%S.%f')
    ds.SeriesTime = now.strftime('%H%M%S.%f')
    ds.AcquisitionTime = now.strftime('%H%M%S.%f')
    ds.ContentTime = now.strftime('%H%M%S.%f')

    # --- 4. 图像参数 ---
    ds.Modality = "CT"
    ds.Manufacturer = "MedImager Inc."
    ds.InstitutionName = "MedImager Test Facility"
    ds.StudyDescription = "Water Phantom Test"
    ds.SeriesDescription = "Axial Water Phantom"

    # 图像方向和位置
    ds.ImagePositionPatient = [0, 0, 0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.SliceLocation = "0.0"

    # 像素和扫描参数
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 512
    ds.Columns = 512
    ds.PixelSpacing = [0.5, 0.5]
    ds.SliceThickness = 1.0
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1  # 1 = signed integer
    
    # 窗宽窗位
    ds.WindowCenter = 0
    ds.WindowWidth = 100
    
    # 斜率和截距 (HU = pixel_value * RescaleSlope + RescaleIntercept)
    ds.RescaleIntercept = 0.0
    ds.RescaleSlope = 1.0

    # SOP (Service-Object Pair)
    ds.SOPClassUID = pydicom.uid.CTImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # --- 5. 生成像素数据 ---
    image_data = generate_water_phantom_pixels()
    ds.PixelData = image_data.tobytes()

    # --- 6. 保存文件 ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        pydicom.dcmwrite(str(output_path), ds, write_like_original=False)
        print(f"文件已成功保存到: {output_path}")
    except Exception as e:
        print(f"保存 DICOM 文件时出错: {e}")

def create_water_phantom_dcm_series(output_dir: Path, num_slices: int) -> None:
    """
    生成并保存一个 DICOM 格式的水模图像序列。

    Args:
        output_dir (Path): 保存 .dcm 文件的目录。
        num_slices (int): 要生成的切片数量。
    """
    print(f"开始生成 DICOM 水模序列，将保存至: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 为整个序列生成一次性的 UID
    study_uid = generate_uid()
    series_uid = generate_uid()

    # --- 循环生成每个切片 ---
    for i in range(num_slices):
        slice_num = i + 1
        print(f"  正在生成切片 {slice_num}/{num_slices}...")

        # --- 1. 文件元信息 ---
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid() # 每个文件必须是唯一的
        file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = generate_uid()
        file_meta.ImplementationVersionName = "MedImager_PhantomGen_v2"

        # --- 2. 主数据集 ---
        ds = Dataset()
        ds.file_meta = file_meta

        # --- 3. 患者与研究信息 ---
        ds.PatientName = "PHANTOM^WATER"
        ds.PatientID = "Phantom_001"
        ds.PatientBirthDate = "19700101"
        ds.PatientSex = "O"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.StudyID = "STUDY_001"
        ds.SeriesNumber = 1
        ds.AcquisitionNumber = slice_num
        ds.InstanceNumber = slice_num
        
        # ... (日期时间部分省略) ...

        # --- 4. 图像参数 ---
        ds.Modality = "CT"
        ds.Manufacturer = "MedImager Inc."
        ds.InstitutionName = "MedImager Test Facility"
        ds.StudyDescription = "Water Phantom Test"
        ds.SeriesDescription = "Axial Water Phantom"

        # 图像方向和位置 (关键：更新 SliceLocation)
        slice_thickness = 2.0
        ds.ImagePositionPatient = [0, 0, i * slice_thickness]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.SliceLocation = str(i * slice_thickness)
        ds.SliceThickness = slice_thickness

        # 像素和扫描参数
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = 512
        ds.Columns = 512
        ds.PixelSpacing = [0.5, 0.5]
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1  # 1 = signed integer
        
        # 窗宽窗位
        ds.WindowCenter = 0
        ds.WindowWidth = 100
        
        # 斜率和截距
        ds.RescaleIntercept = 0.0
        ds.RescaleSlope = 1.0

        # SOP
        ds.SOPClassUID = pydicom.uid.CTImageStorage
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        
        ds.is_little_endian = True
        ds.is_implicit_VR = False

        # --- 5. 生成像素数据 ---
        image_data = generate_water_phantom_pixels()
        ds.PixelData = image_data.tobytes()

        # --- 6. 保存文件 ---
        output_filename = output_dir / f"water_phantom_slice_{slice_num:03d}.dcm"
        try:
            pydicom.dcmwrite(str(output_filename), ds, write_like_original=False)
        except Exception as e:
            print(f"保存 DICOM 文件 {output_filename} 时出错: {e}")
            
    print(f"序列已成功生成完毕。")


if __name__ == '__main__':
    # 脚本位于 medimager/tests/scripts/
    # 输出目录为 medimager/tests/dcm/water_phantom/
    script_dir = Path(__file__).parent
    output_dir = script_dir.parent / "dcm" / "water_phantom"
    
    # 清理旧文件
    if output_dir.exists():
        for f in output_dir.glob("*.dcm"):
            f.unlink()
    else:
        # 如果是单个文件，也清理掉
        legacy_file = script_dir.parent / "dcm" / "water_phantom.dcm"
        if legacy_file.exists():
            legacy_file.unlink()

    create_water_phantom_dcm_series(output_dir, num_slices=10) 