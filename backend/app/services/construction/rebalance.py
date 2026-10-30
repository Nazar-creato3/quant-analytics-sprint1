"""Explicit cash buffer + rebalance calendar + drift bands."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence


@dataclass(frozen=True, slots=True)
class RebalancePolicy:
    calendar: str = "weekly"  # weekly | monthly | daily
    drift_band: float = 0.20  # relative |w-t|/max(|t|,eps)
    cash_buffer: float = 0.20
    weekday: int = 0  # Monday


@dataclass(frozen=True, slots=True)
class RebalanceDecision:
    due: bool
    reason: str
    trades: tuple[tuple[str, float], ...]  # symbol, delta weight
    cash_after: float


def calendar_due(last: date | None, as_of: date, policy: RebalancePolicy) -> bool:
    if last is None:
        return True
    if policy.calendar == "daily":
        return as_of > last
    if policy.calendar == "monthly":
        return (as_of.year, as_of.month) > (last.year, last.month) and as_of.day >= 1
    # weekly: first scheduled weekday strictly after last
    return as_of >= last + timedelta(days=1) and as_of.weekday() == policy.weekday


def drifted(current: float, target: float, band: float) -> bool:
    denom = max(abs(target), 0.01)
    return abs(current - target) / denom > band


def plan(
    symbols: Sequence[str],
    current: Sequence[float],
    target: Sequence[float],
    *,
    as_of: date,
    last: date | None,
    policy: RebalancePolicy | None = None,
) -> RebalanceDecision:
    pol = policy or RebalancePolicy()
    due_cal = calendar_due(last, as_of, pol)
    trades: list[tuple[str, float]] = []
    drift_hit = False
    for sym, cur, tgt in zip(symbols, current, target):
        if drifted(float(cur), float(tgt), pol.drift_band):
            drift_hit = True
            trades.append((str(sym).upper(), round(float(tgt) - float(cur), 8)))
    if not due_cal and not drift_hit:
        cash = max(0.0, 1.0 - sum(abs(float(x)) for x in current))
        return RebalanceDecision(False, "inside_band", (), round(cash, 8))
    if due_cal and not trades:
        trades = [
            (str(s).upper(), round(float(t) - float(c), 8))
            for s, c, t in zip(symbols, current, target)
            if abs(float(t) - float(c)) > 1e-8
        ]
        reason = "calendar"
    else:
        reason = "drift" if drift_hit and not due_cal else "calendar+drift"
    new_w = list(current)
    idx = {str(s).upper(): i for i, s in enumerate(symbols)}
    for sym, dw in trades:
        i = idx.get(sym)
        if i is not None:
            new_w[i] = float(new_w[i]) + dw
    cash = max(0.0, 1.0 - sum(abs(float(x)) for x in new_w))
    if cash + 1e-12 < pol.cash_buffer:
        # Force cash buffer: scale risky weights
        risky = sum(abs(float(x)) for x in new_w)
        room = 1.0 - pol.cash_buffer
        if risky > room > 0:
            scale = room / risky
            trades = [
                (str(s).upper(), round(float(new_w[i]) * scale - float(current[i]), 8))
                for i, s in enumerate(symbols)
            ]
            cash = pol.cash_buffer
            reason += "+cash_buffer"
    return RebalanceDecision(True, reason, tuple(trades), round(cash, 8))
