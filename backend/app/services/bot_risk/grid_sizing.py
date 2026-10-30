"""Risk-based level sizing for grid bots."""
from __future__ import annotations

from app.services.bot_risk.guard import get_bot_risk_guard
from app.services.grid.engine import GridLevel


def apply_risk_sizing_to_levels(
    levels: list[GridLevel],
    *,
    total_capital: float,
    entry_price: float,
    stop_loss_price: float,
    grid_count: int,
) -> None:
    """Resize grid level quantities using shared risk-per-trade sizing."""
    if entry_price <= 0 or stop_loss_price <= 0 or not levels:
        return
    guard = get_bot_risk_guard()
    sized = guard.compute_position_size(
        portfolio_usd=total_capital,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
    )
    if not sized.allowed:
        return
    per_level_notional = sized.notional_usd / max(grid_count, 1)
    for level in levels:
        if level.price > 0:
            level.quantity = round(per_level_notional / level.price, 6)
