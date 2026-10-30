"""Venue scorecards from our fill quality — not a vendor TCA tape."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.pit.slippage import fill_row_to_shortfall


VENUES = ("alpaca", "tinkoff", "binance", "tokenized_equity", "paper")


@dataclass(frozen=True, slots=True)
class VenueCard:
    venue: str
    n: int
    mean_is_bps: float
    p90_is_bps: float
    fill_rate: float
    score: float  # higher = better (lower IS, higher fill)
    notes: str


def _venue_of(row: Mapping[str, Any]) -> str:
    raw = str(row.get("venue") or row.get("broker") or row.get("execution_venue") or "paper").lower()
    if raw in {"moex", "t-bank", "tbank"}:
        return "tinkoff"
    if raw in {"bybit", "mexc", "tokenized"}:
        return "tokenized_equity"
    if raw in VENUES:
        return raw
    return "paper"


def build_scorecards(fills: Sequence[Mapping[str, Any]]) -> dict[str, VenueCard]:
    buckets: dict[str, list[Mapping[str, Any]]] = {v: [] for v in VENUES}
    for row in fills:
        buckets.setdefault(_venue_of(row), []).append(row)
    cards: dict[str, VenueCard] = {}
    for venue, rows in buckets.items():
        if venue not in VENUES:
            continue
        is_s: list[float] = []
        filled = 0
        for row in rows:
            st = str(row.get("status") or "filled").lower()
            if st in {"filled", "partial"}:
                filled += 1
            bps = fill_row_to_shortfall(row)
            if bps is not None:
                is_s.append(float(bps))
        n = len(rows)
        if n == 0:
            cards[venue] = VenueCard(venue, 0, 0.0, 0.0, 0.0, 0.0, "no_history")
            continue
        mean = sum(is_s) / len(is_s) if is_s else 8.0  # unknown IS → conservative
        ordered = sorted(is_s) if is_s else [mean]
        p90 = ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))]
        fill_rate = filled / n
        # score: fill_rate in [0,1] minus IS penalty (10 bps → −0.2)
        score = fill_rate - min(1.0, mean / 50.0)
        cards[venue] = VenueCard(
            venue=venue,
            n=n,
            mean_is_bps=round(mean, 4),
            p90_is_bps=round(p90, 4),
            fill_rate=round(fill_rate, 4),
            score=round(score, 4),
            notes="own_fills",
        )
    return cards
