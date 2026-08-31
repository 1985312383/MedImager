"""Versioned manifests for generated example-study caches."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from medimager.demo.catalog import DemoStudyId


MANIFEST_SCHEMA = "medimager.demo_study"
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class DemoFileManifest:
    relative_path: str
    sop_instance_uid: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class DemoSeriesManifest:
    role: str
    series_instance_uid: str
    relative_path: str
    modality: str
    instances: int
    pixel_sha256: str
    expected_geometry_status: str
    expected_reason_key: str
    files: tuple[DemoFileManifest, ...]


@dataclass(frozen=True)
class DemoStudyManifest:
    study_id: DemoStudyId
    study_instance_uid: str
    generator_version: str
    profile: dict[str, Any]
    series: tuple[DemoSeriesManifest, ...]
    disk_bytes: int
    semantic_digest: str = ""
    complete: bool = True
    schema: str = MANIFEST_SCHEMA
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def with_digest(self) -> "DemoStudyManifest":
        payload = self.to_dict()
        payload["semantic_digest"] = ""
        digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        return replace(self, semantic_digest=digest)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["study_id"] = self.study_id.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DemoStudyManifest":
        if payload.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("Unsupported demo manifest schema")
        if int(payload.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported demo manifest schema version")
        files_by_series = []
        for item in payload.get("series", []):
            files = tuple(DemoFileManifest(**entry) for entry in item.get("files", []))
            files_by_series.append(
                DemoSeriesManifest(
                    role=str(item["role"]),
                    series_instance_uid=str(item["series_instance_uid"]),
                    relative_path=str(item["relative_path"]),
                    modality=str(item["modality"]),
                    instances=int(item["instances"]),
                    pixel_sha256=str(item["pixel_sha256"]),
                    expected_geometry_status=str(item["expected_geometry_status"]),
                    expected_reason_key=str(item["expected_reason_key"]),
                    files=files,
                )
            )
        return cls(
            study_id=DemoStudyId(payload["study_id"]),
            study_instance_uid=str(payload["study_instance_uid"]),
            generator_version=str(payload["generator_version"]),
            profile=dict(payload.get("profile", {})),
            series=tuple(files_by_series),
            disk_bytes=int(payload.get("disk_bytes", 0)),
            semantic_digest=str(payload.get("semantic_digest", "")),
            complete=bool(payload.get("complete", False)),
            schema=str(payload["schema"]),
            schema_version=int(payload["schema_version"]),
        )

    @classmethod
    def read(cls, root: Path) -> "DemoStudyManifest":
        payload = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    def write(self, root: Path) -> Path:
        path = root / MANIFEST_FILENAME
        temporary = root / f".{MANIFEST_FILENAME}.tmp"
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def digest_is_valid(self) -> bool:
        return (
            bool(self.semantic_digest)
            and self.with_digest().semantic_digest == self.semantic_digest
        )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
