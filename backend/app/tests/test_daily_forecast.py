"""Tests for structured daily forecast builder."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.forecast.daily_builder import DailyForecastBuilder, _build_market_outlook
from app.services.forecast.types import ForecastDirection, ForecastSignals, InstrumentForecast
from app.services.regime.types import MarketRegimeLabel


def _sample_forecast(**overrides) -> InstrumentForecast:
    base = InstrumentForecast(
        instrument_id=1,
        regime_distribution={
            MarketRegimeLabel.BULLISH_TREND.value: 0.55,
            MarketRegimeLabel.BEARISH_TREND.value: 0.15,
            MarketRegimeLabel.CHOPPY_RANGE.value: 0.30,
        },
        risk_flags=("tail_risk",),
        confidence=0.72,
        contributing_factors=(),
        composite_risk_score=0.42,
        signals=ForecastSignals(
            short_term_momentum=0.5,
            momentum_direction=ForecastDirection.BULLISH,
            tail_risk_score=0.4,
            volatility_expansion_probability=0.35,
            correlation_shift_score=0.2,
            liquidity_deterioration_score=0.1,
            event_impact_score=0.25,
        ),
        dominant_regime=MarketRegimeLabel.BULLISH_TREND.value,
    )
    if overrides:
        return InstrumentForecast(**{**base.__dict__, **overrides})
    return base


class TestDailyForecastBuilder:
    def test_market_outlook_has_three_scenarios(self):
        outlook = _build_market_outlook(_sample_forecast())
        assert len(outlook) == 3
        assert outlook[0]["engine"] == "RegimeEngine"
        assert sum(item["probability"] for item in outlook) <= 1.01

    @pytest.mark.asyncio
    async def test_build_composes_sections(self):
        builder = DailyForecastBuilder(
            forecast_engine=MagicMock(),
            factor_engine=MagicMock(),
        )
        forecast = _sample_forecast()
        builder._forecast_engine.forecast_instrument = AsyncMock(return_value=forecast)
        builder._factor_engine.estimate_for_instrument = AsyncMock(return_value=[])

        explain_snapshot = MagicMock()
        explain_snapshot.source_metrics = {"risk": {"tail_risk_score": 0.4}}
        explain_snapshot.forecast_explanation = "test"
        explain_snapshot.regime_explanation = "test"
        explain_snapshot.risk_explanation = "test"

        with patch(
            "app.services.forecast.daily_builder.ExplainabilityLayer"
        ) as explain_cls:
            explain_cls.return_value.explain_for_instrument = AsyncMock(return_value=explain_snapshot)
            with patch.object(builder, "_scenario_probabilities", AsyncMock(return_value={})):
                payload = await builder.build(
                    AsyncMock(),
                    instrument_id=1,
                    symbol="AAPL",
                )

        assert payload["symbol"] == "AAPL"
        assert payload["market_outlook"]
        assert payload["actionable_summary"]
        assert "RegimeEngine" in payload["engines_used"]
