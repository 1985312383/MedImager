"""Deterministic local hanging protocols for the v2.5 study workspace."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from medimager.core.multi_series_manager import SeriesInfo


class HangingProtocolId(str, Enum):
    STUDY_OVERVIEW = "study_overview"
    CT_COMPARISON = "ct_comparison"
    MR_NEURO = "mr_neuro"
    CURRENT_MPR = "current_mpr"


@dataclass(frozen=True)
class HangingPlan:
    protocol: HangingProtocolId
    layout: Tuple[int, int]
    series_ids: Tuple[str, ...]


def _text(info: SeriesInfo) -> str:
    return " ".join(
        (
            str(info.series_description or ""),
            str(info.protocol_name or ""),
            str(info.body_part_examined or ""),
        )
    ).casefold()


def _is_contrast_phase(info: SeriesInfo) -> bool:
    value = _text(info)
    if any(term in value for term in ("non contrast", "without contrast", "unenhanced", "plain", "平扫")):
        return False
    return any(
        term in value
        for term in ("contrast", "venous", "arterial", "portal", "enhanced", "增强")
    )


def _series_number(info: SeriesInfo) -> tuple[int, object]:
    try:
        return 0, int(str(info.series_number).strip())
    except (TypeError, ValueError):
        return 1, str(info.series_number or "").casefold()


def _ordered(items: Iterable[SeriesInfo]) -> list[SeriesInfo]:
    return sorted(items, key=lambda info: (_series_number(info), _text(info), info.series_id))


def _same_study(
    series: Sequence[SeriesInfo], active: Optional[SeriesInfo]
) -> list[SeriesInfo]:
    if active is None or not active.study_instance_uid:
        return list(series)
    return [
        info for info in series
        if info.study_instance_uid == active.study_instance_uid
    ]


def build_hanging_plan(
    protocol: HangingProtocolId,
    series: Sequence[SeriesInfo],
    active_series_id: Optional[str] = None,
) -> HangingPlan:
    """Select pane assignments without touching Qt or image model state."""
    active = next((item for item in series if item.series_id == active_series_id), None)
    candidates = _ordered(_same_study(series, active))
    loaded = [item for item in candidates if item.is_loaded]
    candidates = loaded or candidates

    if protocol is HangingProtocolId.CURRENT_MPR:
        selected = active or (candidates[0] if candidates else None)
        return HangingPlan(protocol, (1, 1), (selected.series_id,) if selected else ())

    if protocol is HangingProtocolId.CT_COMPARISON:
        ct = [item for item in candidates if str(item.modality).upper() == "CT"]
        pool = ct or candidates
        selected = []
        if active in pool:
            selected.append(active)
        # Prefer a contrasting enhancement phase, then the closest protocol.
        active_contrast = _is_contrast_phase(active) if active is not None else False
        ranked = sorted(
            (item for item in pool if item is not active),
            key=lambda item: (
                _is_contrast_phase(item) == active_contrast,
                item.body_part_examined != getattr(active, "body_part_examined", ""),
                _series_number(item),
            ),
        )
        selected.extend(ranked[: 2 - len(selected)])
        return HangingPlan(protocol, (1, 2), tuple(item.series_id for item in selected))

    if protocol is HangingProtocolId.MR_NEURO:
        mr = [item for item in candidates if str(item.modality).upper() == "MR"]
        pool = mr or candidates
        slot_terms = (
            ("t1", "mprage", "spgr"),
            ("t2",),
            ("flair",),
            ("dwi", "diffusion", "adc"),
        )
        selected = []
        used = set()
        for terms in slot_terms:
            match = next(
                (
                    item for item in pool
                    if item.series_id not in used
                    and any(term in _text(item) for term in terms)
                ),
                None,
            )
            if match is not None:
                selected.append(match)
                used.add(match.series_id)
        selected.extend(item for item in pool if item.series_id not in used)
        return HangingPlan(
            protocol, (2, 2), tuple(item.series_id for item in selected[:4])
        )

    return HangingPlan(
        HangingProtocolId.STUDY_OVERVIEW,
        (2, 2),
        tuple(item.series_id for item in candidates[:4]),
    )
