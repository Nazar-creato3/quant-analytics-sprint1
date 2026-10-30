"""Key-rate scenario math (prompt 63, R5). Bond stress matches 56 duration/convexity."""
from __future__ import annotations

from typing import Sequence


def bond_price_change_pct(*, mod_duration: float, convexity: float, dy: float) -> float:
    """ΔP/P ≈ −D_mod·Δy + ½·C·Δy². dy in decimal (0.01 = 100 bp)."""
    return float(-mod_duration * dy + 0.5 * convexity * dy * dy)


def floater_price_change_pct() -> float:
    return 0.0


def floater_income(*, notional: float, new_rate: float, spread: float, years: float = 1.0) -> float:
    return float(notional * (new_rate + spread) * years)


def deposit_income(*, balance: float, new_rate: float, years: float = 1.0) -> float:
    return float(balance * new_rate * years)


def equity_return_from_rate_beta(*, beta: float, dy: float) -> float:
    """Rates factor treated as yield change; caption: past reaction, not a forecast."""
    return float(beta * dy)


def bootstrap_interval(samples: Sequence[float], *, lo: float = 0.05, hi: float = 0.95) -> tuple[float, float]:
    if not samples:
        return float("nan"), float("nan")
    ordered = sorted(float(x) for x in samples)
    n = len(ordered)

    def _q(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return ordered[idx]

    return _q(lo), _q(hi)
