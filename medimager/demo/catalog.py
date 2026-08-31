"""Stable catalog for the offline MedImager example studies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from medimager.core.hanging_protocols import HangingProtocolId
from medimager.utils.resource_path import get_resource_path


CATALOG_SCHEMA = "medimager.demo_catalog"
CATALOG_SCHEMA_VERSION = 1
GENERATOR_VERSION = "2.6.0"


class DemoStudyId(StrEnum):
    """Identifiers persisted by the catalog and command-line integration."""

    CT_MULTIPHASE = "ct_multiphase"
    MR_BRAIN = "mr_brain"
    GEOMETRY_LAB = "geometry_lab"


@dataclass(frozen=True)
class DemoStudySpec:
    """UI-neutral description of one generated example study."""

    id: DemoStudyId
    title_key: str
    description_key: str
    preview_resource: str
    estimated_bytes: int
    expected_series_count: int
    default_hanging_protocol: HangingProtocolId
    default_active_role: str
    schema_version: int = CATALOG_SCHEMA_VERSION
    generator_version: str = GENERATOR_VERSION

    @property
    def preview_path(self) -> Path:
        return Path(get_resource_path(f"medimager/demo/{self.preview_resource}"))


def _catalog_path() -> Path:
    return Path(get_resource_path("medimager/demo/catalog.json"))


@lru_cache(maxsize=1)
def load_demo_catalog() -> tuple[DemoStudySpec, ...]:
    """Load and strictly validate the bundled example-study catalog."""

    path = _catalog_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CATALOG_SCHEMA:
        raise ValueError("Unsupported demo catalog schema")
    if int(payload.get("schema_version", 0)) != CATALOG_SCHEMA_VERSION:
        raise ValueError("Unsupported demo catalog schema version")
    if payload.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("Demo catalog and generator versions do not match")

    specs: list[DemoStudySpec] = []
    seen: set[DemoStudyId] = set()
    for item in payload.get("studies", []):
        study_id = DemoStudyId(str(item["id"]))
        if study_id in seen:
            raise ValueError(f"Duplicate demo study id: {study_id}")
        seen.add(study_id)
        spec = DemoStudySpec(
            id=study_id,
            title_key=str(item["title_key"]),
            description_key=str(item["description_key"]),
            preview_resource=str(item["preview_resource"]),
            estimated_bytes=int(item["estimated_bytes"]),
            expected_series_count=int(item["expected_series_count"]),
            default_hanging_protocol=HangingProtocolId(
                str(item["default_hanging_protocol"])
            ),
            default_active_role=str(item["default_active_role"]),
        )
        if spec.estimated_bytes <= 0 or spec.expected_series_count <= 0:
            raise ValueError(f"Invalid resource budget for {study_id}")
        specs.append(spec)

    expected = set(DemoStudyId)
    if seen != expected:
        missing = ", ".join(sorted(item.value for item in expected - seen))
        raise ValueError(f"Demo catalog is incomplete: {missing}")
    return tuple(specs)


def get_demo_study_spec(study_id: DemoStudyId | str) -> DemoStudySpec:
    """Return one catalog entry, accepting the persisted string id."""

    normalized = DemoStudyId(study_id)
    return next(spec for spec in load_demo_catalog() if spec.id is normalized)
