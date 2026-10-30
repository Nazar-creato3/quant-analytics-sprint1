"""Transaction cost: half-spread + impact from own tape. Reject if edge < cost."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.pit.slippage import predicted_cost_bps, round_trip_cost_from_tape


@dataclass(frozen=True, slots=True)
class CostQuote:
    symbol: str
    spread_bps: float
    impact_bps: float
    round_trip: float
    net_edge: float
    accept: bool
    reason: str


def kyle_impact_bps(notional_usd: float, adv_usd: float, *, coeff: float = 10.0) -> float:
    """√(Q/ADV) impact in bps. coeff=10 → 10% ADV costs ~3 bps one-way at default."""
    if adv_usd <= 0 or notional_usd <= 0:
        return 0.0
    frac = min(1.0, float(notional_usd) / float(adv_usd))
    return float(coeff) * (frac**0.5)


def quote(
    symbol: str,
    *,
    notional_usd: float,
    adv_usd: float = 0.0,
    edge_return: float,
    fills: Sequence[Mapping[str, Any]] | None = None,
) -> CostQuote:
    tape_rt = round_trip_cost_from_tape(symbol, list(fills) if fills else None)
    spread_bps = tape_rt * 10_000.0 / 2.0
    impact = kyle_impact_bps(notional_usd, adv_usd)
    rt = tape_rt + 2.0 * impact / 10_000.0
    net = float(edge_return) - rt
    ok = net > 1e-12
    return CostQuote(
        symbol=symbol.upper(),
        spread_bps=round(spread_bps, 4),
        impact_bps=round(impact, 4),
        round_trip=round(rt, 8),
        net_edge=round(net, 8),
        accept=ok,
        reason="edge_gt_cost" if ok else "edge_lt_cost",
    )


def filter_by_edge(
    symbols: Sequence[str],
    *,
    edges: Sequence[float],
    notionals: Sequence[float],
    adv: Sequence[float] | None = None,
    fills_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[list[bool], list[CostQuote]]:
    flags: list[bool] = []
    quotes: list[CostQuote] = []
    for i, sym in enumerate(symbols):
        q = quote(
            sym,
            notional_usd=float(notionals[i]) if i < len(notionals) else 0.0,
            adv_usd=float(adv[i]) if adv and i < len(adv) else 0.0,
            edge_return=float(edges[i]) if i < len(edges) else 0.0,
            fills=(fills_by_symbol or {}).get(str(sym).upper()),
        )
        quotes.append(q)
        flags.append(q.accept)
    return flags, quotes
