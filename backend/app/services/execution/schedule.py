"""TWAP / VWAP child clips with Cartea book gates. Not HFT."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.quant_desk.microstructure import BookGate, book_gate


# Institutional, not microstructure racing: ≥ 60s between children, ≤ 10% ADV / day.
MIN_SLICE_SECONDS = 60
MAX_DAY_PARTICIPATION = 0.10
MAX_CHILD_PARTICIPATION = 0.02


@dataclass(frozen=True, slots=True)
class ChildOrder:
    seq: int
    qty: float
    wait_seconds: int
    size_mult: float
    reason: str


@dataclass(frozen=True, slots=True)
class Schedule:
    kind: str  # twap | vwap
    children: tuple[ChildOrder, ...]
    parent_qty: float
    clipped_qty: float
    notes: tuple[str, ...]


def _volume_weights(profile: Sequence[float] | None, n: int) -> list[float]:
    if profile and len(profile) >= n:
        raw = [max(0.0, float(x)) for x in profile[:n]]
        s = sum(raw)
        if s > 0:
            return [x / s for x in raw]
    return [1.0 / n] * n


def build_schedule(
    parent_qty: float,
    *,
    adv_qty: float,
    n_slices: int = 6,
    horizon_minutes: int = 30,
    kind: str = "twap",
    volume_profile: Sequence[float] | None = None,
    bid: float | None = None,
    ask: float | None = None,
    bid_sz: float | None = None,
    ask_sz: float | None = None,
    direction: str = "long",
    atr_pct: float | None = None,
) -> Schedule:
    notes: list[str] = []
    qty = max(0.0, float(parent_qty))
    adv = max(0.0, float(adv_qty))
    day_cap = adv * MAX_DAY_PARTICIPATION if adv > 0 else qty
    if qty > day_cap + 1e-12:
        qty = day_cap
        notes.append("day_participation")
    n = max(1, min(int(n_slices), 12))
    weights = _volume_weights(volume_profile if kind == "vwap" else None, n)
    gate = book_gate(
        bid=bid, ask=ask, bid_sz=bid_sz, ask_sz=ask_sz,
        direction=direction, atr_pct=atr_pct,
    )
    if not gate.allow:
        return Schedule(kind, (), parent_qty, 0.0, (gate.reason,))
    wait = max(MIN_SLICE_SECONDS, int((max(1, horizon_minutes) * 60) / n))
    child_cap = adv * MAX_CHILD_PARTICIPATION if adv > 0 else qty
    children: list[ChildOrder] = []
    remaining = qty
    clipped = 0.0
    for i in range(n):
        raw = qty * weights[i] * gate.size_mult
        take = min(remaining, raw, child_cap)
        if take <= 1e-12:
            notes.append("child_empty")
            break
        remaining -= take
        clipped += take
        children.append(
            ChildOrder(
                seq=i + 1,
                qty=round(take, 8),
                wait_seconds=wait,
                size_mult=gate.size_mult,
                reason=gate.reason,
            )
        )
    if remaining > 1e-8:
        notes.append("leftover_unscheduled")
    return Schedule(
        kind=kind if kind == "vwap" else "twap",
        children=tuple(children),
        parent_qty=float(parent_qty),
        clipped_qty=round(clipped, 8),
        notes=tuple(notes),
    )


def apply_gate_to_qty(qty: float, gate: BookGate) -> float:
    if not gate.allow:
        return 0.0
    return max(0.0, float(qty) * float(gate.size_mult))
