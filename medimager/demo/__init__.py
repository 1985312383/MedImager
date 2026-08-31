"""Offline, deterministic example studies shipped with MedImager."""

from medimager.demo.catalog import (
    DemoStudyId,
    DemoStudySpec,
    get_demo_study_spec,
    load_demo_catalog,
)
from medimager.demo.generator import (
    PRODUCTION_PROFILE,
    DemoGenerationProfile,
    generate_demo_study,
    uid_for,
    validate_demo_study,
)
from medimager.demo.manifest import DemoStudyManifest
from medimager.demo.service import (
    DemoBuildResult,
    DemoCacheInfo,
    DemoStudyError,
    DemoStudyService,
)

__all__ = [
    "PRODUCTION_PROFILE",
    "DemoBuildResult",
    "DemoCacheInfo",
    "DemoGenerationProfile",
    "DemoStudyError",
    "DemoStudyId",
    "DemoStudyManifest",
    "DemoStudyService",
    "DemoStudySpec",
    "generate_demo_study",
    "get_demo_study_spec",
    "load_demo_catalog",
    "uid_for",
    "validate_demo_study",
]
