"""Shreve / Björk: do not mix physical forecasts with risk-neutral prices."""
from __future__ import annotations


def one_step_binomial_no_arb(*, spot: float, up: float, down: float, rate: float = 0.0) -> bool:
    """True when d < 1+r < u so a unique risk-neutral p* exists."""
    if spot <= 0 or up <= 0 or down <= 0:
        return False
    if down >= up:
        return False
    growth = 1.0 + rate
    return down < growth < up


def physical_factory_ok(*, uses_risk_neutral_drift: bool) -> bool:
    """Maneuver factory must stay on the physical measure."""
    return not uses_risk_neutral_drift
