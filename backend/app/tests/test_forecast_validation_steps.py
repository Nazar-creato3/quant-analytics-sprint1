"""Tests for forecast validation steps 1-4."""
from __future__ import annotations

from app.services.chat.deep_advisor import finalize_advisor_reply
from app.services.forecast.ensemble import (
    LIVE_ACCURACY_FLOOR,
    EnsembleForecastEngine,
    MomentumDirectionAccuracy,
    _aapl_bearish_momentum_weight_factor,
    _momentum_bull_bear_accuracy,
    _should_invert_aapl_bearish_momentum,
)
from app.services.forecast.types import ForecastDirection, ForecastSignals
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine


def _trend_prices(start: float, step: float, count: int) -> list[float]:
    return [start + step * index for index in range(count)]


def test_finalize_advisor_reply_strips_confidence_horizon_leak():
    raw = (
        "Краткий тезис по SBER.\n"
        "Negative | horizon ~10d | confidence 36% (аналитическая справка)."
    )
    cleaned = finalize_advisor_reply(raw)
    assert "confidence 36%" not in cleaned


def test_hierarchy_validation_calls_forecast_engine_not_hardcoded_signals():
    captured: list[ForecastSignals] = []

    class SpyForecastEngine:
        def compute_from_inputs(self, bundle):
            from app.services.forecast.engine import ForecastEngine

            result = ForecastEngine().compute_from_inputs(bundle)
            captured.append(result.signals)
            return result

    engine = HierarchyValidationEngine(forecast_engine=SpyForecastEngine())
    prices = [100.0 + (index % 7) * 0.5 + index * 0.05 for index in range(80)]
    report = engine.run(instrument_id=1, prices=prices, sector="technology")
    assert report.total_points > 0
    assert captured, "ForecastEngine.compute_from_inputs must be invoked in replay loop"
    assert not all(
        s.short_term_momentum == 0.4 and s.momentum_direction == ForecastDirection.NEUTRAL
        for s in captured
    ), "hardcoded stub signals must not be used"


def test_aapl_bearish_inversion_when_anti_predictive():
    mom_acc = MomentumDirectionAccuracy(
        bullish_accuracy=0.54,
        bearish_accuracy=0.29,
        bullish_n=61,
        bearish_n=24,
    )
    assert _should_invert_aapl_bearish_momentum(mom_acc) is True


def test_aapl_bearish_weight_reduced_when_below_random_and_not_inverted():
    mom_acc = MomentumDirectionAccuracy(
        bullish_accuracy=0.54,
        bearish_accuracy=0.29,
        bullish_n=61,
        bearish_n=24,
    )
    factor = _aapl_bearish_momentum_weight_factor(mom_acc)
    assert factor < 1.0
    assert factor >= 0.35


def test_ensemble_suppresses_direction_when_live_accuracy_below_floor():
    prices = _trend_prices(100.0, 0.2, 70)
    engine = EnsembleForecastEngine()
    result = engine.compute(
        prices,
        symbol="AAPL",
        momentum_score=0.62,
        calibrated_confidence=0.68,
        live_direction_accuracy=LIVE_ACCURACY_FLOOR - 0.05,
        live_accuracy_sample_size=30,
    )
    assert result.direction_suppressed is True
    assert result.direction_consensus == 0
    assert result.suppression_message_ru == "недостаточно предсказательной силы для направления"


def test_momentum_bull_bear_tracking_returns_counts():
    prices = _trend_prices(100.0, 0.15, 80)
    acc = _momentum_bull_bear_accuracy(prices)
    assert acc.bullish_n + acc.bearish_n > 0
