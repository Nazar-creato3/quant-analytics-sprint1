"""Days-to-exit and square-root impact (prompt 64)."""
from __future__ import annotations

from math import exp, log, sqrt
from statistics import median


def median_adv(turnovers: list[float]) -> float | None:
    clean = [x for x in turnovers if x is not None and x > 0]
    if not clean:
        return None
    return float(median(clean))


def days_to_exit(position_value: float, adv: float | None, participation: float) -> float | None:
    if adv is None or adv <= 0 or participation <= 0 or position_value <= 0:
        return None
    return position_value / (participation * adv)


def square_root_impact(
    *,
    position_value: float,
    adv: float | None,
    sigma_daily: float | None,
    half_spread: float = 0.0,
    kyle_y: float = 1.0,
) -> float | None:
    if adv is None or adv <= 0 or sigma_daily is None or position_value <= 0:
        return None
    return kyle_y * sigma_daily * sqrt(position_value / adv) + half_spread


def corwin_schultz_spread(high: float, low: float) -> float | None:
    """One high/low pair, Corwin–Schultz 2012 (γ not observed).

    β = ln(H/L)², α = (√(2β) − √β) / (3 − 2√2),
    S = 2(e^α − 1) / (1 + e^α). Not the relative range (H−L)/mid.
    """
    if high <= 0 or low <= 0 or high < low:
        return None
    if high == low:
        return 0.0
    beta = log(high / low) ** 2
    alpha = (sqrt(2.0 * beta) - sqrt(beta)) / (3.0 - 2.0 * sqrt(2.0))
    if alpha <= 0:
        return 0.0
    return 2.0 * (exp(alpha) - 1.0) / (1.0 + exp(alpha))
