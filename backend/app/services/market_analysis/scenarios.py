"""Historical and hypothetical stress scenarios (spec Section 5)."""
from __future__ import annotations

from typing import Mapping

# Approximate cumulative factor shocks over crisis windows (fractional returns).
HISTORICAL_SCENARIO_SHOCKS: dict[str, dict[str, float]] = {
    "2008_replay": {
        "value": -0.25,
        "momentum": -0.30,
        "size": -0.15,
        "quality": -0.20,
        "low_vol": -0.35,
        "growth": -0.28,
        "liquidity": -0.40,
        "market_beta": -0.42,
        "volatility_factor": 0.80,
        "rates_sensitivity": -0.05,
    },
    "2020_replay": {
        "value": -0.18,
        "momentum": -0.25,
        "size": -0.12,
        "quality": -0.10,
        "low_vol": 0.15,
        "growth": -0.22,
        "liquidity": -0.35,
        "market_beta": -0.34,
        "volatility_factor": 0.75,
        "rates_sensitivity": -0.08,
    },
    "2022_replay": {
        "value": 0.05,
        "momentum": -0.12,
        "size": -0.08,
        "quality": -0.05,
        "low_vol": -0.10,
        "growth": -0.18,
        "liquidity": -0.12,
        "market_beta": -0.19,
        "volatility_factor": 0.25,
        "rates_sensitivity": -0.12,
    },
}


def apply_factor_shock(
    exposures: Mapping[str, float | None],
    shocks: Mapping[str, float],
) -> float:
    """Δr = Σ β_k × F_k for a unit-weight position."""
    total = 0.0
    for factor, shock in shocks.items():
        beta = exposures.get(factor)
        if beta is not None:
            total += float(beta) * float(shock)
    return round(total, 6)


def rate_shock_impact(
    exposures: Mapping[str, float | None],
    *,
    bps: float = 200.0,
) -> float | None:
    """+N bps rate shock propagated through rate-sensitive exposures.

    Impact = -β × (bps / 10_000). bps already converted to a decimal rate
    move — do not scale further (GA16-306).
    """
    rate_move = bps / 10_000.0
    beta = exposures.get("rates_sensitivity")
    if beta is None:
        beta = exposures.get("low_vol")
    if beta is None:
        return None
    return round(-float(beta) * rate_move, 6)


def run_stress_scenarios(
    exposures: Mapping[str, float | None],
    *,
    rate_shock_bps: float = 200.0,
) -> dict[str, float | None]:
    """Legacy 3-replay helper. Removal window 2026-11-04; SoT is stress_library."""
    results: dict[str, float | None] = {}
    for name, shocks in HISTORICAL_SCENARIO_SHOCKS.items():
        impact = apply_factor_shock(exposures, shocks)
        has_exposure = any(exposures.get(k) is not None for k in shocks)
        if not has_exposure:
            results[name] = None
        else:
            results[name] = impact
    results[f"rate_shock_{int(rate_shock_bps)}bps"] = rate_shock_impact(
        exposures,
        bps=rate_shock_bps,
    )
    return results
