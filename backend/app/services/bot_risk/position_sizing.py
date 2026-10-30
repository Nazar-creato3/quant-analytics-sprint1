"""
Risk-based position sizing for bots.

Uses the same % risk-per-trade formula as ``RiskEngine`` (maneuver path):
  risk_amount = portfolio * risk_pct / 100
  quantity    = risk_amount / |entry - stop_loss|

Freqtrade Edge is not wired yet (sidecar = signal bridge only); this module
is the single sizing source for all bot types until Edge hooks land.
"""
from __future__ import annotations

from app.services.bot_risk.types import PositionSizeResult


def compute_risk_based_size(
    *,
    portfolio_usd: float,
    entry_price: float,
    stop_loss_price: float,
    risk_pct: float,
    max_position_pct: float,
    direction: str = "long",
) -> PositionSizeResult:
    if portfolio_usd <= 0 or entry_price <= 0:
        return PositionSizeResult(
            allowed=False,
            reason="Invalid portfolio or entry price",
            stop_loss_price=stop_loss_price,
        )

    if direction == "long" and stop_loss_price >= entry_price:
        return PositionSizeResult(
            allowed=False,
            reason="Long stop must be below entry",
            stop_loss_price=stop_loss_price,
        )
    if direction == "short" and stop_loss_price <= entry_price:
        return PositionSizeResult(
            allowed=False,
            reason="Short stop must be above entry",
            stop_loss_price=stop_loss_price,
        )

    risk_per_unit = abs(entry_price - stop_loss_price)
    if risk_per_unit < 1e-9:
        return PositionSizeResult(
            allowed=False,
            reason="Stop distance too small",
            stop_loss_price=stop_loss_price,
        )

    risk_amount = portfolio_usd * (risk_pct / 100.0)
    quantity = risk_amount / risk_per_unit
    notional = quantity * entry_price

    position_cap = portfolio_usd * (max_position_pct / 100.0)
    if notional > position_cap:
        notional = position_cap
        quantity = notional / entry_price
        risk_amount = quantity * risk_per_unit

    if notional <= 0 or quantity <= 0:
        return PositionSizeResult(
            allowed=False,
            reason="Computed size is zero",
            stop_loss_price=stop_loss_price,
        )

    effective_risk_pct = (risk_amount / portfolio_usd) * 100.0 if portfolio_usd else 0.0
    return PositionSizeResult(
        allowed=True,
        reason="Risk sizing OK",
        notional_usd=round(notional, 4),
        quantity=round(quantity, 8),
        risk_amount_usd=round(risk_amount, 4),
        risk_pct=round(effective_risk_pct, 4),
        stop_loss_price=round(stop_loss_price, 6),
    )


def default_stop_loss_price(
    *,
    entry_price: float,
    stop_loss_pct: float,
    direction: str = "long",
    anchor_price: float | None = None,
) -> float:
    """Default stop below entry (long) or below grid lower bound."""
    base = anchor_price if anchor_price is not None else entry_price
    if direction == "long":
        return round(base * (1.0 - stop_loss_pct), 6)
    return round(base * (1.0 + stop_loss_pct), 6)
