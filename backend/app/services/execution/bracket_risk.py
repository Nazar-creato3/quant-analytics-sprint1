"""Bracket legs must match the risk engine: geometry, 2×ATR stop, min R:R."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.risk.engine import RiskEngine, RiskParameters, TradeRiskResult


@dataclass(frozen=True, slots=True)
class BracketCheck:
    ok: bool
    stop_loss: float
    take_profit: float
    reasons: tuple[str, ...]
    aligned: bool


def geometry_ok(*, side: str, entry: float, sl: float, tp: float) -> list[str]:
    bad: list[str] = []
    if entry <= 0 or sl <= 0 or tp <= 0:
        return ["non_positive_px"]
    d = str(side).lower()
    if d in {"buy", "long"}:
        if not (sl < entry < tp):
            bad.append("long_order")
    elif d in {"sell", "short"}:
        if not (tp < entry < sl):
            bad.append("short_order")
    else:
        bad.append("side")
    return bad


def rr_ok(*, entry: float, sl: float, tp: float, min_rr: float = 2.0) -> bool:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 1e-12:
        return False
    return reward / risk + 1e-9 >= min_rr


def atr_stop_ok(*, entry: float, sl: float, atr: float, lo: float = 1.5, hi: float = 2.5) -> bool:
    if atr <= 0:
        return True
    dist = abs(entry - sl) / atr
    return lo - 1e-9 <= dist <= hi + 1e-9


def align_with_engine(
    *,
    ticker: str,
    side: str,
    entry: float,
    atr: float,
    stop_loss: float | None,
    take_profit: float | None,
    portfolio_size: float,
    min_rr: float = 2.0,
) -> BracketCheck:
    direction = "short" if str(side).lower() in {"sell", "short"} else "long"
    engine = RiskEngine(RiskParameters(portfolio_size=portfolio_size))
    computed: TradeRiskResult = engine.compute(
        ticker=ticker,
        direction=direction,
        entry_price=entry,
        confidence=0.7,
        atr=atr,
    )
    reasons: list[str] = []
    sl = float(stop_loss or 0.0)
    tp = float(take_profit or 0.0)
    if sl <= 0 or tp <= 0 or geometry_ok(side=direction, entry=entry, sl=sl, tp=tp):
        if computed.is_tradeable:
            sl, tp = computed.stop_loss, computed.take_profit
            reasons.append("snapped_to_engine")
        else:
            return BracketCheck(False, 0.0, 0.0, (computed.reason or "engine_veto",), False)
    geo = geometry_ok(side=direction, entry=entry, sl=sl, tp=tp)
    if geo:
        if computed.is_tradeable:
            sl, tp = computed.stop_loss, computed.take_profit
            reasons.append("geometry_fix")
        else:
            return BracketCheck(False, sl, tp, tuple(geo), False)
    if not rr_ok(entry=entry, sl=sl, tp=tp, min_rr=min_rr):
        if computed.is_tradeable:
            sl, tp = computed.stop_loss, computed.take_profit
            reasons.append("rr_fix")
        else:
            reasons.append("rr")
    if atr > 0 and not atr_stop_ok(entry=entry, sl=sl, atr=atr):
        if computed.is_tradeable:
            sl, tp = computed.stop_loss, computed.take_profit
            reasons.append("atr_stop_fix")
    geo2 = geometry_ok(side=direction, entry=entry, sl=sl, tp=tp)
    ok = not geo2 and rr_ok(entry=entry, sl=sl, tp=tp, min_rr=min_rr)
    if not ok:
        reasons.extend(geo2 or ["inconsistent"])
    return BracketCheck(ok, round(sl, 6), round(tp, 6), tuple(dict.fromkeys(reasons)), bool(reasons))
