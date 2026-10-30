"""Futures notional, leverage, cushion, hedge size (prompt 58A)."""
from __future__ import annotations


def notional(*, qty: float, price: float, point_value: float) -> float:
    """Full underlying exposure, not initial margin."""
    return float(qty) * float(price) * float(point_value)


def portfolio_leverage(*, notionals: list[float], liquid_nav: float) -> float | None:
    if liquid_nav <= 0:
        return None
    return float(sum(abs(x) for x in notionals) / liquid_nav)


def cushion_to_margin_call(
    *,
    liquid_nav: float,
    min_margin: float,
    signed_notional: float,
) -> float | None:
    """Percent move of the underlying against the position until liquid == min margin."""
    if min_margin is None:
        return None
    room = float(liquid_nav) - float(min_margin)
    exposure = abs(float(signed_notional))
    if exposure <= 1e-12:
        return None
    return float(room / exposure)


def hedge_contracts(
    *,
    beta: float,
    portfolio_value: float,
    hedge_share: float,
    fut_price: float,
    point_value: float,
) -> float | None:
    denom = float(fut_price) * float(point_value)
    if denom <= 1e-12:
        return None
    return float(beta * portfolio_value * hedge_share / denom)


def residual_risk(*, portfolio_vol: float, beta: float, index_vol: float) -> float:
    sys = abs(float(beta) * float(index_vol))
    var = max(float(portfolio_vol) ** 2 - sys**2, 0.0)
    return float(var**0.5)
