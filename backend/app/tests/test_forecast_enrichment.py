"""Tests for structured forecast enrichment."""
from __future__ import annotations

from app.schemas.forecast import StructuredForecastSections
from app.services.analysis.context import AnalysisContext, EventRiskSummary, NewsHeadline
from app.services.analysis.enrichment import enrich_structured_forecast
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    GlobalRegimeResult,
    IntervalForecast,
    PointForecast,
    PointMagnitudeClass,
    RiskForecastLayer,
    RiskItem,
    ScenarioForecast,
    ScenarioForecastItem,
    SectorRegimeContext,
    SectorRotationFlag,
    SectorRotationScore,
)
from app.services.regime.types import RegimeClassificationResult


def _hierarchy_output() -> ForecastOutput:
    regime = RegimeClassificationResult(
        distribution={"bullish_trend": 0.6},
        dominant_regime="bullish_trend",
        confidence=0.7,
        feature_sequence=(),
    )
    sector = SectorRegimeContext(
        sector="technology",
        regime=regime,
        rotation=SectorRotationScore(
            sector="technology",
            score_1w=0.1,
            score_1m=0.2,
            score_3m=0.3,
            composite_score=0.25,
            rotation_flag=SectorRotationFlag.SECTORS_STRENGTHENING,
        ),
        sector_momentum=0.08,
    )
    return ForecastOutput(
        instrument_id=1,
        symbol="NVDA",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.62,
            plain_language_summary="Импульс положительный.",
        ),
        interval_forecast=IntervalForecast(
            horizon_days=10,
            p10=-0.04,
            p90=0.07,
            rolling_volatility=0.02,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.08,
            p25=-0.01,
            p50=0.02,
            p75=0.04,
            p95=0.09,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(
            scenarios=(
                ScenarioForecastItem(
                    name="realistic",
                    scenario_type="realistic",
                    label_ru="Реалистичный",
                    probability=0.42,
                    impact=0.02,
                    impact_narrative_ru="Базовый сценарий роста.",
                ),
            ),
            scenario_dispersion=0.03,
        ),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={"composite_risk_score": 0.35},
            portfolio_metrics={},
            plain_language_summary="Умеренный риск.",
            risk_items=(
                RiskItem(
                    metric="volatility_expansion_probability",
                    score=0.55,
                    severity="medium",
                    plain_language_summary="Волатильность: 55% — повышенное внимание",
                ),
            ),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="balanced",
            rule_id="test",
        ),
        calibrated_confidence=0.72,
        high_confidence=False,
        global_regime=GlobalRegimeResult(
            distribution={"risk_on": 0.5},
            dominant_regime="risk_on",
            confidence=0.68,
            confirmation_window_bars=5,
            confidence_damping_active=False,
            credit_spread_proxy=0.02,
        ),
        sector_regime=sector,
        instruction_block="Что делать по NVDA: держать.",
    )


class _FakeDisclosure:
    def to_dict(self) -> dict:
        return {"executive_summary": "Сводка сценариев."}


def test_enrich_adds_macro_news_and_gaps():
    hierarchy = _hierarchy_output()
    analysis = AnalysisContext(
        symbol="NVDA",
        news_headlines=[NewsHeadline(title="NVDA beats estimates")],
        macro_snippet="Макро-фон: VIX 17.0.",
        macro_indicators={"vix": 17.0},
        factor_exposures={"momentum": 0.35},
        data_gaps=["macro_series_normalized.cpi"],
    )
    result = enrich_structured_forecast(
        StructuredForecastSections(),
        hierarchy=hierarchy,
        payload=None,
        analysis=analysis,
        narrator_texts=["Сигналы согласованы."],
        disclosure=_FakeDisclosure(),
        symbol="NVDA",
    )
    assert result.actionable_summary
    assert any("NVDA" in line for line in result.actionable_summary)
    assert any("ограничения данных" in line.lower() for line in result.actionable_summary)
    assert any("FactorEngine" in e for e in result.engines_used)
    assert any("NewsAggregator" in e for e in result.engines_used)
    outlook_text = str(result.market_outlook)
    assert "NVDA beats" in outlook_text or "Новости" in outlook_text


def test_enrich_adds_event_risk_tail_item():
    hierarchy = _hierarchy_output()
    analysis = AnalysisContext(
        symbol="NVDA",
        event_risk=EventRiskSummary(
            score=0.6,
            news_impact_probability=0.45,
            article_count=2,
            reason="earnings proximity",
        ),
    )
    result = enrich_structured_forecast(
        StructuredForecastSections(),
        hierarchy=hierarchy,
        payload=None,
        analysis=analysis,
        narrator_texts=[],
        disclosure=_FakeDisclosure(),
        symbol="NVDA",
    )
    assert result.tail_risk_events
    assert any("EventRiskLayer" in str(item) for item in result.tail_risk_events)
