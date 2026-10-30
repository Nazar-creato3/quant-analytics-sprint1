"""Explicit veto hierarchy for the research ensemble.

Highest authority first. A higher layer that fires FLAT kills everything below.
Rules never reverse a regime/macro veto. ML never reverses a rule conflict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

VETO_HIERARCHY: tuple[str, ...] = (
    "regime",
    "macro",
    "rules_conflict",
    "meta_skip",
    "ml",
)


@dataclass(frozen=True, slots=True)
class GateInputs:
    regime_alpha_on: bool = True
    regime_size_mult: float = 1.0
    macro_veto: bool = False
    donchian_dir: int = 0
    turtle_dir: int = 0
    meta_take: bool = True
    ml_dir: int = 0


@dataclass(frozen=True, slots=True)
class EnsembleDecision:
    direction: int
    size_mult: float
    vetoed_by: str | None
    source: str
    hierarchy: tuple[str, ...] = VETO_HIERARCHY
    note: str = ""


def combine(inputs: GateInputs) -> EnsembleDecision:
    if not inputs.regime_alpha_on:
        return EnsembleDecision(0, 0.0, "regime", "flat", note="regime_alpha_off")
    if inputs.macro_veto:
        return EnsembleDecision(0, 0.0, "macro", "flat", note="macro_crisis_veto")

    d_dir = int(np_sign(inputs.donchian_dir))
    t_dir = int(np_sign(inputs.turtle_dir))
    if d_dir != 0 and t_dir != 0 and d_dir != t_dir:
        return EnsembleDecision(0, 0.0, "rules_conflict", "flat", note="turtle_vs_donchian")

    rule_dir = t_dir or d_dir
    if rule_dir != 0 and not inputs.meta_take:
        return EnsembleDecision(0, 0.0, "meta_skip", "flat", note="meta_label_skip")

    size = max(0.0, min(1.0, float(inputs.regime_size_mult)))
    if rule_dir != 0:
        return EnsembleDecision(
            rule_dir,
            size,
            None,
            "rules",
            note="turtle" if t_dir != 0 else "donchian",
        )

    ml = int(np_sign(inputs.ml_dir))
    if ml == 0:
        return EnsembleDecision(0, 0.0, None, "flat", note="no_signal")
    return EnsembleDecision(ml, size, None, "ml", note="ml_fill")


def np_sign(v: int | float) -> int:
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def decision_to_dict(dec: EnsembleDecision) -> dict[str, object]:
    return {
        "direction": dec.direction,
        "size_mult": dec.size_mult,
        "vetoed_by": dec.vetoed_by,
        "source": dec.source,
        "hierarchy": list(dec.hierarchy),
        "note": dec.note,
    }


def overlay_from_mapping(raw: Mapping[str, object]) -> EnsembleDecision:
    return combine(
        GateInputs(
            regime_alpha_on=bool(raw.get("regime_alpha_on", True)),
            regime_size_mult=float(raw.get("regime_size_mult", 1.0) or 1.0),
            macro_veto=bool(raw.get("macro_veto", False)),
            donchian_dir=int(raw.get("donchian_dir", 0) or 0),
            turtle_dir=int(raw.get("turtle_dir", 0) or 0),
            meta_take=bool(raw.get("meta_take", True)),
            ml_dir=int(raw.get("ml_dir", 0) or 0),
        )
    )
