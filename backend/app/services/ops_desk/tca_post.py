"""Post-trade TCA: implementation shortfall vs arrival from *our* fills."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.pit.slippage import fill_row_to_shortfall, implementation_shortfall_bps


@dataclass(frozen=True, slots=True)
class FillIS:
    symbol: str
    is_bps: float | None
    n: int
    mean_bps: float
    p90_bps: float


def summarize_symbol(symbol: str, fills: Sequence[Mapping[str, Any]]) -> FillIS:
    sample: list[float] = []
    for row in fills:
        bps = fill_row_to_shortfall(row)
        if bps is None:
            continue
        sample.append(float(bps))
    if not sample:
        return FillIS(symbol.upper(), None, 0, 0.0, 0.0)
    ordered = sorted(sample)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))]
    return FillIS(
        symbol=symbol.upper(),
        is_bps=round(sum(sample) / len(sample), 4),
        n=len(sample),
        mean_bps=round(sum(sample) / len(sample), 4),
        p90_bps=round(p90, 4),
    )


def book_tca(fills_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[FillIS]:
    return [summarize_symbol(sym, rows) for sym, rows in fills_by_symbol.items()]


def one_fill_is(arrival: float, fill: float, side: str) -> float | None:
    return implementation_shortfall_bps(arrival, fill, side)
