"""Longstaff–Schwartz style hold vs close on a path ensemble (physical measure)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LsmDecision:
    continue_value: float
    exercise_value: float
    hold: bool
    reason: str


def _ols_intercept_slope(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    if n < 3:
        return 0.0, 0.0
    mx = sum(x) / n
    my = sum(y) / n
    den = sum((a - mx) ** 2 for a in x)
    if den <= 1e-12:
        return my, 0.0
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / den
    return my - slope * mx, slope


def lsm_hold_or_close(
    *,
    mark_pnl: float,
    remaining_payoffs: list[float],
    state_features: list[float],
) -> LsmDecision:
    """Regress continuation payoff on a 1-D state (e.g. moneyness / remaining days)."""
    if not remaining_payoffs or not state_features or len(remaining_payoffs) != len(state_features):
        return LsmDecision(0.0, mark_pnl, mark_pnl > 0, "insufficient_paths")
    intercept, slope = _ols_intercept_slope(state_features, remaining_payoffs)
    x0 = state_features[-1]
    continuation = intercept + slope * x0
    hold = continuation > mark_pnl
    return LsmDecision(
        continue_value=round(continuation, 6),
        exercise_value=round(mark_pnl, 6),
        hold=hold,
        reason="hold" if hold else "exercise",
    )
