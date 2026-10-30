"""Volatility-based auto-calibration for grid bots."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.approval.context import realized_volatility
from app.services.grid.config import AutoGridResponse, GridConfigModel, GridType, RiskLevel
from app.services.grid.levels import num_levels_for_regime, select_grid_type_for_volatility


# k multiplier for range = price ± k × realized_vol (annualized fraction)
_RISK_K: dict[RiskLevel, float] = {
    "low": 1.5,
    "medium": 2.5,
    "high": 3.5,
}


def _volatility_regime(realized_vol: float) -> str:
    if realized_vol > 0.35:
        return "high"
    if realized_vol > 0.15:
        return "medium"
    return "low"


def calculate_auto_grid(
    symbol: str,
    capital: float,
    current_price: float,
    closes: Sequence[float],
    *,
    risk_level: RiskLevel = "medium",
    grid_type: GridType | None = None,
) -> AutoGridResponse:
    """
    Auto-calibrate grid range and levels from recent realized volatility.
    Reuses existing `realized_volatility` from approval/regime stack — no duplicate logic.
    """
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if capital <= 0:
        raise ValueError("capital must be positive")

    rv = realized_volatility(list(closes)) if closes else 0.20
    if rv <= 0:
        rv = 0.20  # ~20% annualized fallback when history thin

    regime = _volatility_regime(rv)
    k = _RISK_K[risk_level]
    # Convert annualized vol to a range fraction (≈ 1σ move over ~30d horizon)
    range_frac = min(0.25, max(0.04, rv * k / math.sqrt(252) * math.sqrt(30)))

    lower = round(current_price * (1.0 - range_frac), 6)
    upper = round(current_price * (1.0 + range_frac), 6)
    lower = max(lower, current_price * 0.5)
    upper = min(upper, current_price * 2.0)

    n_levels = num_levels_for_regime(regime, risk_level)
    gt = grid_type or select_grid_type_for_volatility(rv, regime)

    stop_loss = round(lower * 0.97, 6)
    take_profit = round(upper * 1.03, 6)

    cfg = GridConfigModel(
        symbol=symbol,
        upper_bound=upper,
        lower_bound=lower,
        num_levels=n_levels,
        grid_type=gt,
        capital_allocated=capital,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )

    return AutoGridResponse(
        config=cfg,
        current_price=current_price,
        realized_volatility=round(rv, 6),
        volatility_regime=regime,
        num_levels=n_levels,
        grid_type=gt,
    )
