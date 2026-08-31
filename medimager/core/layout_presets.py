"""Versioned layout and hanging-protocol presets for the reading workspace.

The types in this module deliberately contain no Qt objects.  They provide a
stable boundary between the visual layout gallery, workspace persistence and
the existing tuple/dict layout APIs used by :mod:`medimager.ui.main_window`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Optional, Sequence

from medimager.core.hanging_protocols import HangingProtocolId
from medimager.core.multi_series_manager import SeriesInfo


LAYOUT_SCHEMA_VERSION = 1
USER_PRESET_SCHEMA_VERSION = 2
MAX_USER_LAYOUT_PRESETS = 20

_SPECIAL_DEFAULTS: dict[str, dict[str, object]] = {
    "vertical_split": {
        "top_ratio": 0.6,
        "bottom_ratio": 0.5,
        "bottom_split": True,
    },
    "horizontal_split": {
        "left_ratio": 0.6,
        "right_ratio": 0.5,
        "right_split": True,
    },
    "triple_column_right_split": {
        "left_ratio": 0.33,
        "middle_ratio": 0.34,
        "right_split_ratio": 0.5,
        "right_split": True,
    },
    "triple_column_middle_right_split": {
        "left_ratio": 0.33,
        "middle_ratio": 0.34,
        "middle_split_ratio": 0.5,
        "right_split_ratio": 0.5,
        "middle_split": True,
        "right_split": True,
    },
}


@dataclass(frozen=True)
class LayoutSpec:
    """Serializable geometry for a regular or special viewport layout."""

    kind: str = "grid"
    rows: int = 1
    columns: int = 1
    special_type: str = ""
    ratios: tuple[float, ...] = ()
    schema: int = LAYOUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema != LAYOUT_SCHEMA_VERSION:
            raise ValueError(f"unsupported layout schema: {self.schema}")
        if self.kind not in {"grid", "special"}:
            raise ValueError(f"unsupported layout kind: {self.kind}")
        if self.kind == "grid":
            if not (1 <= int(self.rows) <= 3 and 1 <= int(self.columns) <= 4):
                raise ValueError("grid layout must be between 1x1 and 3x4")
        elif self.special_type not in _SPECIAL_DEFAULTS:
            raise ValueError(f"unsupported special layout: {self.special_type}")
        if any(not (0.05 <= float(value) <= 0.95) for value in self.ratios):
            raise ValueError("layout ratios must be between 0.05 and 0.95")

    @classmethod
    def from_legacy(cls, value: object) -> "LayoutSpec":
        """Convert the v2.5 tuple/dict representation to a stable spec."""

        if isinstance(value, LayoutSpec):
            return value
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return cls(kind="grid", rows=int(value[0]), columns=int(value[1]))
        if isinstance(value, Mapping):
            special_type = str(value.get("type", ""))
            if special_type not in _SPECIAL_DEFAULTS:
                rows = int(value.get("rows", 1))
                columns = int(value.get("columns", value.get("cols", 1)))
                return cls(kind="grid", rows=rows, columns=columns)
            ratio_keys = {
                "vertical_split": ("top_ratio", "bottom_ratio"),
                "horizontal_split": ("left_ratio", "right_ratio"),
                "triple_column_right_split": (
                    "left_ratio",
                    "middle_ratio",
                    "right_split_ratio",
                ),
                "triple_column_middle_right_split": (
                    "left_ratio",
                    "middle_ratio",
                    "middle_split_ratio",
                    "right_split_ratio",
                ),
            }[special_type]
            defaults = _SPECIAL_DEFAULTS[special_type]
            ratios = tuple(
                float(value.get(key, defaults[key])) for key in ratio_keys
            )
            return cls(kind="special", special_type=special_type, ratios=ratios)
        raise ValueError(f"invalid layout value: {value!r}")

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> "LayoutSpec":
        return cls(
            schema=int(document.get("schema", LAYOUT_SCHEMA_VERSION)),
            kind=str(document.get("kind", "grid")),
            rows=int(document.get("rows", 1)),
            columns=int(document.get("columns", 1)),
            special_type=str(document.get("special_type", "")),
            ratios=tuple(float(value) for value in document.get("ratios", ())),
        )

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "schema": self.schema,
            "kind": self.kind,
        }
        if self.kind == "grid":
            document.update(rows=self.rows, columns=self.columns)
        else:
            document.update(special_type=self.special_type, ratios=list(self.ratios))
        return document

    def to_legacy(self) -> tuple[int, int] | dict[str, object]:
        if self.kind == "grid":
            return int(self.rows), int(self.columns)
        config = dict(_SPECIAL_DEFAULTS[self.special_type])
        config["type"] = self.special_type
        ratio_keys = {
            "vertical_split": ("top_ratio", "bottom_ratio"),
            "horizontal_split": ("left_ratio", "right_ratio"),
            "triple_column_right_split": (
                "left_ratio",
                "middle_ratio",
                "right_split_ratio",
            ),
            "triple_column_middle_right_split": (
                "left_ratio",
                "middle_ratio",
                "middle_split_ratio",
                "right_split_ratio",
            ),
        }[self.special_type]
        for key, value in zip(ratio_keys, self.ratios):
            config[key] = float(value)
        return config


@dataclass(frozen=True)
class LayoutPreset:
    preset_id: str
    title_key: str
    description_key: str
    icon_name: str
    layout: LayoutSpec
    hanging_protocol: Optional[HangingProtocolId] = None
    builtin: bool = True
    favorite: bool = False
    last_used_at: int = 0


@dataclass(frozen=True)
class LayoutContext:
    active_series_id: Optional[str]
    study_series: tuple[SeriesInfo, ...] = ()
    mpr_available: bool = False
    mpr_reason: str = ""


@dataclass(frozen=True)
class LayoutApplyResult:
    success: bool
    assigned_series: int = 0
    warning_keys: tuple[str, ...] = ()
    error: str = ""


def builtin_layout_presets() -> tuple[LayoutPreset, ...]:
    """Return built-ins in their stable gallery order."""

    clinical = (
        LayoutPreset(
            "study_overview",
            "layoutgallery.study_overview",
            "layoutgallery.study_overview_description",
            "layout-grid.svg",
            LayoutSpec(rows=2, columns=2),
            HangingProtocolId.STUDY_OVERVIEW,
        ),
        LayoutPreset(
            "ct_comparison",
            "layoutgallery.ct_comparison",
            "layoutgallery.ct_comparison_description",
            "compare.svg",
            LayoutSpec(rows=1, columns=2),
            HangingProtocolId.CT_COMPARISON,
        ),
        LayoutPreset(
            "mr_neuro",
            "layoutgallery.mr_neuro",
            "layoutgallery.mr_neuro_description",
            "brain.svg",
            LayoutSpec(rows=2, columns=2),
            HangingProtocolId.MR_NEURO,
        ),
        LayoutPreset(
            "current_mpr",
            "layoutgallery.current_mpr",
            "layoutgallery.current_mpr_description",
            "mpr.svg",
            LayoutSpec(rows=1, columns=1),
            HangingProtocolId.CURRENT_MPR,
        ),
    )
    special = tuple(
        LayoutPreset(
            f"special_{special_type}",
            f"layoutgallery.{special_type}",
            f"layoutgallery.{special_type}_description",
            "layout-special.svg",
            LayoutSpec(kind="special", special_type=special_type),
        )
        for special_type in _SPECIAL_DEFAULTS
    )
    return clinical + special


class LayoutApplicationService:
    """Apply a preset transactionally through injected workspace callbacks."""

    def __init__(
        self,
        *,
        capture: Callable[[], object],
        restore: Callable[[object], None],
        apply_layout: Callable[[LayoutSpec], bool],
        apply_hanging: Callable[[HangingProtocolId], int],
        enter_mpr: Callable[[], bool],
        persist: Callable[[], None],
    ) -> None:
        self._capture = capture
        self._restore = restore
        self._apply_layout = apply_layout
        self._apply_hanging = apply_hanging
        self._enter_mpr = enter_mpr
        self._persist = persist

    def apply(
        self, preset: LayoutPreset, context: LayoutContext
    ) -> LayoutApplyResult:
        snapshot = self._capture()
        try:
            if preset.hanging_protocol is HangingProtocolId.CURRENT_MPR:
                if not context.mpr_available:
                    reason = context.mpr_reason or "mpr_unavailable"
                    return LayoutApplyResult(False, warning_keys=(reason,))
                if not self._enter_mpr():
                    raise RuntimeError("mpr_enter_failed")
                self._persist()
                return LayoutApplyResult(True, assigned_series=1)

            if not self._apply_layout(preset.layout):
                raise RuntimeError("layout_apply_failed")
            assigned = 0
            if preset.hanging_protocol is not None:
                assigned = int(self._apply_hanging(preset.hanging_protocol))
                if context.study_series and assigned <= 0:
                    raise RuntimeError("hanging_assignment_failed")
            self._persist()
            warnings = () if assigned or not context.study_series else ("no_series",)
            return LayoutApplyResult(True, assigned, warnings)
        except Exception as error:
            self._restore(snapshot)
            return LayoutApplyResult(False, error=str(error))


@dataclass
class UserLayoutPresetStore:
    """Settings-backed geometry-only user presets."""

    read: Callable[[str, object], object]
    write: Callable[[str, object], None]
    key: str = "layout_presets.document"
    _cached: list[LayoutPreset] = field(default_factory=list, init=False)

    def load(self) -> tuple[LayoutPreset, ...]:
        document = self.read(self.key, {})
        if not isinstance(document, Mapping):
            return ()
        if int(document.get("schema_version", 0)) > USER_PRESET_SCHEMA_VERSION:
            return ()
        presets: list[LayoutPreset] = []
        for item in document.get("presets", ()):
            if not isinstance(item, Mapping):
                continue
            try:
                preset_id = str(item["preset_id"])
                title = str(item["title"])
                layout = LayoutSpec.from_document(item["layout"])
                presets.append(
                    LayoutPreset(
                        preset_id,
                        title,
                        "",
                        "layout-custom.svg",
                        layout,
                        builtin=False,
                        favorite=_stored_bool(item.get("favorite", False)),
                        last_used_at=_stored_timestamp(item.get("last_used_at", 0)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self._cached = _gallery_order(presets[:MAX_USER_LAYOUT_PRESETS])
        return tuple(self._cached)

    def save(self, title: str, layout: LayoutSpec) -> LayoutPreset:
        normalized = " ".join(str(title).split()).strip()
        if not normalized:
            raise ValueError("layout preset title is required")
        presets = list(self.load())
        if any(item.title_key.casefold() == normalized.casefold() for item in presets):
            raise ValueError("layout preset title already exists")
        if len(presets) >= MAX_USER_LAYOUT_PRESETS:
            raise ValueError("layout preset limit reached")
        import hashlib

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        preset = LayoutPreset(
            f"user_{digest}",
            normalized,
            "",
            "layout-custom.svg",
            layout,
            builtin=False,
        )
        presets.append(preset)
        self._write(presets)
        return preset

    def delete(self, preset_id: str) -> bool:
        presets = list(self.load())
        remaining = [item for item in presets if item.preset_id != preset_id]
        if len(remaining) == len(presets):
            return False
        self._write(remaining)
        return True

    def mark_used(
        self, preset_id: str, *, used_at: Optional[int] = None
    ) -> Optional[LayoutPreset]:
        """Record a successful application and return the updated preset.

        ``used_at`` is an epoch-millisecond value.  It is injectable so tests
        and import tools can produce deterministic ordering without persisting
        any study, series, patient, or viewport identity.
        """

        timestamp = (
            time.time_ns() // 1_000_000
            if used_at is None
            else _validated_timestamp(used_at)
        )
        updated: Optional[LayoutPreset] = None
        presets: list[LayoutPreset] = []
        for item in self.load():
            if item.preset_id == str(preset_id):
                item = replace(item, last_used_at=timestamp)
                updated = item
            presets.append(item)
        if updated is not None:
            self._write(presets)
        return updated

    def toggle_favorite(
        self, preset_id: str, favorite: Optional[bool] = None
    ) -> Optional[LayoutPreset]:
        """Toggle or explicitly set one preset's favorite state."""

        updated: Optional[LayoutPreset] = None
        presets: list[LayoutPreset] = []
        for item in self.load():
            if item.preset_id == str(preset_id):
                enabled = not item.favorite if favorite is None else bool(favorite)
                item = replace(item, favorite=enabled)
                updated = item
            presets.append(item)
        if updated is not None:
            self._write(presets)
        return updated

    def favorites(self) -> tuple[LayoutPreset, ...]:
        """Return favorites, most recently used first."""

        return tuple(item for item in self.load() if item.favorite)

    def recent(self, limit: int = 5) -> tuple[LayoutPreset, ...]:
        """Return successfully used presets in descending use-time order."""

        try:
            requested = int(limit)
        except (TypeError, ValueError) as error:
            raise ValueError("recent layout limit must be an integer") from error
        if requested < 0:
            raise ValueError("recent layout limit must be non-negative")
        ordered = sorted(
            (item for item in self.load() if item.last_used_at > 0),
            key=lambda item: (
                -item.last_used_at,
                item.title_key.casefold(),
                item.preset_id,
            ),
        )
        return tuple(ordered[: min(requested, MAX_USER_LAYOUT_PRESETS)])

    def _write(self, presets: Sequence[LayoutPreset]) -> None:
        user_presets = [item for item in presets if not item.builtin][
            :MAX_USER_LAYOUT_PRESETS
        ]
        document = {
            "schema_version": USER_PRESET_SCHEMA_VERSION,
            "presets": [
                {
                    "preset_id": item.preset_id,
                    "title": item.title_key,
                    "layout": item.layout.to_document(),
                    "favorite": item.favorite,
                    "last_used_at": item.last_used_at,
                }
                for item in user_presets
            ],
        }
        self.write(self.key, document)


def _stored_bool(value: object) -> bool:
    """Coerce old settings defensively without treating ``"false"`` as true."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return False


def _stored_timestamp(value: object) -> int:
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, timestamp)


def _validated_timestamp(value: object) -> int:
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("layout use timestamp must be a non-negative integer") from error
    if timestamp < 0:
        raise ValueError("layout use timestamp must be a non-negative integer")
    return timestamp


def _gallery_order(presets: Sequence[LayoutPreset]) -> list[LayoutPreset]:
    """Order favorites first, then recent use, preserving ties from storage."""

    indexed = list(enumerate(presets))
    indexed.sort(
        key=lambda value: (
            not value[1].favorite,
            -value[1].last_used_at,
            value[0],
        )
    )
    return [item for _index, item in indexed]
