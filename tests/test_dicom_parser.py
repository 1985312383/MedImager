import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset

from medimager.core.dicom_parser import DicomParser
from medimager.core.image_data_model import ImageDataModel
from tests.dicom_fixtures import make_dicom_dataset


def make_ct_dataset(
    value: int,
    *,
    orientation=None,
    position=None,
    slice_location=None,
    instance_number=None,
    slope=1.0,
    intercept=0.0,
    photometric="MONOCHROME2",
):
    ds = Dataset()
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    ds.file_meta = file_meta

    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.RescaleSlope = slope
    ds.RescaleIntercept = intercept
    ds.PixelData = np.full((2, 2), value, dtype=np.int16).tobytes()

    if orientation is not None:
        ds.ImageOrientationPatient = orientation
    if position is not None:
        ds.ImagePositionPatient = position
    if slice_location is not None:
        ds.SliceLocation = slice_location
    if instance_number is not None:
        ds.InstanceNumber = instance_number
    return ds


def test_sort_uses_orientation_and_position_projection():
    parser = DicomParser()
    orientation = [0, 1, 0, 0, 0, 1]  # normal points along patient X
    datasets = [
        make_ct_dataset(20, orientation=orientation, position=[2, 0, 0], instance_number=1),
        make_ct_dataset(0, orientation=orientation, position=[0, 0, 0], instance_number=3),
        make_ct_dataset(10, orientation=orientation, position=[1, 0, 0], instance_number=2),
    ]

    sorted_sets = parser._sort_dicom_slices(datasets)

    assert [int(ds.pixel_array[0, 0]) for ds in sorted_sets] == [0, 10, 20]


def test_sort_falls_back_to_slice_location_then_instance_number():
    parser = DicomParser()

    by_location = [
        make_ct_dataset(20, slice_location=2),
        make_ct_dataset(0, slice_location=0),
        make_ct_dataset(10, slice_location=1),
    ]
    assert [int(ds.pixel_array[0, 0]) for ds in parser._sort_dicom_slices(by_location)] == [0, 10, 20]

    by_instance = [
        make_ct_dataset(20, instance_number=3),
        make_ct_dataset(0, instance_number=1),
        make_ct_dataset(10, instance_number=2),
    ]
    assert [int(ds.pixel_array[0, 0]) for ds in parser._sort_dicom_slices(by_instance)] == [0, 10, 20]


def test_sort_falls_back_when_patient_geometry_tags_are_empty():
    parser = DicomParser()
    datasets = [
        make_ct_dataset(20, slice_location=2),
        make_ct_dataset(0, slice_location=0),
        make_ct_dataset(10, slice_location=1),
    ]
    for ds in datasets:
        ds.ImageOrientationPatient = None
        ds.ImagePositionPatient = None

    sorted_sets = parser._sort_dicom_slices(datasets)

    assert [int(ds.pixel_array[0, 0]) for ds in sorted_sets] == [0, 10, 20]


def test_sort_handles_reverse_file_order_with_non_axial_orientation():
    parser = DicomParser()
    orientation = [0, 1, 0, 0, 0, 1]  # normal points along patient X
    datasets = [
        make_ct_dataset(20, orientation=orientation, position=[2, 0, 0]),
        make_ct_dataset(10, orientation=orientation, position=[1, 0, 0]),
        make_ct_dataset(0, orientation=orientation, position=[0, 0, 0]),
    ]

    sorted_sets = parser._sort_dicom_slices(datasets)

    assert [int(ds.pixel_array[0, 0]) for ds in sorted_sets] == [0, 10, 20]


def test_extract_pixel_data_expands_single_dataset_multiframe_grayscale():
    parser = DicomParser()
    frames = np.arange(12, dtype=np.int16).reshape(3, 2, 2)
    ds = make_dicom_dataset(frames)

    pixel_data = parser._extract_pixel_data([ds])

    assert pixel_data.shape == (3, 2, 2)
    assert np.array_equal(pixel_data, frames.astype(np.float32))


def test_extract_pixel_data_applies_rescale_slope_and_intercept():
    parser = DicomParser()
    ds = make_ct_dataset(50, slope=2.0, intercept=-100.0)

    pixel_data = parser._extract_pixel_data([ds])

    assert pixel_data.shape == (1, 2, 2)
    assert np.all(pixel_data == 0.0)


def test_monochrome1_is_inverted_in_display_pipeline():
    model = ImageDataModel()
    assert model.load_single_image(np.array([[0.0, 100.0]], dtype=np.float32))
    model.dicom_header["PhotometricInterpretation"] = "MONOCHROME1"
    model.set_window(100, 50)

    display = model.get_display_slice()

    assert display.tolist() == [[255, 0]]
