from __future__ import annotations

import json
import threading
import tomllib
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pydicom
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from pydicom.uid import ExplicitVRLittleEndian

import medimager.demo.service as demo_service_module
from medimager.core.image_data_model import ImageDataModel
from medimager.core.volume_geometry import GeometryStatus, VolumeBuilder
from medimager.demo import (
    DemoGenerationProfile,
    DemoStudyError,
    DemoStudyId,
    DemoStudyService,
    generate_demo_study,
    get_demo_study_spec,
    load_demo_catalog,
    uid_for,
    validate_demo_study,
)
from medimager.demo.generator import DemoGenerationCancelled
from medimager.demo.preview_builder import PREVIEW_SIZE, build_preview_assets


SMALL_PROFILE = DemoGenerationProfile(
    ct_shape_zyx=(8, 32, 32),
    ct_coronal_slices=8,
    mr_shape_zyx=(8, 32, 32),
    geometry_shape_zyx=(8, 24, 24),
    random_seed=260,
)


def _series_files(root: Path, series) -> list[str]:
    return [str(root / item.relative_path) for item in series.files]


def test_catalog_has_all_studies_and_resolvable_preview_resources():
    catalog = load_demo_catalog()

    assert {spec.id for spec in catalog} == set(DemoStudyId)
    assert all(spec.preview_path.is_file() for spec in catalog)
    assert all(spec.preview_path.suffix == ".png" for spec in catalog)
    assert all(spec.estimated_bytes > 0 for spec in catalog)
    assert sum(spec.estimated_bytes for spec in catalog) <= 24 * 1024 * 1024
    assert sum(spec.preview_path.stat().st_size for spec in catalog) <= 512 * 1024
    for spec in catalog:
        with Image.open(spec.preview_path) as preview:
            assert preview.format == "PNG"
            assert preview.size == PREVIEW_SIZE


def test_preview_builder_is_deterministic(tmp_path):
    first = build_preview_assets(tmp_path / "first")
    second = build_preview_assets(tmp_path / "second")

    assert [path.name for path in first] == [path.name for path in second]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]


def test_demo_assets_are_packaged_and_legacy_binary_phantoms_are_absent():
    project_root = Path(__file__).parents[1]
    project = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_data = project["tool"]["setuptools"]["package-data"]["medimager"]

    assert "demo/catalog.json" in package_data
    assert "demo/previews/*.png" in package_data
    spec_text = (project_root / "MedImager.spec").read_text(encoding="utf-8")
    assert "medimager\\\\demo\\\\catalog.json" in spec_text
    assert "medimager\\\\demo\\\\previews" in spec_text

    legacy_root = project_root / "medimager" / "tests"
    assert not tuple((legacy_root / "dcm").rglob("*.dcm"))
    assert not tuple((legacy_root / "scripts").glob("generate_*_phantom.py"))


def test_uid_for_is_deterministic_valid_and_name_scoped():
    first = uid_for("ct_multiphase:study")

    assert first == uid_for("ct_multiphase:study")
    assert first != uid_for("mr_brain:study")
    assert first.startswith("2.25.")
    assert len(first) <= 64


def test_ct_generation_is_byte_deterministic_and_spatially_linked(tmp_path):
    spec = get_demo_study_spec(DemoStudyId.CT_MULTIPHASE)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first = generate_demo_study(spec, first_root, profile=SMALL_PROFILE)
    second = generate_demo_study(spec, second_root, profile=SMALL_PROFILE)

    assert first.semantic_digest == second.semantic_digest
    assert [series.pixel_sha256 for series in first.series] == [
        series.pixel_sha256 for series in second.series
    ]
    assert [item.sha256 for series in first.series for item in series.files] == [
        item.sha256 for series in second.series for item in series.files
    ]
    assert validate_demo_study(first_root, spec).valid
    assert first.disk_bytes < spec.estimated_bytes

    noncontrast = first.series[0]
    arterial = first.series[1]
    nc_dataset = pydicom.dcmread(_series_files(first_root, noncontrast)[4])
    arterial_dataset = pydicom.dcmread(_series_files(first_root, arterial)[4])
    assert nc_dataset.FrameOfReferenceUID == arterial_dataset.FrameOfReferenceUID
    assert nc_dataset.StudyInstanceUID == arterial_dataset.StudyInstanceUID
    assert nc_dataset.PatientIdentityRemoved == "YES"
    assert nc_dataset.BurnedInAnnotation == "NO"
    assert not np.array_equal(nc_dataset.pixel_array, arterial_dataset.pixel_array)


@pytest.mark.parametrize(
    "study_id",
    [DemoStudyId.MR_BRAIN, DemoStudyId.GEOMETRY_LAB],
)
def test_all_demo_builders_have_stable_manifests_and_file_order(tmp_path, study_id):
    spec = get_demo_study_spec(study_id)
    first = generate_demo_study(spec, tmp_path / "first", profile=SMALL_PROFILE)
    second = generate_demo_study(spec, tmp_path / "second", profile=SMALL_PROFILE)

    assert first.to_dict() == second.to_dict()
    assert [item.relative_path for series in first.series for item in series.files] == [
        item.relative_path for series in second.series for item in series.files
    ]


@pytest.mark.parametrize("study_id", list(DemoStudyId))
def test_every_demo_series_uses_fixed_deidentified_explicit_vr_metadata(
    tmp_path,
    study_id,
):
    spec = get_demo_study_spec(study_id)
    manifest = generate_demo_study(spec, tmp_path, profile=SMALL_PROFILE)

    for series in manifest.series:
        dataset = pydicom.dcmread(
            _series_files(tmp_path, series)[0],
            stop_before_pixels=True,
        )
        assert dataset.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
        assert dataset.PatientIdentityRemoved == "YES"
        assert dataset.BurnedInAnnotation == "NO"
        assert dataset.DeidentificationMethod == "Fully synthetic; no source patient"
        assert dataset.StudyDate == "20260115"
        assert dataset.StudyInstanceUID.startswith("2.25.")
        assert dataset.SeriesInstanceUID.startswith("2.25.")
        assert dataset.SOPInstanceUID.startswith("2.25.")


def test_mr_generation_exposes_neuro_roles_and_shared_geometry(tmp_path):
    spec = get_demo_study_spec(DemoStudyId.MR_BRAIN)
    manifest = generate_demo_study(spec, tmp_path, profile=SMALL_PROFILE)

    assert [series.role for series in manifest.series] == [
        "mr_t1_mprage",
        "mr_t2_tse",
        "mr_flair",
        "mr_dwi_b1000",
    ]
    first_datasets = [
        pydicom.dcmread(_series_files(tmp_path, series)[0])
        for series in manifest.series
    ]
    assert {dataset.Modality for dataset in first_datasets} == {"MR"}
    assert len({dataset.FrameOfReferenceUID for dataset in first_datasets}) == 1
    assert len({dataset.SeriesInstanceUID for dataset in first_datasets}) == 4
    assert [dataset.SeriesDescription for dataset in first_datasets] == [
        "3D T1 MPRAGE",
        "T2 TSE",
        "Ax FLAIR",
        "DWI b1000",
    ]


def test_geometry_lab_manifest_matches_volume_builder_diagnostics(tmp_path, qapp):
    spec = get_demo_study_spec(DemoStudyId.GEOMETRY_LAB)
    manifest = generate_demo_study(spec, tmp_path, profile=SMALL_PROFILE)

    results = {}
    for series in manifest.series:
        model = ImageDataModel()
        assert model.load_dicom_series(_series_files(tmp_path, series))
        inspection = VolumeBuilder.inspect(model)
        results[series.role] = inspection
        assert inspection.detail == series.expected_reason_key
        if series.expected_geometry_status == "compatible":
            assert inspection.status is GeometryStatus.COMPATIBLE
        else:
            assert inspection.status is not GeometryStatus.COMPATIBLE

    assert results["geometry_reversed_order"].status is GeometryStatus.COMPATIBLE
    assert results["geometry_regular_oblique"].status is GeometryStatus.COMPATIBLE
    frame_a = pydicom.dcmread(
        _series_files(
            tmp_path,
            next(
                item
                for item in manifest.series
                if item.role == "geometry_different_for_a"
            ),
        )[0],
        stop_before_pixels=True,
    ).FrameOfReferenceUID
    frame_b = pydicom.dcmread(
        _series_files(
            tmp_path,
            next(
                item
                for item in manifest.series
                if item.role == "geometry_different_for_b"
            ),
        )[0],
        stop_before_pixels=True,
    ).FrameOfReferenceUID
    assert frame_a != frame_b
    assert [item.role for item in manifest.series[:4]] == [
        "geometry_regular_axial",
        "geometry_reversed_order",
        "geometry_anisotropic",
        "geometry_regular_oblique",
    ]
    assert all(
        item.expected_geometry_status == "rejected" for item in manifest.series[4:10]
    )
    assert [item.role for item in manifest.series[10:]] == [
        "geometry_different_for_a",
        "geometry_different_for_b",
    ]


def test_cancelled_generation_never_writes_a_complete_manifest(tmp_path):
    spec = get_demo_study_spec(DemoStudyId.CT_MULTIPHASE)
    completed = 0

    def on_progress(current: int, _total: int) -> None:
        nonlocal completed
        completed = current

    with pytest.raises(DemoGenerationCancelled):
        generate_demo_study(
            spec,
            tmp_path,
            progress=on_progress,
            cancelled=lambda: completed >= 1,
            profile=SMALL_PROFILE,
        )

    assert not (tmp_path / "manifest.json").exists()


def test_service_reuses_cache_repairs_corruption_and_clears_it(
    tmp_path,
    qapp,
    monkeypatch,
):
    executor = ThreadPoolExecutor(max_workers=2)
    service = DemoStudyService(
        tmp_path / "cache",
        executor=executor,
        profile=SMALL_PROFILE,
    )
    try:
        first_future = service.ensure_ready(DemoStudyId.CT_MULTIPHASE)
        assert service.ensure_ready(DemoStudyId.CT_MULTIPHASE) is first_future
        first = first_future.result(timeout=15)
        assert first.generated
        assert service.cache_info().ready_studies == (DemoStudyId.CT_MULTIPHASE,)

        manifest_mtime = (first.root / "manifest.json").stat().st_mtime_ns
        with monkeypatch.context() as cache_hit_patch:
            cache_hit_patch.setattr(
                demo_service_module,
                "generate_demo_study",
                lambda *_args, **_kwargs: pytest.fail("cache hit regenerated data"),
            )
            cached = service.ensure_ready(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        assert not cached.generated
        assert cached.root == first.root
        assert (cached.root / "manifest.json").stat().st_mtime_ns == manifest_mtime

        victim = cached.root / cached.manifest.series[0].files[0].relative_path
        victim.write_bytes(victim.read_bytes() + b"corrupt")
        repaired = service.ensure_ready(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        assert repaired.generated
        assert validate_demo_study(
            repaired.root, get_demo_study_spec(repaired.study_id)
        ).valid

        freed = service.clear_cache(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        assert freed > 0
        assert not repaired.root.exists()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_service_cancels_a_queued_request_without_creating_cache(tmp_path, qapp):
    executor = ThreadPoolExecutor(max_workers=1)
    blocker_release = threading.Event()
    blocker = executor.submit(blocker_release.wait)
    service = DemoStudyService(
        tmp_path / "cache",
        executor=executor,
        profile=SMALL_PROFILE,
    )
    try:
        future = service.ensure_ready(DemoStudyId.MR_BRAIN)
        assert service.cancel(DemoStudyId.MR_BRAIN)
        blocker_release.set()
        blocker.result(timeout=5)
        with pytest.raises(CancelledError):
            future.result(timeout=5)
        assert not (service.cache_root / DemoStudyId.MR_BRAIN.value).exists()
    finally:
        blocker_release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_service_cancels_active_generation_and_removes_only_staging(tmp_path, qapp):
    executor = ThreadPoolExecutor(max_workers=1)
    service = DemoStudyService(
        tmp_path / "cache",
        executor=executor,
        profile=SMALL_PROFILE,
    )

    def cancel_after_first(study_id: str, current: int, _total: int) -> None:
        if current >= 1:
            service.cancel(study_id)

    service.progress.connect(
        cancel_after_first,
        Qt.ConnectionType.DirectConnection,
    )
    try:
        future = service.ensure_ready(DemoStudyId.MR_BRAIN)
        with pytest.raises(DemoGenerationCancelled):
            future.result(timeout=15)
        assert not (service.cache_root / DemoStudyId.MR_BRAIN.value).exists()
        assert not list(service.cache_root.glob(".staging-*"))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_service_disk_preflight_fails_without_allocating_staging(
    tmp_path,
    qapp,
    monkeypatch,
):
    executor = ThreadPoolExecutor(max_workers=1)
    service = DemoStudyService(
        tmp_path / "cache",
        executor=executor,
        profile=SMALL_PROFILE,
    )
    monkeypatch.setattr(
        demo_service_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )
    try:
        with pytest.raises(DemoStudyError) as raised:
            service.ensure_ready(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        assert raised.value.code == "demo.insufficient_disk_space"
        assert not list(service.cache_root.glob(".staging-*"))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_service_unwritable_cache_root_is_localised(tmp_path, qapp, monkeypatch):
    cache_root = tmp_path / "unwritable"
    executor = ThreadPoolExecutor(max_workers=1)
    service = DemoStudyService(
        cache_root,
        executor=executor,
        profile=SMALL_PROFILE,
    )
    original_mkdir = Path.mkdir

    def reject_cache_root(path: Path, *args, **kwargs):
        if path == cache_root:
            raise OSError("synthetic permission failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", reject_cache_root)
    try:
        with pytest.raises(DemoStudyError) as raised:
            service.ensure_ready(DemoStudyId.MR_BRAIN).result(timeout=15)
        assert raised.value.code == "demo.cache_unavailable"
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_failed_atomic_promotion_restores_previous_valid_cache(
    tmp_path,
    qapp,
    monkeypatch,
):
    executor = ThreadPoolExecutor(max_workers=1)
    service = DemoStudyService(
        tmp_path / "cache",
        executor=executor,
        profile=SMALL_PROFILE,
    )
    try:
        first = service.ensure_ready(DemoStudyId.CT_MULTIPHASE).result(timeout=15)
        original_digest = first.manifest.semantic_digest
        original_replace = Path.replace

        def reject_staging_promotion(source: Path, target: Path):
            if source.name.startswith(".staging-"):
                raise OSError("synthetic promotion failure")
            return original_replace(source, target)

        monkeypatch.setattr(Path, "replace", reject_staging_promotion)
        with pytest.raises(DemoStudyError) as raised:
            service.ensure_ready(
                DemoStudyId.CT_MULTIPHASE,
                force=True,
            ).result(timeout=15)
        assert raised.value.code == "demo.generation_failed"

        restored = validate_demo_study(
            first.root,
            get_demo_study_spec(DemoStudyId.CT_MULTIPHASE),
        )
        assert restored.valid
        assert restored.manifest is not None
        assert restored.manifest.semantic_digest == original_digest
        assert not list(service.cache_root.glob(".staging-*"))
        assert not list(service.cache_root.glob(".replaced-*"))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_manifest_tampering_and_file_corruption_are_rejected(tmp_path):
    spec = get_demo_study_spec(DemoStudyId.MR_BRAIN)
    manifest = generate_demo_study(spec, tmp_path, profile=SMALL_PROFILE)
    manifest_path = tmp_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["study_instance_uid"] = uid_for("tampered")
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_demo_study(tmp_path, spec).reason == "demo.manifest_digest_mismatch"

    manifest.write(tmp_path)
    victim = tmp_path / manifest.series[0].files[0].relative_path
    victim.write_bytes(victim.read_bytes()[:-1])
    assert validate_demo_study(tmp_path, spec).reason == "demo.file_size_mismatch"
