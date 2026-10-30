"""Tests for Prompt 18 RegimeEngine probabilistic classification."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from app.services.regime import (
    InstrumentSeries,
    MarketRegimeLabel,
    RegimeEngine,
    RegimeScopeType,
)
from app.services.regime.features import (
    build_feature_sequence,
    build_feature_vector,
    prices_to_returns,
)
from app.services.regime.hmm import classify_sequence
from app.services.regime.types import RegimeClassificationResult


def _trend_prices(start: float, step: float, count: int) -> list[float]:
    return [start + step * index for index in range(count)]


def _choppy_prices(start: float, amplitude: float, count: int) -> list[float]:
    return [start + amplitude * math.sin(index * 0.9) for index in range(count)]


def _vol_spike_prices(start: float, count: int, *, spike_at: int, spike_size: float) -> list[float]:
    prices = [start]
    for index in range(1, count):
        if index < spike_at:
            prices.append(start * (1.0 + 0.0003 * math.sin(index * 0.7)))
        elif index == spike_at:
            prices.append(prices[-1] * (1.0 + spike_size))
        elif index == spike_at + 1:
            prices.append(prices[-1] * (1.0 - spike_size * 0.9))
        else:
            sign = 1.0 if index % 2 == 0 else -1.0
            prices.append(prices[-1] * (1.0 + sign * spike_size * 0.14))
    return prices


class TestFeatureExtraction:
    def test_prices_to_returns(self):
        returns = prices_to_returns([100.0, 110.0, 121.0])
        assert len(returns) == 2
        assert returns[0] == pytest.approx(math.log(1.1))
        assert returns[1] == pytest.approx(math.log(1.1))

    def test_bullish_trend_features(self):
        prices = _trend_prices(100.0, 1.5, 40)
        feature = build_feature_vector(prices, [1000.0] * len(prices), spread_bps=8.0)
        assert feature.trend_slope > 0.4
        assert feature.band_position > 0.6

    def test_choppy_range_features(self):
        prices = _choppy_prices(100.0, 1.0, 40)
        feature = build_feature_vector(prices, [1000.0] * len(prices), spread_bps=10.0)
        assert abs(feature.trend_slope) < 0.35
        assert 0.25 <= feature.band_position <= 0.75

    def test_vol_spike_features(self):
        prices = _vol_spike_prices(100.0, 40, spike_at=30, spike_size=0.12)
        feature = build_feature_vector(prices, [1000.0] * len(prices), spread_bps=15.0)
        assert feature.vol_ratio > 1.5


class TestGaussianHMM:
    def test_distribution_sums_to_one(self):
        prices = _trend_prices(100.0, 1.0, 35)
        sequence = build_feature_sequence(prices, [1000.0] * len(prices))
        distribution, confidence = classify_sequence(sequence)
        assert pytest.approx(sum(distribution.values()), rel=1e-6) == 1.0
        assert 0.0 <= confidence <= 1.0


class TestRegimeEngineClassification:
    def setup_method(self) -> None:
        self.engine = RegimeEngine()

    def test_bullish_trend_high_confidence(self):
        prices = _trend_prices(100.0, 2.0, 45)
        volumes = [1200.0 + index * 5 for index in range(len(prices))]
        result = self.engine.classify_instrument(
            prices,
            volumes,
            spread_bps=6.0,
            correlation_cluster=0.25,
        )
        assert result.dominant_regime == MarketRegimeLabel.BULLISH_TREND.value
        assert result.distribution[MarketRegimeLabel.BULLISH_TREND.value] > 0.35
        assert result.confidence >= 0.25

    def test_bearish_trend(self):
        prices = _trend_prices(200.0, -1.8, 45)
        result = self.engine.classify_instrument(prices, spread_bps=7.0)
        assert result.dominant_regime == MarketRegimeLabel.BEARISH_TREND.value
        assert result.distribution[MarketRegimeLabel.BEARISH_TREND.value] > 0.30

    def test_choppy_range(self):
        prices = _choppy_prices(100.0, 0.8, 45)
        result = self.engine.classify_instrument(prices, spread_bps=9.0, correlation_cluster=0.3)
        assert result.dominant_regime == MarketRegimeLabel.CHOPPY_RANGE.value
        assert result.distribution[MarketRegimeLabel.CHOPPY_RANGE.value] > 0.25

    def test_high_volatility_shock(self):
        prices = _vol_spike_prices(100.0, 45, spike_at=32, spike_size=0.18)
        result = self.engine.classify_instrument(
            prices,
            spread_bps=20.0,
            correlation_cluster=0.50,
        )
        assert result.dominant_regime == MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value
        assert result.distribution[MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value] > 0.25

    def test_liquidity_drought(self):
        prices = _choppy_prices(100.0, 0.4, 40)
        result = self.engine.classify_instrument(prices, spread_bps=95.0)
        assert result.dominant_regime == MarketRegimeLabel.LIQUIDITY_DROUGHT.value
        assert result.distribution[MarketRegimeLabel.LIQUIDITY_DROUGHT.value] > 0.25

    def test_macro_uncertainty_via_correlation_cluster(self):
        prices = _choppy_prices(100.0, 0.5, 40)
        result = self.engine.classify_instrument(
            prices,
            spread_bps=12.0,
            correlation_cluster=0.95,
        )
        assert result.dominant_regime == MarketRegimeLabel.MACRO_UNCERTAINTY.value
        assert result.distribution[MarketRegimeLabel.MACRO_UNCERTAINTY.value] > 0.20

    def test_result_validation(self):
        prices = _trend_prices(100.0, 1.0, 30)
        result = self.engine.classify_instrument(prices)
        result.validate()

    def test_invalid_result_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            RegimeClassificationResult(
                distribution={"bullish_trend": 0.4, "choppy_range": 0.4},
                dominant_regime="bullish_trend",
                confidence=0.5,
            ).validate()


class TestRegimeEngineAggregation:
    def setup_method(self) -> None:
        self.engine = RegimeEngine()

    def test_sector_classification(self):
        instruments = {
            1: InstrumentSeries(prices=_trend_prices(100.0, 1.5, 40), spread_bps=8.0),
            2: InstrumentSeries(prices=_trend_prices(50.0, 0.8, 40), spread_bps=9.0),
        }
        result = self.engine.classify_sector(instruments)
        assert result.dominant_regime == MarketRegimeLabel.BULLISH_TREND.value

    def test_global_classification(self):
        sector_data = {
            "technology": {
                1: InstrumentSeries(prices=_trend_prices(100.0, 1.2, 40), spread_bps=7.0),
            },
            "energy": {
                2: InstrumentSeries(prices=_trend_prices(80.0, 0.9, 40), spread_bps=8.0),
            },
        }
        result = self.engine.classify_global(sector_data)
        assert result.dominant_regime == MarketRegimeLabel.BULLISH_TREND.value


class _FakeSession:
    _shared_previous: str | None = None

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def execute(self, _stmt: object):
        class _Result:
            @staticmethod
            def scalar_one_or_none() -> str | None:
                return _FakeSession._shared_previous

        return _Result()


class TestRegimePersistence:
    @pytest.mark.asyncio
    async def test_persist_classification_records_transition(self):
        engine = RegimeEngine()
        session = _FakeSession()
        _FakeSession._shared_previous = MarketRegimeLabel.CHOPPY_RANGE.value

        prices = _trend_prices(100.0, 1.5, 35)
        result = engine.classify_instrument(prices)
        observed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)

        row = await engine.persist_classification(
            session,
            scope_type=RegimeScopeType.INSTRUMENT,
            scope_id="101",
            result=result,
            observed_at=observed_at,
        )

        assert len(session.added) == 1
        assert row.scope_type == RegimeScopeType.INSTRUMENT.value
        assert row.scope_id == "101"
        assert row.previous_regime == MarketRegimeLabel.CHOPPY_RANGE.value
        assert row.dominant_regime == result.dominant_regime
        assert pytest.approx(sum(row.regime_distribution.values()), rel=1e-6) == 1.0
