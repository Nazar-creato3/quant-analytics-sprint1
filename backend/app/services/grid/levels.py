"""Grid level price computation — arithmetic and geometric spacing."""
from __future__ import annotations

import math

from app.services.grid.config import GridType


def compute_grid_prices(
    lower: float,
    upper: float,
    num_levels: int,
    grid_type: GridType | str = GridType.GEOMETRIC,
) -> list[float]:
    """
    Return `num_levels + 1` price levels from lower to upper inclusive.
    Arithmetic: equal absolute spacing.
    Geometric: equal percentage spacing (better for volatile assets).
    """
    if lower >= upper:
        raise ValueError("lower must be less than upper")
    if num_levels < 1:
        raise ValueError("num_levels must be >= 1")

    gt = GridType(grid_type) if isinstance(grid_type, str) else grid_type
    n = num_levels

    if gt == GridType.ARITHMETIC:
        step = (upper - lower) / n
        return [round(lower + i * step, 8) for i in range(n + 1)]

    # Geometric: ratio^(1/n) spacing
    if lower <= 0:
        raise ValueError("geometric grid requires positive lower bound")
    ratio = upper / lower
    if ratio <= 0:
        raise ValueError("invalid bounds for geometric grid")
    exp_step = ratio ** (1.0 / n)
    return [round(lower * (exp_step**i), 8) for i in range(n + 1)]


def grid_interval_at_price(
    lower: float,
    upper: float,
    num_levels: int,
    grid_type: GridType | str,
    at_price: float,
) -> float:
    """Effective step size at a given price level."""
    prices = compute_grid_prices(lower, upper, num_levels, grid_type)
    if len(prices) < 2:
        return upper - lower
    # Find nearest level index
    idx = min(range(len(prices)), key=lambda i: abs(prices[i] - at_price))
    if idx < len(prices) - 1:
        return prices[idx + 1] - prices[idx]
    return prices[idx] - prices[idx - 1]


def select_grid_type_for_volatility(realized_vol: float, regime: str) -> GridType:
    """Auto-select grid type from volatility profile."""
    if regime == "high" or realized_vol > 0.35:
        return GridType.GEOMETRIC
    if regime == "low" and realized_vol < 0.15:
        return GridType.ARITHMETIC
    return GridType.GEOMETRIC


def num_levels_for_regime(regime: str, risk_level: str) -> int:
    """More levels in high-vol, fewer in low-vol (Pionex-style AI grid)."""
    base = {"low": 8, "medium": 12, "high": 16}[risk_level]
    if regime == "high":
        return min(100, base + 6)
    if regime == "low":
        return max(4, base - 4)
    return base
