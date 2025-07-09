#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成一个带有完整元数据的 DICOM Gammex 模体文件，用于测试。
Gammex 模体通常用于 CT 扫描仪的质量保证，它包含多个代表不同
组织密度的插件，嵌入在水等效的背景中。
"""
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid
from pathlib import Path
import datetime

def create_circular_mask(center, radius, size):
    """创建一个圆形蒙版"""
    y, x = np.ogrid[:size, :size]
    dist_from_center = np.sqrt((x - center[0])**2 + (y - center[1])**2)
    mask = dist_from_center <= radius
    return mask

def generate_gammex_phantom(size: int = 512) -> np.ndarray:
    """
    生成一个模拟的 Gammex 模体图像。
    布局和HU值参考了 Sun Nuclear Gammex CT 模体。

    Args:
        size (int): 图像的尺寸 (size x size)。

    Returns:
        np.ndarray: 代表 Gammex 模体 HU 值的 NumPy 数组。
    """
    # 1. 初始化背景为空气 (-1000 HU)
    image_data = np.full((size, size), -1000, dtype=np.int16)
    main_center = (size // 2, size // 2)
    
    # 2. 创建模体主体 (PMMA 塑料外壳: ~120 HU)
    main_radius = size // 2 - 15
    image_data[create_circular_mask(main_center, main_radius, size)] = 120
    
    # 在 PMMA 内部填充水 (0 HU)
    water_radius = main_radius - 8 # 假设8个像素的壁厚
    image_data[create_circular_mask(main_center, water_radius, size)] = 0

    # 3. 定义插件参数 (名称, HU 值)
    # 将插件放置在一个圆环上
    insert_ring_radius = main_radius * 0.55
    num_inserts = 8
    insert_radius_pixels = 20 # 插件的半径
    
    inserts = [
        # (名称, HU 值) - 基于常见CT值估算
        ("Air",          -1000),
        ("Adipose",        -90),
        ("Brain",           40),
        ("Iodine 5mg/ml",  130),
        ("Calcium 50mg/ml",150),
        ("Iodine 10mg/ml", 280),
        ("Calcium 100mg/ml",300),
        ("Calcium 300mg/ml",850),
    ]

    # 4. 在图像中绘制一圈插件
    for i, (name, hu_value) in enumerate(inserts):
        angle = (i / num_inserts) * 2 * np.pi
        dx = int(insert_ring_radius * np.cos(angle))
        dy = int(insert_ring_radius * np.sin(angle))
        insert_center = (main_center[0] + dx, main_center[1] + dy)
        mask = create_circular_mask(insert_center, insert_radius_pixels, size)
        image_data[mask] = hu_value

    # 5. 在中心放置一个 "True Water" 插件作为参考
    center_insert_hu = 0
    center_insert_radius = 25
    mask = create_circular_mask(main_center, center_insert_radius, size)
    image_data[mask] = center_insert_hu
    
    # 6. 添加轻微的噪声
    noise = np.random.normal(0, 10, (size, size)).astype(np.int16)
    image_data += noise
    
    return image_data

def create_gammex_phantom_dcm(output_dir: Path, num_slices: int) -> None:
    """
    生成并保存一个 DICOM 格式的 Gammex 模体图像序列。

    Args:
        output_dir (Path): 保存 .dcm 文件的目录。
        num_slices (int): 要生成的切片数量。
    """
    print(f"开始生成 DICOM Gammex 模体序列，将保存至: {output_dir}")
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
        ds.PatientName = "PHANTOM^GAMMEX"
        ds.PatientID = "Phantom_GMX_001"
        ds.PatientBirthDate = "19700101"
        ds.PatientSex = "O"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.StudyID = "STUDY_GMX_001"
        ds.SeriesNumber = 1
        ds.AcquisitionNumber = slice_num
        ds.InstanceNumber = slice_num

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
        ds.StudyDescription = "Gammex Phantom Test"
        ds.SeriesDescription = "Axial Gammex-like Phantom"

        # 图像方向和位置 (关键：更新 SliceLocation)
        slice_thickness = 2.0
        ds.ImagePositionPatient = [0, 0, i * slice_thickness]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.SliceLocation = str(i * slice_thickness)
        ds.SliceThickness = slice_thickness

        # 像素和扫描参数
        image_size = 512
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = image_size
        ds.Columns = image_size
        ds.PixelSpacing = [0.5, 0.5]
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1  # 1 = signed integer
        
        # 窗宽窗位 (可以根据内容调整)
        ds.WindowCenter = 40
        ds.WindowWidth = 400
        
        # 斜率和截距
        ds.RescaleIntercept = 0.0
        ds.RescaleSlope = 1.0

        # SOP
        ds.SOPClassUID = pydicom.uid.CTImageStorage
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        
        ds.is_little_endian = True
        ds.is_implicit_VR = False

        # --- 5. 生成像素数据 ---
        image_data = generate_gammex_phantom(size=512)
        # 添加一个移动的标记点
        marker_pos_x = 200 + i * 10
        image_data[255:258, marker_pos_x:marker_pos_x+3] = 3000 # 高密度点
        ds.PixelData = image_data.tobytes()

        # --- 6. 保存文件 ---
        output_filename = output_dir / f"gammex_slice_{slice_num:03d}.dcm"
        try:
            pydicom.dcmwrite(str(output_filename), ds, write_like_original=False)
        except Exception as e:
            print(f"保存 DICOM 文件 {output_filename} 时出错: {e}")

    print(f"序列已成功生成完毕。")

def main():
    """主函数，生成并保存模体"""
    print("开始生成 Gammex 模体 DICOM 序列...")
    
    # 脚本位于 medimager/tests/scripts/
    # 输出目录为 medimager/tests/dcm/gammex_phantom/
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir.parent / "dcm" / "gammex_phantom"
    
    # 清理旧文件
    if output_dir.exists():
        for f in output_dir.glob("*.dcm"):
            f.unlink()

    create_gammex_phantom_dcm(output_dir, num_slices=10)

if __name__ == '__main__':
    main() 