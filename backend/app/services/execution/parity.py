"""Nightly paper ↔ live parity: paper must not look systematically better than live."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.execution.scorecard import build_scorecards


@dataclass(frozen=True, slots=True)
class ParityReport:
    ok: bool
    paper_is_bps: float
    live_is_bps: float
    paper_fill: float
    live_fill: float
    drift_bps: float
    reasons: tuple[str, ...]


def nightly_parity(
    fills: Sequence[Mapping[str, Any]],
    *,
    max_optimistic_bps: float = 8.0,
    min_live_n: int = 3,
) -> ParityReport:
    cards = build_scorecards(fills)
    paper = cards.get("paper")
    live_cards = [c for k, c in cards.items() if k != "paper" and c.n >= min_live_n]
    paper_is = paper.mean_is_bps if paper and paper.n else 0.0
    paper_fill = paper.fill_rate if paper and paper.n else 0.0
    if not live_cards:
        return ParityReport(False, paper_is, 0.0, paper_fill, 0.0, 0.0, ("нет данных",))
    live_is = sum(c.mean_is_bps * c.n for c in live_cards) / sum(c.n for c in live_cards)
    live_fill = sum(c.fill_rate * c.n for c in live_cards) / sum(c.n for c in live_cards)
    drift = live_is - paper_is  # >0 paper cheaper than live
    reasons: list[str] = []
    if drift > max_optimistic_bps:
        reasons.append("paper_optimistic_is")
    if paper_fill - live_fill > 0.25:
        reasons.append("paper_optimistic_fill")
    return ParityReport(
        ok=not reasons,
        paper_is_bps=round(paper_is, 4),
        live_is_bps=round(live_is, 4),
        paper_fill=round(paper_fill, 4),
        live_fill=round(live_fill, 4),
        drift_bps=round(drift, 4),
        reasons=tuple(reasons),
    )
