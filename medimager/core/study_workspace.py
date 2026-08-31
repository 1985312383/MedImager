"""Privacy-safe, versioned persistence for per-study reading workspaces.

The module is deliberately independent from widgets and from ``MainWindow``.
Callers capture runtime state into :class:`StudyWorkspaceState`, while the
store owns schema migration, history eviction and verified settings writes.

Only one-way hashes of DICOM UIDs are persisted.  Manual registration offsets
are intentionally outside this schema: a manual/both position mode is restored
as automatic LPS synchronization (or disabled when it was manual-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import time
from typing import Any, Mapping, Optional, Protocol, Sequence

from PySide6.QtCore import QPointF

from medimager.core.layout_presets import LayoutSpec
from medimager.core.view_presentation_state import (
    InterpolationMode,
    ViewPresentationState,
)


WORKSPACE_SCHEMA_VERSION = 2
WORKSPACE_DOCUMENT_KEY = "study_workspace.document"
LEGACY_WORKSPACE_KEY = "study_workspace.states"
STUDY_KEY_HEX_LENGTH = 24
SERIES_KEY_HEX_LENGTH = 32
DEFAULT_MAX_HISTORY = 20
MAX_MAX_HISTORY = 100

_HEX_RE = re.compile(r"^[0-9a-f]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SYNC_GROUPS = {
    "all_views",
    "same_patient",
    "same_study",
    "same_modality",
    "custom",
}
_SYNC_MODE_MASK = 0x7F
_MPR_PLANES = frozenset({"axial", "coronal", "sagittal"})
_MPR_LAYOUTS = frozenset({"three_columns", "one_plus_two", "single"})


class WorkspaceSettings(Protocol):
    """The small SettingsManager surface required by the store."""

    def get_setting(self, key: str, default_value: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...

    def remove_setting(self, key: str) -> None: ...

    def save_settings(self) -> None: ...

    def has_setting(self, key: str) -> bool: ...


def _hash_uid(value: object, length: int) -> Optional[str]:
    uid = str(value or "").strip()
    if not uid:
        return None
    return hashlib.sha256(uid.encode("utf-8", "replace")).hexdigest()[:length]


def study_key_for_uid(study_instance_uid: object) -> Optional[str]:
    """Return the stable, 96-bit opaque lookup key for a Study UID."""

    return _hash_uid(study_instance_uid, STUDY_KEY_HEX_LENGTH)


def series_key_for_uid(series_instance_uid: object) -> Optional[str]:
    """Return the stable, 128-bit opaque lookup key for a Series UID."""

    return _hash_uid(series_instance_uid, SERIES_KEY_HEX_LENGTH)


def _is_hash(value: object, length: int) -> bool:
    text = str(value or "")
    return len(text) == length and _HEX_RE.fullmatch(text) is not None


def _safe_id(value: object, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise ValueError("invalid workspace identifier")
    return text


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _strict_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalise_splitter_ratios(
    value: Optional[Mapping[str, Sequence[object]]],
) -> dict[str, tuple[float, ...]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("splitter_ratios must be an object")
    result: dict[str, tuple[float, ...]] = {}
    for raw_name, raw_values in value.items():
        name = _safe_id(raw_name)
        if isinstance(raw_values, (str, bytes)) or not isinstance(
            raw_values, Sequence
        ):
            raise ValueError("splitter ratios must be arrays")
        if not 2 <= len(raw_values) <= 12:
            raise ValueError("splitter ratios must contain 2 to 12 items")
        ratios = tuple(_finite_float(item, "splitter ratio") for item in raw_values)
        if any(item < 0.0 for item in ratios) or sum(ratios) <= 0.0:
            raise ValueError("splitter ratios must be non-negative and non-empty")
        total = sum(ratios)
        result[name] = tuple(item / total for item in ratios)
    return result


@dataclass(frozen=True)
class WorkspaceSyncState:
    """Serializable sync choices; never contains registration transforms."""

    mode: int = 0
    group: str = "same_study"
    position_mode: str = "auto_lps"

    def __post_init__(self) -> None:
        mode = _strict_int(self.mode, "sync mode")
        if mode < 0 or mode & ~_SYNC_MODE_MASK:
            raise ValueError("unsupported sync mode bits")
        group = str(self.group)
        if group not in _SYNC_GROUPS:
            raise ValueError("unsupported sync group")
        if self.position_mode not in {"none", "auto_lps"}:
            raise ValueError("unsupported position sync mode")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "group", group)

    @classmethod
    def from_runtime(
        cls,
        mode: object = 0,
        group: object = "same_study",
        position_mode: object = "auto_lps",
    ) -> "WorkspaceSyncState":
        raw_mode = getattr(mode, "value", mode)
        raw_group = getattr(group, "value", group)
        position = str(position_mode or "none").strip().casefold()
        aliases = {
            "auto": "auto_lps",
            "auto_lps": "auto_lps",
            # The manual half cannot be persisted without its registration
            # transform, so "both" safely retains only automatic LPS sync.
            "both": "auto_lps",
            "manual": "none",
            "none": "none",
            "off": "none",
        }
        return cls(
            mode=int(raw_mode),
            group=str(raw_group),
            position_mode=aliases.get(position, "none"),
        )

    @classmethod
    def from_document(cls, value: object) -> "WorkspaceSyncState":
        if not isinstance(value, Mapping):
            raise ValueError("sync must be an object")
        return cls(
            mode=_strict_int(value.get("mode", 0), "sync mode"),
            group=str(value.get("group", "same_study")),
            position_mode=str(value.get("position_mode", "auto_lps")),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "group": self.group,
            "position_mode": self.position_mode,
        }


@dataclass(frozen=True)
class PresentationSnapshot:
    """A complete, JSON-safe snapshot of ``ViewPresentationState``."""

    series_key: str
    slice_index: int = 0
    window_width: float = 400.0
    window_level: float = 40.0
    use_dicom_voi_lut: bool = False
    voi_lut_index: Optional[int] = None
    zoom: float = 1.0
    pan_center: tuple[float, float] = (0.0, 0.0)
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    inverted: bool = False
    interpolation: str = InterpolationMode.ADAPTIVE.value
    magnifier_enabled: bool = False
    fit_mode: bool = True
    use_physical_pixel_aspect: bool = True

    def __post_init__(self) -> None:
        if not _is_hash(self.series_key, SERIES_KEY_HEX_LENGTH):
            raise ValueError("invalid series key")
        slice_index = max(0, _strict_int(self.slice_index, "slice_index"))
        width = max(1.0, _finite_float(self.window_width, "window_width"))
        level = _finite_float(self.window_level, "window_level")
        zoom = min(
            ViewPresentationState.MAX_ZOOM,
            max(
                ViewPresentationState.MIN_ZOOM,
                _finite_float(self.zoom, "zoom"),
            ),
        )
        if not isinstance(self.pan_center, (tuple, list)) or len(self.pan_center) != 2:
            raise ValueError("pan_center must contain two values")
        pan = (
            _finite_float(self.pan_center[0], "pan_center.x"),
            _finite_float(self.pan_center[1], "pan_center.y"),
        )
        rotation = _strict_int(self.rotation, "rotation")
        rotation = int(round(rotation / 90.0) * 90) % 360
        voi_index = self.voi_lut_index
        if voi_index is not None:
            voi_index = max(0, _strict_int(voi_index, "voi_lut_index"))
        interpolation = InterpolationMode.coerce(self.interpolation).value
        object.__setattr__(self, "slice_index", slice_index)
        object.__setattr__(self, "window_width", width)
        object.__setattr__(self, "window_level", level)
        object.__setattr__(self, "zoom", zoom)
        object.__setattr__(self, "pan_center", pan)
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "voi_lut_index", voi_index)
        object.__setattr__(self, "interpolation", interpolation)

    @classmethod
    def from_view_state(
        cls,
        state: ViewPresentationState,
        *,
        series_uid: object = None,
        series_key: Optional[str] = None,
    ) -> "PresentationSnapshot":
        key = series_key or series_key_for_uid(series_uid)
        if key is None:
            raise ValueError("series_uid or series_key is required")
        return cls(
            series_key=key,
            slice_index=state.slice_index,
            window_width=state.window_width,
            window_level=state.window_level,
            use_dicom_voi_lut=state.use_dicom_voi_lut,
            voi_lut_index=state.voi_lut_index,
            zoom=state.zoom,
            pan_center=(state.pan_center.x(), state.pan_center.y()),
            rotation=state.rotation,
            flip_horizontal=state.flip_horizontal,
            flip_vertical=state.flip_vertical,
            inverted=state.inverted,
            interpolation=state.interpolation.value,
            magnifier_enabled=state.magnifier_enabled,
            fit_mode=state.fit_mode,
            use_physical_pixel_aspect=state.use_physical_pixel_aspect,
        )

    @classmethod
    def from_document(cls, value: object) -> "PresentationSnapshot":
        if not isinstance(value, Mapping):
            raise ValueError("presentation must be an object")
        pan = value.get("pan_center", (0.0, 0.0))
        if isinstance(pan, (str, bytes)) or not isinstance(pan, Sequence):
            raise ValueError("pan_center must be an array")
        return cls(
            series_key=str(value.get("series_key", "")),
            slice_index=_strict_int(value.get("slice_index", 0), "slice_index"),
            window_width=_finite_float(
                value.get("window_width", 400.0), "window_width"
            ),
            window_level=_finite_float(
                value.get("window_level", 40.0), "window_level"
            ),
            use_dicom_voi_lut=_strict_bool(
                value.get("use_dicom_voi_lut", False), "use_dicom_voi_lut"
            ),
            voi_lut_index=(
                None
                if value.get("voi_lut_index") is None
                else _strict_int(value["voi_lut_index"], "voi_lut_index")
            ),
            zoom=_finite_float(value.get("zoom", 1.0), "zoom"),
            pan_center=tuple(pan),
            rotation=_strict_int(value.get("rotation", 0), "rotation"),
            flip_horizontal=_strict_bool(
                value.get("flip_horizontal", False), "flip_horizontal"
            ),
            flip_vertical=_strict_bool(
                value.get("flip_vertical", False), "flip_vertical"
            ),
            inverted=_strict_bool(value.get("inverted", False), "inverted"),
            interpolation=str(value.get("interpolation", "adaptive")),
            magnifier_enabled=_strict_bool(
                value.get("magnifier_enabled", False), "magnifier_enabled"
            ),
            fit_mode=_strict_bool(value.get("fit_mode", True), "fit_mode"),
            use_physical_pixel_aspect=_strict_bool(
                value.get("use_physical_pixel_aspect", True),
                "use_physical_pixel_aspect",
            ),
        )

    def to_view_state(
        self,
        *,
        series_id: Optional[str] = None,
        slice_count: Optional[int] = None,
    ) -> ViewPresentationState:
        state = ViewPresentationState(
            series_id=series_id,
            slice_index=self.slice_index,
            window_width=self.window_width,
            window_level=self.window_level,
            use_dicom_voi_lut=self.use_dicom_voi_lut,
            voi_lut_index=self.voi_lut_index,
            zoom=self.zoom,
            pan_center=QPointF(*self.pan_center),
            rotation=self.rotation,
            flip_horizontal=self.flip_horizontal,
            flip_vertical=self.flip_vertical,
            inverted=self.inverted,
            interpolation=InterpolationMode.coerce(self.interpolation),
            magnifier_enabled=self.magnifier_enabled,
            fit_mode=self.fit_mode,
            use_physical_pixel_aspect=self.use_physical_pixel_aspect,
        )
        state.clamp(slice_count)
        return state

    def to_document(self) -> dict[str, object]:
        return {
            "series_key": self.series_key,
            "slice_index": self.slice_index,
            "window_width": self.window_width,
            "window_level": self.window_level,
            "use_dicom_voi_lut": self.use_dicom_voi_lut,
            "voi_lut_index": self.voi_lut_index,
            "zoom": self.zoom,
            "pan_center": list(self.pan_center),
            "rotation": self.rotation,
            "flip_horizontal": self.flip_horizontal,
            "flip_vertical": self.flip_vertical,
            "inverted": self.inverted,
            "interpolation": self.interpolation,
            "magnifier_enabled": self.magnifier_enabled,
            "fit_mode": self.fit_mode,
            "use_physical_pixel_aspect": self.use_physical_pixel_aspect,
        }


@dataclass(frozen=True)
class MprWorkspaceSnapshot:
    """Optional orthogonal-MPR state retained without forcing MPR entry."""

    series_key: str
    cursor_lps: tuple[float, float, float]
    plane_indices: Mapping[str, int] = field(default_factory=dict)
    layout_mode: str = "three_columns"
    active_plane: str = "axial"
    intersection_lines_visible: bool = True
    views: Mapping[str, PresentationSnapshot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_hash(self.series_key, SERIES_KEY_HEX_LENGTH):
            raise ValueError("invalid MPR series key")
        if (
            isinstance(self.cursor_lps, (str, bytes))
            or not isinstance(self.cursor_lps, Sequence)
            or len(self.cursor_lps) != 3
        ):
            raise ValueError("MPR cursor_lps must contain three values")
        cursor = tuple(
            _finite_float(value, "MPR cursor_lps") for value in self.cursor_lps
        )
        indices: dict[str, int] = {}
        for raw_plane, raw_index in self.plane_indices.items():
            plane = str(raw_plane)
            if plane not in _MPR_PLANES:
                raise ValueError("unsupported MPR plane")
            indices[plane] = max(0, _strict_int(raw_index, "MPR plane index"))
        layout = str(self.layout_mode)
        if layout not in _MPR_LAYOUTS:
            raise ValueError("unsupported MPR layout")
        active = str(self.active_plane)
        if active not in _MPR_PLANES:
            raise ValueError("unsupported active MPR plane")
        visible = _strict_bool(
            self.intersection_lines_visible,
            "MPR intersection_lines_visible",
        )
        views: dict[str, PresentationSnapshot] = {}
        for raw_plane, snapshot in self.views.items():
            plane = str(raw_plane)
            if plane not in _MPR_PLANES:
                raise ValueError("unsupported MPR view plane")
            if (
                not isinstance(snapshot, PresentationSnapshot)
                or snapshot.series_key != self.series_key
            ):
                raise ValueError("invalid MPR view presentation")
            views[plane] = snapshot
        object.__setattr__(self, "cursor_lps", cursor)
        object.__setattr__(self, "plane_indices", indices)
        object.__setattr__(self, "layout_mode", layout)
        object.__setattr__(self, "active_plane", active)
        object.__setattr__(self, "intersection_lines_visible", visible)
        object.__setattr__(self, "views", views)

    @classmethod
    def capture(
        cls,
        *,
        series_uid: object,
        cursor_lps: Sequence[object],
        plane_indices: Optional[Mapping[str, object]] = None,
        views: Optional[Mapping[str, ViewPresentationState]] = None,
        layout_mode: object = "three_columns",
        active_plane: object = "axial",
        intersection_lines_visible: bool = True,
    ) -> "MprWorkspaceSnapshot":
        series_key = series_key_for_uid(series_uid)
        if series_key is None:
            raise ValueError("MPR series_uid is required")
        snapshots = {
            str(plane): PresentationSnapshot.from_view_state(
                state,
                series_key=series_key,
            )
            for plane, state in (views or {}).items()
        }
        return cls(
            series_key=series_key,
            cursor_lps=tuple(cursor_lps),
            plane_indices={
                str(plane): index
                for plane, index in (plane_indices or {}).items()
            },
            layout_mode=str(getattr(layout_mode, "value", layout_mode)),
            active_plane=str(getattr(active_plane, "value", active_plane)),
            intersection_lines_visible=bool(intersection_lines_visible),
            views=snapshots,
        )

    @classmethod
    def from_document(cls, value: object) -> "MprWorkspaceSnapshot":
        if not isinstance(value, Mapping):
            raise ValueError("MPR workspace must be an object")
        raw_cursor = value.get("cursor_lps", ())
        raw_indices = value.get("plane_indices", {})
        raw_views = value.get("views", {})
        if isinstance(raw_cursor, (str, bytes)) or not isinstance(
            raw_cursor, Sequence
        ):
            raise ValueError("MPR cursor_lps must be an array")
        if not isinstance(raw_indices, Mapping) or not isinstance(raw_views, Mapping):
            raise ValueError("MPR indices and views must be objects")
        return cls(
            series_key=str(value.get("series_key", "")),
            cursor_lps=tuple(raw_cursor),
            plane_indices={str(key): item for key, item in raw_indices.items()},
            layout_mode=str(value.get("layout_mode", "three_columns")),
            active_plane=str(value.get("active_plane", "axial")),
            intersection_lines_visible=_strict_bool(
                value.get("intersection_lines_visible", True),
                "MPR intersection_lines_visible",
            ),
            views={
                str(key): PresentationSnapshot.from_document(item)
                for key, item in raw_views.items()
            },
        )

    def to_document(self) -> dict[str, object]:
        return {
            "series_key": self.series_key,
            "cursor_lps": list(self.cursor_lps),
            "plane_indices": dict(sorted(self.plane_indices.items())),
            "layout_mode": self.layout_mode,
            "active_plane": self.active_plane,
            "intersection_lines_visible": self.intersection_lines_visible,
            "views": {
                key: value.to_document()
                for key, value in sorted(self.views.items())
            },
        }


@dataclass(frozen=True)
class StudyWorkspaceState:
    """One persisted study workspace, keyed only by opaque identifiers."""

    study_key: str
    updated_at_ms: int
    layout: LayoutSpec = field(default_factory=LayoutSpec)
    splitter_ratios: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    bindings: Mapping[str, str] = field(default_factory=dict)
    active_viewport: str = ""
    sync: WorkspaceSyncState = field(default_factory=WorkspaceSyncState)
    presentations: Mapping[str, PresentationSnapshot] = field(default_factory=dict)
    mpr: Optional[MprWorkspaceSnapshot] = None

    def __post_init__(self) -> None:
        if not _is_hash(self.study_key, STUDY_KEY_HEX_LENGTH):
            raise ValueError("invalid study key")
        updated = _strict_int(self.updated_at_ms, "updated_at_ms")
        if updated < 0:
            raise ValueError("updated_at_ms must be non-negative")
        if not isinstance(self.layout, LayoutSpec):
            raise ValueError("layout must be a LayoutSpec")
        ratios = _normalise_splitter_ratios(self.splitter_ratios)
        bindings: dict[str, str] = {}
        for raw_view, raw_series in self.bindings.items():
            view = _safe_id(raw_view)
            series = str(raw_series)
            if not _is_hash(series, SERIES_KEY_HEX_LENGTH):
                raise ValueError("invalid series key in bindings")
            bindings[view] = series
        active = _safe_id(self.active_viewport, allow_empty=True)
        presentations: dict[str, PresentationSnapshot] = {}
        for raw_view, snapshot in self.presentations.items():
            view = _safe_id(raw_view)
            if not isinstance(snapshot, PresentationSnapshot):
                raise ValueError("invalid presentation snapshot")
            if bindings.get(view) != snapshot.series_key:
                raise ValueError("presentation does not match its viewport binding")
            presentations[view] = snapshot
        if self.mpr is not None and not isinstance(
            self.mpr, MprWorkspaceSnapshot
        ):
            raise ValueError("invalid MPR workspace snapshot")
        object.__setattr__(self, "updated_at_ms", updated)
        object.__setattr__(self, "splitter_ratios", ratios)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "active_viewport", active)
        object.__setattr__(self, "presentations", presentations)

    @classmethod
    def capture(
        cls,
        *,
        study_instance_uid: object,
        layout: LayoutSpec | object,
        bindings: Mapping[str, object],
        presentations: Optional[Mapping[str, ViewPresentationState]] = None,
        active_viewport: str = "",
        sync: Optional[WorkspaceSyncState] = None,
        splitter_ratios: Optional[Mapping[str, Sequence[object]]] = None,
        mpr: Optional[MprWorkspaceSnapshot] = None,
        updated_at_ms: Optional[int] = None,
    ) -> "StudyWorkspaceState":
        study_key = study_key_for_uid(study_instance_uid)
        if study_key is None:
            raise ValueError("study_instance_uid is required")
        hashed_bindings: dict[str, str] = {}
        for view, uid in bindings.items():
            key = series_key_for_uid(uid)
            if key is not None:
                hashed_bindings[_safe_id(view)] = key
        snapshots: dict[str, PresentationSnapshot] = {}
        for view, state in (presentations or {}).items():
            safe_view = _safe_id(view)
            key = hashed_bindings.get(safe_view)
            if key is None:
                continue
            snapshots[safe_view] = PresentationSnapshot.from_view_state(
                state, series_key=key
            )
        return cls(
            study_key=study_key,
            updated_at_ms=(
                int(time.time() * 1000) if updated_at_ms is None else updated_at_ms
            ),
            layout=LayoutSpec.from_legacy(layout),
            splitter_ratios=splitter_ratios or {},
            bindings=hashed_bindings,
            active_viewport=active_viewport,
            sync=sync or WorkspaceSyncState(),
            presentations=snapshots,
            mpr=mpr,
        )

    @classmethod
    def from_document(
        cls, study_key: str, value: object
    ) -> "StudyWorkspaceState":
        if not isinstance(value, Mapping):
            raise ValueError("workspace state must be an object")
        raw_bindings = value.get("bindings", {})
        raw_presentations = value.get("presentations", {})
        if not isinstance(raw_bindings, Mapping) or not isinstance(
            raw_presentations, Mapping
        ):
            raise ValueError("bindings and presentations must be objects")
        bindings = {str(key): str(item) for key, item in raw_bindings.items()}
        presentations = {
            str(key): PresentationSnapshot.from_document(item)
            for key, item in raw_presentations.items()
        }
        raw_layout = value.get("layout", {})
        if not isinstance(raw_layout, Mapping):
            raise ValueError("layout must be an object")
        raw_ratios = value.get("splitter_ratios", {})
        if not isinstance(raw_ratios, Mapping):
            raise ValueError("splitter_ratios must be an object")
        return cls(
            study_key=study_key,
            updated_at_ms=_strict_int(value.get("updated_at_ms", 0), "updated_at_ms"),
            layout=LayoutSpec.from_document(raw_layout),
            splitter_ratios={str(key): item for key, item in raw_ratios.items()},
            bindings=bindings,
            active_viewport=str(value.get("active_viewport", "")),
            sync=WorkspaceSyncState.from_document(value.get("sync", {})),
            presentations=presentations,
            mpr=(
                None
                if value.get("mpr") is None
                else MprWorkspaceSnapshot.from_document(value.get("mpr"))
            ),
        )

    @property
    def required_series_keys(self) -> frozenset[str]:
        required = set(self.bindings.values())
        if self.mpr is not None:
            required.add(self.mpr.series_key)
        return frozenset(required)

    def resolve_bindings(self, series_key_index: Mapping[str, str]) -> dict[str, str]:
        """Map viewport IDs to runtime series IDs using a caller-built index."""

        return {
            view: series_key_index[key]
            for view, key in self.bindings.items()
            if key in series_key_index
        }

    def resolve_mpr_series(
        self, series_key_index: Mapping[str, str]
    ) -> Optional[str]:
        if self.mpr is None:
            return None
        return series_key_index.get(self.mpr.series_key)

    def to_document(self) -> dict[str, object]:
        return {
            "updated_at_ms": self.updated_at_ms,
            "layout": self.layout.to_document(),
            "splitter_ratios": {
                key: list(value) for key, value in sorted(self.splitter_ratios.items())
            },
            "bindings": dict(sorted(self.bindings.items())),
            "active_viewport": self.active_viewport,
            "sync": self.sync.to_document(),
            "presentations": {
                key: value.to_document()
                for key, value in sorted(self.presentations.items())
            },
            "mpr": None if self.mpr is None else self.mpr.to_document(),
        }


def build_series_key_index(
    series_uid_by_runtime_id: Mapping[str, object],
) -> dict[str, str]:
    """Build ``opaque series key -> runtime series id`` for restoration."""

    result: dict[str, str] = {}
    for runtime_id, uid in series_uid_by_runtime_id.items():
        key = series_key_for_uid(uid)
        if key is not None:
            result[key] = str(runtime_id)
    return result


@dataclass(frozen=True)
class WorkspaceDocument:
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    states: Mapping[str, StudyWorkspaceState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_SCHEMA_VERSION:
            raise ValueError("WorkspaceDocument only represents schema v2")
        states: dict[str, StudyWorkspaceState] = {}
        for key, state in self.states.items():
            if not isinstance(state, StudyWorkspaceState) or state.study_key != key:
                raise ValueError("workspace state key mismatch")
            states[key] = state
        object.__setattr__(self, "states", states)

    @classmethod
    def parse(
        cls, value: object
    ) -> tuple["WorkspaceDocument", int]:
        if not isinstance(value, Mapping):
            raise ValueError("workspace document must be an object")
        version = _strict_int(value.get("schema_version", 0), "schema_version")
        if version != WORKSPACE_SCHEMA_VERSION:
            raise ValueError("unsupported workspace schema")
        raw_states = value.get("states", {})
        if not isinstance(raw_states, Mapping):
            raise ValueError("workspace states must be an object")
        states: dict[str, StudyWorkspaceState] = {}
        skipped = 0
        for raw_key, raw_state in raw_states.items():
            key = str(raw_key)
            try:
                state = StudyWorkspaceState.from_document(key, raw_state)
            except (KeyError, TypeError, ValueError, OverflowError):
                skipped += 1
                continue
            states[key] = state
        return cls(states=states), skipped

    def pruned(self, maximum: int) -> tuple["WorkspaceDocument", int]:
        limit = max(1, min(MAX_MAX_HISTORY, int(maximum)))
        ordered = sorted(
            self.states.items(),
            key=lambda item: (-item[1].updated_at_ms, item[0]),
        )
        retained = dict(ordered[:limit])
        return WorkspaceDocument(states=retained), max(0, len(ordered) - len(retained))

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "states": {
                key: state.to_document()
                for key, state in sorted(self.states.items())
            },
        }


@dataclass(frozen=True)
class WorkspaceLoadResult:
    document: WorkspaceDocument
    read_only: bool = False
    migrated: bool = False
    skipped_entries: int = 0
    newer_schema_version: Optional[int] = None
    error: str = ""


@dataclass(frozen=True)
class WorkspaceWriteResult:
    success: bool
    document: WorkspaceDocument
    verified: bool = False
    pruned_entries: int = 0
    reason: str = ""


def _legacy_series_key(value: object) -> Optional[str]:
    text = str(value or "").strip().lower()
    if _is_hash(text, SERIES_KEY_HEX_LENGTH):
        return text
    return series_key_for_uid(value)


def _legacy_presentation(
    value: Mapping[str, object], series_key: str
) -> PresentationSnapshot:
    defaults = ViewPresentationState()
    pan = value.get("pan", (0.0, 0.0))
    if isinstance(pan, (str, bytes)) or not isinstance(pan, Sequence) or len(pan) != 2:
        pan = (0.0, 0.0)

    def legacy_float(name: str, default: float) -> float:
        try:
            return _finite_float(value.get(name, default), name)
        except (TypeError, ValueError, OverflowError):
            return default

    try:
        slice_index = _strict_int(value.get("slice", 0), "slice")
    except (TypeError, ValueError, OverflowError):
        slice_index = 0
    return PresentationSnapshot(
        series_key=series_key,
        slice_index=slice_index,
        window_width=legacy_float("ww", defaults.window_width),
        window_level=legacy_float("wl", defaults.window_level),
        zoom=legacy_float("zoom", defaults.zoom),
        pan_center=(legacy_float_from(pan, 0), legacy_float_from(pan, 1)),
        inverted=bool(value.get("invert", defaults.inverted)),
        interpolation=InterpolationMode.coerce(
            value.get("interpolation", defaults.interpolation)
        ).value,
        fit_mode=bool(value.get("fit", defaults.fit_mode)),
    )


def legacy_float_from(values: Sequence[object], index: int) -> float:
    try:
        return _finite_float(values[index], "legacy pan")
    except (IndexError, TypeError, ValueError, OverflowError):
        return 0.0


def migrate_v25_bare_states(
    value: object, *, maximum: int = DEFAULT_MAX_HISTORY
) -> tuple[WorkspaceDocument, int]:
    """Pure, deterministic migration of the v2.5 bare ``states`` mapping."""

    if not isinstance(value, Mapping):
        return WorkspaceDocument(), 1
    states: dict[str, StudyWorkspaceState] = {}
    skipped = 0
    for raw_study_key, raw_state in value.items():
        study_key = str(raw_study_key).strip().lower()
        if not _is_hash(study_key, STUDY_KEY_HEX_LENGTH) or not isinstance(
            raw_state, Mapping
        ):
            skipped += 1
            continue
        try:
            layout = LayoutSpec.from_legacy(raw_state.get("layout", (1, 1)))
            raw_bindings = raw_state.get("bindings", {})
            raw_presentations = raw_state.get("presentations", {})
            if not isinstance(raw_bindings, Mapping) or not isinstance(
                raw_presentations, Mapping
            ):
                raise ValueError("legacy bindings must be objects")
            bindings: dict[str, str] = {}
            for raw_view, raw_uid in raw_bindings.items():
                view = _safe_id(raw_view)
                key = _legacy_series_key(raw_uid)
                if key is not None:
                    bindings[view] = key
            presentations: dict[str, PresentationSnapshot] = {}
            for raw_view, raw_values in raw_presentations.items():
                view = _safe_id(raw_view)
                if not isinstance(raw_values, Mapping):
                    continue
                key = bindings.get(view) or _legacy_series_key(
                    raw_values.get("series_uid")
                )
                if key is None or bindings.get(view) != key:
                    continue
                presentations[view] = _legacy_presentation(raw_values, key)
            updated = _finite_float(raw_state.get("updated", 0.0), "updated")
            state = StudyWorkspaceState(
                study_key=study_key,
                updated_at_ms=max(0, int(updated * 1000.0)),
                layout=layout,
                bindings=bindings,
                active_viewport=str(raw_state.get("active_view", "")),
                sync=WorkspaceSyncState.from_runtime(
                    raw_state.get("sync_mode", 0),
                    raw_state.get("sync_group", "same_study"),
                    raw_state.get("position_mode", "auto_lps"),
                ),
                presentations=presentations,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            skipped += 1
            continue
        states[study_key] = state
    document, pruned = WorkspaceDocument(states=states).pruned(maximum)
    return document, skipped + pruned


class StudyWorkspaceStore:
    """Settings-backed v2 workspace store with verified document writes."""

    def __init__(
        self,
        settings: WorkspaceSettings,
        *,
        maximum: Optional[int] = None,
        document_key: str = WORKSPACE_DOCUMENT_KEY,
        legacy_key: str = LEGACY_WORKSPACE_KEY,
    ) -> None:
        self.settings = settings
        self._maximum = maximum
        self.document_key = document_key
        self.legacy_key = legacy_key

    @property
    def maximum(self) -> int:
        value: object = self._maximum
        if value is None:
            value = self.settings.get_setting(
                "workspace.history_limit", DEFAULT_MAX_HISTORY
            )
        try:
            return max(1, min(MAX_MAX_HISTORY, int(value)))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_MAX_HISTORY

    def _has(self, key: str) -> bool:
        method = getattr(self.settings, "has_setting", None)
        if callable(method):
            return bool(method(key))
        marker = object()
        return self.settings.get_setting(key, marker) is not marker

    def _sync(self) -> None:
        method = getattr(self.settings, "save_settings", None)
        if callable(method):
            method()

    def _rollback(self, existed: bool, previous: object) -> None:
        try:
            if existed:
                self.settings.set_setting(self.document_key, previous)
            else:
                self.settings.remove_setting(self.document_key)
            self._sync()
        except (OSError, RuntimeError, TypeError, ValueError):
            # The caller still receives a failed/unchecked result.  No legacy
            # key is removed when rollback itself cannot be confirmed.
            pass

    def _write_verified(
        self, document: WorkspaceDocument, *, pruned_entries: int = 0
    ) -> WorkspaceWriteResult:
        payload = document.to_document()
        existed = self._has(self.document_key)
        previous = self.settings.get_setting(self.document_key, {}) if existed else {}
        try:
            self.settings.set_setting(self.document_key, payload)
            self._sync()
            persisted = self.settings.get_setting(self.document_key, {})
            parsed, skipped = WorkspaceDocument.parse(persisted)
            verified = (
                skipped == 0
                and _canonical_json(parsed.to_document()) == _canonical_json(payload)
                and _canonical_json(persisted) == _canonical_json(payload)
            )
        except (OSError, RuntimeError, TypeError, ValueError, OverflowError):
            verified = False
        if not verified:
            self._rollback(existed, previous)
            return WorkspaceWriteResult(
                False,
                document,
                verified=False,
                pruned_entries=pruned_entries,
                reason="verification_failed",
            )
        return WorkspaceWriteResult(
            True,
            document,
            verified=True,
            pruned_entries=pruned_entries,
        )

    def _remove_verified_legacy(self) -> None:
        if not self._has(self.legacy_key):
            return
        try:
            self.settings.remove_setting(self.legacy_key)
            self._sync()
        except (OSError, RuntimeError, TypeError, ValueError):
            # A leftover legacy key is harmless and enables another cleanup
            # attempt on the next load.
            return

    def load_document(self, *, migrate_legacy: bool = True) -> WorkspaceLoadResult:
        has_document = self._has(self.document_key)
        raw = (
            self.settings.get_setting(self.document_key, {})
            if has_document
            else {}
        )
        if has_document and isinstance(raw, Mapping) and raw:
            try:
                version = _strict_int(raw.get("schema_version", 0), "schema_version")
            except (TypeError, ValueError, OverflowError):
                version = 0
            if version > WORKSPACE_SCHEMA_VERSION:
                return WorkspaceLoadResult(
                    WorkspaceDocument(),
                    read_only=True,
                    newer_schema_version=version,
                    error="newer_schema",
                )
            if version == WORKSPACE_SCHEMA_VERSION:
                try:
                    document, skipped = WorkspaceDocument.parse(raw)
                except (TypeError, ValueError, OverflowError):
                    return WorkspaceLoadResult(
                        WorkspaceDocument(), error="corrupt_document"
                    )
                canonical = document.to_document()
                if skipped == 0:
                    try:
                        if _canonical_json(raw) == _canonical_json(canonical):
                            self._remove_verified_legacy()
                    except (TypeError, ValueError):
                        pass
                return WorkspaceLoadResult(document, skipped_entries=skipped)

        if not migrate_legacy or not self._has(self.legacy_key):
            return WorkspaceLoadResult(WorkspaceDocument())
        legacy = self.settings.get_setting(self.legacy_key, {})
        document, skipped = migrate_v25_bare_states(
            legacy, maximum=self.maximum
        )
        result = self._write_verified(document)
        if not result.success:
            return WorkspaceLoadResult(
                WorkspaceDocument(),
                skipped_entries=skipped,
                error=result.reason,
            )
        # The old recovery source is removed only after a successful read-back
        # comparison of the entire v2 document.
        self._remove_verified_legacy()
        return WorkspaceLoadResult(
            result.document,
            migrated=True,
            skipped_entries=skipped,
        )

    def get_by_key(self, study_key: str) -> Optional[StudyWorkspaceState]:
        result = self.load_document()
        if result.read_only:
            return None
        key = str(study_key).strip().lower()
        return result.document.states.get(key)

    def get_for_study_uid(self, study_instance_uid: object) -> Optional[StudyWorkspaceState]:
        key = study_key_for_uid(study_instance_uid)
        return None if key is None else self.get_by_key(key)

    def save_state(self, state: StudyWorkspaceState) -> WorkspaceWriteResult:
        loaded = self.load_document()
        if loaded.read_only:
            return WorkspaceWriteResult(
                False, loaded.document, reason="newer_schema"
            )
        states = dict(loaded.document.states)
        states[state.study_key] = state
        document, pruned = WorkspaceDocument(states=states).pruned(self.maximum)
        return self._write_verified(document, pruned_entries=pruned)

    upsert = save_state

    def remove_by_key(self, study_key: str) -> WorkspaceWriteResult:
        loaded = self.load_document()
        if loaded.read_only:
            return WorkspaceWriteResult(
                False, loaded.document, reason="newer_schema"
            )
        states = dict(loaded.document.states)
        states.pop(str(study_key).strip().lower(), None)
        return self._write_verified(WorkspaceDocument(states=states))

    def clear(self) -> WorkspaceWriteResult:
        loaded = self.load_document()
        if loaded.read_only:
            return WorkspaceWriteResult(
                False, loaded.document, reason="newer_schema"
            )
        return self._write_verified(WorkspaceDocument())


__all__ = [
    "DEFAULT_MAX_HISTORY",
    "LEGACY_WORKSPACE_KEY",
    "PresentationSnapshot",
    "SERIES_KEY_HEX_LENGTH",
    "STUDY_KEY_HEX_LENGTH",
    "StudyWorkspaceState",
    "StudyWorkspaceStore",
    "WORKSPACE_DOCUMENT_KEY",
    "WORKSPACE_SCHEMA_VERSION",
    "WorkspaceDocument",
    "WorkspaceLoadResult",
    "WorkspaceSyncState",
    "WorkspaceWriteResult",
    "build_series_key_index",
    "migrate_v25_bare_states",
    "series_key_for_uid",
    "study_key_for_uid",
]
