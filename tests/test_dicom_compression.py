import logging

import numpy as np
import pytest
from pydicom.pixels import compress
from pydicom.uid import ExplicitVRLittleEndian

from medimager.core.dicom_parser import DicomParser
from tests.dicom_fixtures import COMPRESSED_TRANSFER_SYNTAXES, make_dicom_dataset


def test_uncompressed_transfer_syntax_decodes_pixels():
    raw = np.arange(4, dtype=np.int16).reshape(2, 2)
    ds = make_dicom_dataset(raw, transfer_syntax=ExplicitVRLittleEndian)
    parser = DicomParser()

    pixel_data = parser._extract_pixel_data([ds])

    assert pixel_data.shape == (1, 2, 2)
    assert np.array_equal(pixel_data[0], raw.astype(np.float32))


@pytest.mark.parametrize("syntax_name,transfer_syntax", sorted(COMPRESSED_TRANSFER_SYNTAXES.items()))
def test_compressed_transfer_syntax_decodes_when_encoder_is_available(
    syntax_name,
    transfer_syntax,
):
    dtype = np.uint8 if "jpeg_baseline" == syntax_name else np.int16
    raw = np.arange(4, dtype=dtype).reshape(2, 2)
    ds = make_dicom_dataset(raw, bits_allocated=raw.dtype.itemsize * 8)

    try:
        compress(ds, transfer_syntax)
    except Exception as e:
        pytest.skip(f"{transfer_syntax.name} encoder unavailable in this environment: {e}")

    parser = DicomParser()
    pixel_data = parser._extract_pixel_data([ds])

    assert pixel_data.shape == (1, 2, 2)
    assert np.array_equal(pixel_data[0], raw.astype(np.float32))


@pytest.mark.parametrize("syntax_name,transfer_syntax", sorted(COMPRESSED_TRANSFER_SYNTAXES.items()))
def test_compressed_transfer_syntax_failure_mentions_decoder_dependency(
    syntax_name,
    transfer_syntax,
    caplog,
):
    ds = make_dicom_dataset(
        np.zeros((2, 2), dtype=np.int16),
        transfer_syntax=transfer_syntax,
    )
    parser = DicomParser()

    with caplog.at_level(logging.ERROR, logger="medimager.core.dicom_parser"):
        pixel_data = parser._extract_pixel_data([ds])

    assert transfer_syntax.is_compressed
    assert pixel_data is None
    assert str(transfer_syntax) in caplog.text
    assert "compressed DICOM pixel data" in caplog.text
    assert "pylibjpeg" in caplog.text or "gdcm" in caplog.text


@pytest.mark.parametrize("syntax_name,transfer_syntax", sorted(COMPRESSED_TRANSFER_SYNTAXES.items()))
def test_compressed_transfer_syntax_registry_marks_cases_as_compressed(
    syntax_name,
    transfer_syntax,
):
    assert transfer_syntax.is_compressed, syntax_name
