"""Regression tests for historical replay scenarios (Prompt 81)."""
from __future__ import annotations

import pytest

from app.services.market_analysis.scenarios import run_stress_scenarios


def test_replay_scenarios_nonzero_with_factor_exposure():
    exposures = {
        "market_beta": 1.2,
        "momentum": 0.35,
        "value": -0.1,
        "rates_sensitivity": 0.15,
    }
    results = run_stress_scenarios(exposures)
    for key in ("2008_replay", "2020_replay", "2022_replay"):
        assert key in results
        assert results[key] is not None
        assert results[key] != 0.0


def test_replay_unavailable_without_exposures():
    results = run_stress_scenarios({})
    for key in ("2008_replay", "2020_replay", "2022_replay"):
        assert results[key] is None


def test_rate_shock_unavailable_without_beta():
    results = run_stress_scenarios({"momentum": None, "market_beta": None})
    rate_key = "rate_shock_200bps"
    assert results[rate_key] is None


def test_rate_shock_impact_no_extra_scale_after_bps():
    """GA16-306: after bps→decimal, do not multiply by 50.

    β=0.15, +200 bps → -0.15 × 0.02 = -0.003 (not -0.15).
    """
    from app.services.market_analysis.scenarios import rate_shock_impact

    assert rate_shock_impact({"rates_sensitivity": 0.15}, bps=200.0) == -0.003
    assert rate_shock_impact({"rates_sensitivity": 1.0}, bps=100.0) == -0.01


def test_invalid_exposure_map_does_not_fake_zero_replay():
    """Empty betas must not masquerade as a calculated 0% impact."""
    results = run_stress_scenarios({"market_beta": None, "momentum": None})
    assert results["2008_replay"] is None
