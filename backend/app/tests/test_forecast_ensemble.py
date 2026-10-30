"""Tests for ensemble, conformal, and scenario framing forecast upgrades."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.forecast.conformal import compute_conformal_intervals
from app.services.forecast.ensemble import EnsembleForecastEngine, MIN_HISTORY_BARS
from app.services.forecast.scenario_framing import build_bull_base_bear


def _synthetic_prices(n: int = 60, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.015, n)
    prices = [100.0]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


class TestEnsembleForecast:
    def test_insufficient_history(self):
        engine = EnsembleForecastEngine()
        result = engine.compute([100.0] * 10, momentum_score=0.6, calibrated_confidence=0.7)
        assert result.insufficient_history is True
        assert result.history_bars == 10

    def test_ensemble_with_sufficient_history(self):
        prices = _synthetic_prices(MIN_HISTORY_BARS + 10)
        engine = EnsembleForecastEngine()
        result = engine.compute(prices, momentum_score=0.62, calibrated_confidence=0.68)
        assert result.insufficient_history is False
        assert result.models_total >= 1
        assert len(result.component_models) >= 1
        assert result.default_view == "sector_relative"
        total_weight = sum(m.weight for m in result.component_models)
        assert 0.99 <= total_weight <= 1.01

    def test_regime_gate_error_fails_closed(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("gate down")

        monkeypatch.setattr("app.services.alpha.regime_gate.detect_regime", boom)
        prices = _synthetic_prices(MIN_HISTORY_BARS + 10)
        result = EnsembleForecastEngine().compute(prices, momentum_score=0.62, calibrated_confidence=0.68)
        assert result.direction_consensus == 0
        assert result.median_return == 0.0
        assert result.direction_suppressed is True
        overlays = result.engine_overlays or {}
        assert "alpha_gate" not in overlays

    def test_to_dict_serializable(self):
        prices = _synthetic_prices(MIN_HISTORY_BARS + 5)
        result = EnsembleForecastEngine().compute(prices, momentum_score=0.55)
        d = result.to_dict()
        assert "median_return" in d
        assert "component_models" in d


class TestConformalIntervals:
    def test_intervals_with_sufficient_data(self):
        prices = _synthetic_prices(50)
        interval = compute_conformal_intervals(prices, point_forecast=0.02)
        assert interval.lower_70 <= interval.median_return <= interval.upper_70
        assert interval.lower_90 <= interval.lower_70
        assert interval.upper_90 >= interval.upper_70
        assert interval.horizon_days == 30

    def test_intervals_short_history_fallback(self):
        prices = _synthetic_prices(15)
        interval = compute_conformal_intervals(prices, point_forecast=0.01)
        assert interval.sufficient_data is False
        assert interval.method in {"vol_scaled_fallback", "split_conformal", "mapie_plus"}


class TestBullBaseBear:
    def test_maps_archetypes(self):
        scenarios = build_bull_base_bear(
            narrative_scenarios={"optimistic": 0.3, "realistic": 0.5, "pessimistic": 0.2},
            median_return=0.03,
        )
        keys = {s.key for s in scenarios}
        assert keys == {"bull", "base", "bear"}
        total_prob = sum(s.probability for s in scenarios)
        assert 0.99 <= total_prob <= 1.01

    def test_default_when_empty(self):
        scenarios = build_bull_base_bear(median_return=0.01)
        assert len(scenarios) == 3
        keys = {s.key for s in scenarios}
        assert keys == {"bull", "base", "bear"}
