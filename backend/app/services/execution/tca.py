"""Honest paper TCA: half-spread vs decision mid. Not venue markout."""

from __future__ import annotations

from typing import Any


def one_way_spread_bps(symbol: str) -> float:
    from app.services.forecast.cost_model import round_trip_cost_return

    return float(round_trip_cost_return(symbol) * 10_000.0 / 2.0)


def apply_quote_or_spread(
    mid: float,
    side: str,
    *,
    symbol: str = "",
    bid: float | None = None,
    ask: float | None = None,
    spread_bps: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """Use live bid/ask when both exist; otherwise half-spread model."""
    try:
        b = float(bid) if bid is not None else 0.0
        a = float(ask) if ask is not None else 0.0
    except (TypeError, ValueError):
        b = a = 0.0
    if b > 0 and a > b:
        mid_q = (a + b) / 2.0
        side_l = (side or "").strip().lower()
        fill = a if side_l not in {"sell", "short"} else b
        return fill, {
            "decision_mid": round(mid_q, 6),
            "filled": round(fill, 6),
            "side": side_l or "buy",
            "bid": round(b, 6),
            "ask": round(a, 6),
            "markout_vs_mid_bps": round(((fill - mid_q) / mid_q) * 10_000.0, 4),
            "model": "quote_bid_ask_paper",
            "note_ru": "Бумажный fill по котировке bid/ask, не mid. Не live OMS.",
        }
    return apply_half_spread(mid, side, symbol=symbol, spread_bps=spread_bps)


def apply_half_spread(
    mid: float,
    side: str,
    *,
    symbol: str = "",
    spread_bps: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """Buy pays mid + half spread; sell receives mid − half spread."""
    px = float(mid)
    bps = float(spread_bps) if spread_bps is not None else one_way_spread_bps(symbol)
    slip = px * (bps / 10_000.0)
    side_l = (side or "").strip().lower()
    if side_l in {"sell", "short"}:
        fill = px - slip
    else:
        fill = px + slip
    if fill <= 0:
        fill = px
    return fill, {
        "decision_mid": round(px, 6),
        "filled": round(fill, 6),
        "side": side_l or "buy",
        "half_spread_bps": round(bps, 4),
        "markout_vs_mid_bps": round(((fill - px) / px) * 10_000.0, 4) if px else 0.0,
        "model": "half_spread_paper",
        "note_ru": "Бумажный fill не mid: половина спреда из cost_model. Это не live TCA.",
    }
