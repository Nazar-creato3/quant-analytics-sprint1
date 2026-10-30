"""Volatility-normalized size (Turtle N / dollar-vol)."""
from __future__ import annotations


def turtle_unit_usd(*, equity_usd: float, price: float, atr: float, risk_frac: float = 0.01) -> float:
    """One unit: equity * risk_frac / (ATR/price). Liquid names only in the caller."""
    if equity_usd <= 0 or price <= 0 or atr <= 0:
        return 0.0
    atr_frac = atr / price
    if atr_frac <= 1e-8:
        return 0.0
    return equity_usd * risk_frac / atr_frac


def vol_target_scale(
    *,
    current_usd: float,
    equity_usd: float,
    price: float,
    atr: float,
    target_ann_vol: float = 0.12,
    realized_ann_vol: float | None = None,
) -> float:
    """Blend Turtle unit with vol-targeting. Scale stays in [0.4, 1.25]."""
    if current_usd <= 0:
        return 1.0
    unit = turtle_unit_usd(equity_usd=equity_usd, price=price, atr=atr)
    if unit <= 0:
        scale = 1.0
    else:
        scale = min(1.25, max(0.4, unit / current_usd))
    if realized_ann_vol and realized_ann_vol > 1e-6 and target_ann_vol > 0:
        vt = min(1.25, max(0.4, target_ann_vol / realized_ann_vol))
        scale = (scale + vt) / 2.0
    return float(scale)
