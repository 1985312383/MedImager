"""Typed settings metadata and staged editing support.

The registry is intentionally independent from Qt.  Runtime consumers can use
the strongly typed API while older integrations continue to use string keys
through :class:`medimager.utils.settings.SettingsManager`.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, Iterable, Optional, Protocol, TypeVar


T = TypeVar("T")
_MISSING = object()


class ApplyPolicy(str, Enum):
    """When a setting is expected to affect the running application."""

    LIVE = "live"
    ON_ACCEPT = "on_accept"
    NEXT_LOAD = "next_load"
    RESTART = "restart"


class ControlKind(str, Enum):
    """UI-neutral hint used by the settings center."""

    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    TEXT = "text"
    ENUM = "enum"


@dataclass(frozen=True)
class SettingChoice:
    value: Any
    label_key: str


@dataclass(frozen=True)
class SettingSpec(Generic[T]):
    """Definition of one application preference."""

    key: str
    default: T
    value_type: type
    category: str
    control: ControlKind
    apply_policy: ApplyPolicy = ApplyPolicy.ON_ACCEPT
    label_key: str = ""
    help_key: str = ""
    choices: tuple[SettingChoice, ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    validator: Optional[Callable[[T], bool]] = None
    exportable: bool = True
    sensitive: bool = False

    def coerce(self, value: Any, fallback: Any = _MISSING) -> T:
        """Convert persisted values to the declared type and validate them."""

        default = deepcopy(self.default if fallback is _MISSING else fallback)
        try:
            if self.value_type is bool:
                if isinstance(value, str):
                    normalized = value.strip().casefold()
                    if normalized in {"1", "true", "yes", "on"}:
                        coerced: Any = True
                    elif normalized in {"0", "false", "no", "off", ""}:
                        coerced = False
                    else:
                        return default
                else:
                    coerced = bool(value)
            elif self.value_type is int:
                if isinstance(value, bool):
                    return default
                coerced = int(value)
            elif self.value_type is float:
                if isinstance(value, bool):
                    return default
                coerced = float(value)
            elif self.value_type is str:
                coerced = str(value)
            elif self.value_type is dict:
                if not isinstance(value, dict):
                    return default
                coerced = deepcopy(value)
            elif self.value_type is list:
                if not isinstance(value, list):
                    return default
                coerced = deepcopy(value)
            elif isinstance(value, self.value_type):
                coerced = value
            else:
                return default
        except (TypeError, ValueError, OverflowError):
            return default

        if self.choices and coerced not in {choice.value for choice in self.choices}:
            return default
        if self.minimum is not None and coerced < self.minimum:
            coerced = self.value_type(self.minimum)
        if self.maximum is not None and coerced > self.maximum:
            coerced = self.value_type(self.maximum)
        if self.validator is not None:
            try:
                valid = self.validator(coerced)
            except (TypeError, ValueError, OverflowError):
                return default
            if not valid:
                return default
        return coerced


class SettingsRegistry:
    """Ordered collection of unique :class:`SettingSpec` objects."""

    def __init__(self, specs: Iterable[SettingSpec[Any]] = ()) -> None:
        self._specs: dict[str, SettingSpec[Any]] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: SettingSpec[Any]) -> SettingSpec[Any]:
        if not spec.key or spec.key in self._specs:
            raise ValueError(f"Duplicate or empty setting key: {spec.key!r}")
        self._specs[spec.key] = spec
        return spec

    def contains(self, key: str) -> bool:
        return key in self._specs

    def spec(self, key: str) -> Optional[SettingSpec[Any]]:
        return self._specs.get(key)

    def require(self, key: str) -> SettingSpec[Any]:
        spec = self.spec(key)
        if spec is None:
            raise KeyError(key)
        return spec

    def specs(self, category: Optional[str] = None) -> tuple[SettingSpec[Any], ...]:
        values = self._specs.values()
        if category is not None:
            values = (spec for spec in values if spec.category == category)
        return tuple(values)

    def defaults(self) -> dict[str, Any]:
        return {spec.key: deepcopy(spec.default) for spec in self._specs.values()}

    def coerce(self, key: str, value: Any, fallback: Any = _MISSING) -> Any:
        spec = self.spec(key)
        return deepcopy(value) if spec is None else spec.coerce(value, fallback)


class _SettingsStore(Protocol):
    registry: SettingsRegistry

    def get_typed(self, setting: str | SettingSpec[Any]) -> Any: ...

    def set_many(self, values: dict[str, Any]) -> None: ...


class SettingsSession:
    """Stage edits and safely roll back live previews on cancellation."""

    def __init__(
        self,
        manager: _SettingsStore,
        live_applier: Optional[Callable[[str, Any, bool], None]] = None,
    ) -> None:
        self.manager = manager
        self.registry = manager.registry
        self._live_applier = live_applier
        self._original: dict[str, Any] = {}
        self._staged: dict[str, Any] = {}

    @property
    def changed_keys(self) -> tuple[str, ...]:
        return tuple(self._staged)

    @property
    def is_dirty(self) -> bool:
        return bool(self._staged)

    def get(self, setting: str | SettingSpec[T]) -> T:
        key = setting.key if isinstance(setting, SettingSpec) else str(setting)
        if key in self._staged:
            return deepcopy(self._staged[key])
        return deepcopy(self.manager.get_typed(setting))

    def set(self, setting: str | SettingSpec[T], value: Any) -> T:
        spec = setting if isinstance(setting, SettingSpec) else self.registry.require(str(setting))
        normalized = spec.coerce(value)
        if spec.key not in self._original:
            self._original[spec.key] = self.manager.get_typed(spec)
        if normalized == self._original[spec.key]:
            self._staged.pop(spec.key, None)
        else:
            self._staged[spec.key] = deepcopy(normalized)
        if spec.apply_policy is ApplyPolicy.LIVE and self._live_applier is not None:
            self._live_applier(spec.key, normalized, True)
        return normalized

    def commit(self) -> tuple[str, ...]:
        changed = tuple(self._staged)
        if self._staged:
            self.manager.set_many(dict(self._staged))
        for key in changed:
            spec = self.registry.spec(key)
            if (
                spec is not None
                and spec.apply_policy is ApplyPolicy.LIVE
                and self._live_applier is not None
            ):
                self._live_applier(key, self.manager.get_typed(spec), False)
        self._original.clear()
        self._staged.clear()
        return changed

    def discard(self) -> None:
        if self._live_applier is not None:
            for key, original in self._original.items():
                spec = self.registry.spec(key)
                if spec is not None and spec.apply_policy is ApplyPolicy.LIVE:
                    self._live_applier(key, original, False)
        self._original.clear()
        self._staged.clear()


def _choice(value: str, label_key: str) -> SettingChoice:
    return SettingChoice(value=value, label_key=label_key)


_TOOLBAR_GROUPS = ("browse", "measure", "compare", "advanced")


def _valid_toolbar_order(value: list[Any]) -> bool:
    return len(value) == len(_TOOLBAR_GROUPS) and set(value) == set(_TOOLBAR_GROUPS)


def _valid_visible_toolbar_groups(value: list[Any]) -> bool:
    return (
        bool(value)
        and len(value) == len(set(value))
        and all(item in _TOOLBAR_GROUPS for item in value)
    )


DEFAULT_SETTINGS_REGISTRY = SettingsRegistry(
    (
        SettingSpec("settings.schema_version", 2, int, "internal", ControlKind.INT, minimum=1, maximum=2, exportable=False),
        SettingSpec("language", "en_US", str, "general", ControlKind.ENUM, ApplyPolicy.RESTART),
        SettingSpec("ui_theme", "dark", str, "general", ControlKind.ENUM, ApplyPolicy.LIVE),
        SettingSpec("ui.density", "compact", str, "appearance", ControlKind.ENUM, choices=(_choice("compact", "settingsdialog.density_compact"), _choice("comfortable", "settingsdialog.density_comfortable"))),
        SettingSpec("ui.icon_size", 24, int, "appearance", ControlKind.INT, minimum=16, maximum=40),
        SettingSpec("ui.font_scale", 100, int, "appearance", ControlKind.INT, minimum=80, maximum=150),
        SettingSpec("toolbar.group_order", list(_TOOLBAR_GROUPS), list, "appearance", ControlKind.TEXT, validator=_valid_toolbar_order),
        SettingSpec("toolbar.visible_groups", list(_TOOLBAR_GROUPS), list, "appearance", ControlKind.TEXT, validator=_valid_visible_toolbar_groups),
        SettingSpec("toolbar.show_labels", False, bool, "appearance", ControlKind.BOOL),
        SettingSpec("roi_theme", "default", str, "tools", ControlKind.ENUM),
        SettingSpec("measurement_theme", "default", str, "tools", ControlKind.ENUM),
        SettingSpec("cache_size", 256, int, "storage", ControlKind.INT, minimum=64, maximum=2048),
        SettingSpec("thread_count", 4, int, "storage", ControlKind.INT, minimum=1, maximum=16),
        SettingSpec("display.window_level_strategy", "dicom", str, "display", ControlKind.ENUM, ApplyPolicy.NEXT_LOAD, choices=(_choice("dicom", "settingsdialog.prefer_dicom_tags"), _choice("auto", "settingsdialog.auto_calculate_by_pixel_range"), _choice("fixed", "settingsdialog.fixed_default_400_40"))),
        SettingSpec("display.smooth_interpolation", True, bool, "display", ControlKind.BOOL),
        SettingSpec("display.show_view_title", True, bool, "display", ControlKind.BOOL),
        SettingSpec("display.show_view_status", True, bool, "display", ControlKind.BOOL),
        SettingSpec("overlay.show_orientation", True, bool, "display", ControlKind.BOOL),
        SettingSpec("overlay.show_slice_position", True, bool, "display", ControlKind.BOOL),
        SettingSpec("overlay.show_scale", True, bool, "display", ControlKind.BOOL),
        SettingSpec("overlay.show_patient", True, bool, "display", ControlKind.BOOL),
        SettingSpec("overlay.show_pixel_value", False, bool, "display", ControlKind.BOOL),
        SettingSpec("interaction.left_drag_action", "browse", str, "interaction", ControlKind.ENUM, choices=tuple(_choice(value, f"settingsdialog.{value}") for value in ("browse", "window", "zoom", "pan", "none"))),
        SettingSpec("interaction.middle_drag_action", "window", str, "interaction", ControlKind.ENUM, choices=tuple(_choice(value, f"settingsdialog.{value}") for value in ("browse", "window", "zoom", "pan", "none"))),
        SettingSpec("interaction.right_drag_action", "zoom", str, "interaction", ControlKind.ENUM, choices=tuple(_choice(value, f"settingsdialog.{value}") for value in ("browse", "window", "zoom", "pan", "none"))),
        SettingSpec("interaction.wheel_reverse", False, bool, "interaction", ControlKind.BOOL),
        SettingSpec("cine.default_fps", 10, int, "interaction", ControlKind.INT, minimum=1, maximum=60),
        SettingSpec("dicom.recursive_scan", True, bool, "dicom", ControlKind.BOOL, ApplyPolicy.NEXT_LOAD),
        SettingSpec("dicom.include_extensionless", True, bool, "dicom", ControlKind.BOOL, ApplyPolicy.NEXT_LOAD),
        SettingSpec("dicom.strict_metadata", False, bool, "dicom", ControlKind.BOOL, ApplyPolicy.NEXT_LOAD),
        SettingSpec("roi.stats.show_mean", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.show_std", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.show_max", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.show_min", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.show_area", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.show_count", True, bool, "tools", ControlKind.BOOL),
        SettingSpec("roi.stats.area_unit", "auto", str, "tools", ControlKind.ENUM, choices=tuple(_choice(value, f"settingsdialog.area_{value}") for value in ("auto", "mm2", "cm2", "px"))),
        SettingSpec("multiview.default_layout", "1x1", str, "multiview", ControlKind.ENUM, choices=tuple(_choice(value, value) for value in ("1x1", "1x2", "2x1", "2x2"))),
        SettingSpec("multiview.default_sync_mode", "basic", str, "multiview", ControlKind.ENUM, choices=tuple(_choice(value, value) for value in ("none", "basic", "advanced", "full"))),
        SettingSpec("multiview.sync_group", "same_study", str, "multiview", ControlKind.ENUM, choices=tuple(_choice(value, value) for value in ("same_study", "same_patient", "same_modality", "all_views"))),
        SettingSpec("sync.position_mode", "auto_lps", str, "multiview", ControlKind.ENUM, choices=(_choice("none", "settingsdialog.sync_position_none"), _choice("auto_lps", "settingsdialog.sync_position_auto_lps"))),
        SettingSpec("sync.window_level", True, bool, "multiview", ControlKind.BOOL),
        SettingSpec("sync.zoom", False, bool, "multiview", ControlKind.BOOL),
        SettingSpec("sync.pan", False, bool, "multiview", ControlKind.BOOL),
        SettingSpec("sync.reference_lines", True, bool, "multiview", ControlKind.BOOL),
        SettingSpec("sync.shared_cursor", True, bool, "multiview", ControlKind.BOOL),
        SettingSpec("workspace.startup_mode", "restore", str, "workspace", ControlKind.ENUM, choices=(_choice("restore", "settingsdialog.workspace_startup_restore"), _choice("default_layout", "settingsdialog.workspace_startup_layout"), _choice("hanging_protocol", "settingsdialog.workspace_startup_hanging"))),
        SettingSpec("workspace.default_hanging_protocol", "none", str, "workspace", ControlKind.ENUM, choices=(_choice("none", "settingsdialog.hanging_none"), _choice("study_overview", "settingsdialog.hanging_study_overview"), _choice("ct_phase", "settingsdialog.hanging_ct_phase"), _choice("mr_neuro", "settingsdialog.hanging_mr_neuro"))),
        SettingSpec("workspace.history_limit", 20, int, "workspace", ControlKind.INT, minimum=1, maximum=100),
        SettingSpec("workspace.restore_mpr", False, bool, "workspace", ControlKind.BOOL),
        SettingSpec("privacy.screen_mode", False, bool, "privacy", ControlKind.BOOL, ApplyPolicy.LIVE),
        SettingSpec("cache.thumbnail.max_items", 256, int, "storage", ControlKind.INT, minimum=64, maximum=2048),
        SettingSpec("cache.thumbnail.max_age_days", 30, int, "storage", ControlKind.INT, minimum=1, maximum=365),
        SettingSpec("recent_studies.max_items", 20, int, "workspace", ControlKind.INT, minimum=1, maximum=100),
        SettingSpec("cache.demo.keep", True, bool, "storage", ControlKind.BOOL, ApplyPolicy.NEXT_LOAD),
        SettingSpec("recent_studies.document", {}, dict, "internal", ControlKind.TEXT, exportable=False, sensitive=True),
        SettingSpec("recent_studies.entries", [], list, "internal", ControlKind.TEXT, exportable=False, sensitive=True),
        SettingSpec("recent_studies.schema", 1, int, "internal", ControlKind.INT, exportable=False),
        SettingSpec("recent_studies.persist_patient_labels", False, bool, "internal", ControlKind.BOOL, exportable=False, sensitive=True),
        SettingSpec("study_workspace.document", {}, dict, "internal", ControlKind.TEXT, exportable=False, sensitive=True),
    )
)


# Stable aliases make call sites concise without turning settings into magic strings.
SETTINGS = {spec.key: spec for spec in DEFAULT_SETTINGS_REGISTRY.specs()}

