"""Slippage from our fills vs arrival — not Spectral tape."""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Mapping

from app.services.forecast.cost_model import round_trip_cost_return


def implementation_shortfall_bps(arrival: float, fill: float, side: str) -> float | None:
    """Positive = we paid worse than arrival. Side: buy/long vs sell/short."""
    try:
        mid = float(arrival)
        px = float(fill)
    except (TypeError, ValueError):
        return None
    if mid <= 0 or px <= 0:
        return None
    raw = (px - mid) / mid * 10_000.0
    side_l = str(side or "").strip().lower()
    if side_l in {"sell", "short"}:
        return round(-raw, 4)
    return round(raw, 4)


def _arrival(row: Mapping[str, Any]) -> float | None:
    for key in ("arrival_price", "signal_generated_price", "decision_mid", "vwap"):
        if row.get(key) not in (None, ""):
            try:
                px = float(row[key])
            except (TypeError, ValueError):
                continue
            if px > 0:
                return px
    return None


def fill_row_to_shortfall(row: Mapping[str, Any]) -> float | None:
    arrival = _arrival(row)
    fill = row.get("fill_price") or row.get("filled")
    side = row.get("side") or row.get("direction") or "buy"
    if arrival is None:
        return None
    return implementation_shortfall_bps(arrival, fill, str(side))


def _summarize(sample: list[float]) -> dict[str, float]:
    if not sample:
        return {"n": 0.0, "mean_bps": 0.0, "median_bps": 0.0, "p90_bps": 0.0}
    ordered = sorted(sample)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {
        "n": float(len(sample)),
        "mean_bps": round(sum(sample) / len(sample), 4),
        "median_bps": round(float(median(sample)), 4),
        "p90_bps": round(float(p90), 4),
    }


def model_from_fills(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Global + per-symbol IS. Conservative predicted cost uses p90 when n is large."""
    by_sym: dict[str, list[float]] = defaultdict(list)
    all_bps: list[float] = []
    for row in rows:
        bps = fill_row_to_shortfall(row)
        if bps is None:
            continue
        all_bps.append(bps)
        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
        if sym:
            by_sym[sym].append(bps)
    payload = _summarize(all_bps)
    payload["by_symbol"] = {sym: _summarize(vals) for sym, vals in by_sym.items()}
    return payload


def predicted_cost_bps(
    symbol: str,
    model: Mapping[str, Any] | None,
    *,
    conservative: bool = True,
) -> float:
    """Own-tape when ≥8 fills (symbol first, else book). Else cost_model half-spread."""
    fallback = round_trip_cost_return(symbol) * 10_000.0 / 2.0
    if not model:
        return fallback
    by_sym = model.get("by_symbol") or {}
    row = by_sym.get(str(symbol).upper()) if isinstance(by_sym, dict) else None
    chosen = row if row and float(row.get("n") or 0) >= 8 else model
    n = float(chosen.get("n") or 0.0)
    if n < 8:
        return fallback
    mean = max(0.0, float(chosen.get("mean_bps") or 0.0))
    p90 = max(0.0, float(chosen.get("p90_bps") or mean))
    return p90 if conservative else mean


def round_trip_cost_from_tape(symbol: str, fills: list[Mapping[str, Any]] | None) -> float:
    """Return units, same scale as cost_model.round_trip_cost_return."""
    if not fills:
        return round_trip_cost_return(symbol)
    model = model_from_fills(list(fills))
    return predicted_cost_bps(symbol, model) * 2.0 / 10_000.0
