"""Tests for GET /forecast/{symbol} hierarchy endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.forecast.outlook_normalize import normalize_market_outlook_item
from app.api.v1.endpoints.forecast import (
    _structured_from_payload,
    router as forecast_router,
)
from app.core.deps import get_current_user_email, get_db
from app.schemas.forecast import StructuredForecastSections
from app.services.analysis.enrichment import enrich_structured_forecast
from app.services.analysis.context import AnalysisContext
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    IntervalForecast,
    PointForecast,
    PointMagnitudeClass,
    RiskForecastLayer,
    ScenarioForecast,
)


def _sample_hierarchy_output() -> ForecastOutput:
    return ForecastOutput(
        instrument_id=1,
        symbol="AAPL",
        as_of="2026-07-18T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.6,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=10,
            p10=-0.05,
            p90=0.05,
            rolling_volatility=0.02,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.1,
            p25=-0.02,
            p50=0.0,
            p75=0.02,
            p95=0.1,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.01),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={
                "composite_risk_score": 0.3,
                "volatility_expansion_probability": 0.42,
            },
            portfolio_metrics={},
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="test",
        ),
        calibrated_confidence=0.75,
        high_confidence=False,
    )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(forecast_router, prefix="/api/v1")

    async def fake_user():
        return "test@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestForecastEndpoint:
    @patch("app.api.v1.endpoints.forecast.gather_analysis_context", new_callable=AsyncMock)
    @patch("app.services.macro_registry.service.load_macro_snapshot_bundle", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.forecast.ExplainabilityLayer")
    @patch("app.api.v1.endpoints.forecast.get_daily_forecast_builder")
    @patch("app.api.v1.endpoints.forecast.get_hierarchy_orchestrator")
    @patch("app.api.v1.endpoints.forecast._resolve_instrument", new_callable=AsyncMock)
    def test_get_forecast_returns_200_with_hierarchy(
        self,
        mock_resolve,
        mock_orchestrator_factory,
        mock_builder_factory,
        mock_explain_cls,
        mock_macro_bundle,
        mock_gather_analysis,
        client,
    ):
        instrument = MagicMock()
        instrument.id = 1
        instrument.symbol = "AAPL"
        mock_resolve.return_value = instrument

        orchestrator = MagicMock()
        orchestrator.get_forecast = AsyncMock(return_value=_sample_hierarchy_output())
        mock_orchestrator_factory.return_value = orchestrator

        builder = MagicMock()
        builder.build = AsyncMock(
            return_value={
                "as_of": "2026-07-18",
                "market_outlook": [],
                "sector_opportunities": [],
                "sector_risks": [],
                "regime_forecast": {},
                "tail_risk_events": [],
                "actionable_summary": [],
                "high_confidence_predictions": [],
                "engines_used": [],
                "factor_exposures": {},
            }
        )
        mock_builder_factory.return_value = builder

        explain = MagicMock()
        explain.explain_for_instrument = AsyncMock(
            return_value=MagicMock(
                forecast_explanation="ok",
                regime_explanation="ok",
                risk_explanation="ok",
                source_metrics={"risk": {}},
            )
        )
        mock_explain_cls.return_value = explain

        mock_macro_bundle.return_value = {"indicators": {"vix": 18.5, "rate_cb": 5.25}}
        mock_gather_analysis.return_value = AnalysisContext(
            symbol="AAPL",
            macro_snippet="VIX 18.5; ставка ФРС 5.25%",
            factor_exposures={"momentum": 0.35},
        )

        resp = client.get("/api/v1/forecast/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert data["hierarchy_output"]["instrument_id"] == 1
        assert data["action_recommendation"] == "hold"
        assert data["confidence"] == 0.75
        assert data["probability_map"]["volatility_expansion_probability"] == pytest.approx(0.42)
        assert data["probability_map"]["momentum_score"] == pytest.approx(0.6)
        assert data["factor_exposures"].get("momentum") == pytest.approx(0.35)
        structured = data.get("structured") or {}
        for item in structured.get("market_outlook") or []:
            assert "scenario" in item
            assert "label_ru" in item
            assert "probability" in item
            assert "engine" in item

    @patch("app.api.v1.endpoints.forecast.gather_analysis_context", new_callable=AsyncMock)
    @patch("app.services.macro_registry.service.load_macro_snapshot_bundle", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.forecast.ExplainabilityLayer")
    @patch("app.api.v1.endpoints.forecast.get_daily_forecast_builder")
    @patch("app.api.v1.endpoints.forecast.get_hierarchy_orchestrator")
    @patch("app.api.v1.endpoints.forecast._resolve_instrument", new_callable=AsyncMock)
    @patch("app.services.market_data.series_loader.load_forecast_price_series", new_callable=AsyncMock)
    def test_get_forecast_include_narrative_false_skips_upgrade_layers(
        self,
        mock_load_prices,
        mock_resolve,
        mock_orchestrator_factory,
        mock_builder_factory,
        mock_explain_cls,
        mock_macro_bundle,
        mock_gather_analysis,
        client,
    ):
        instrument = MagicMock()
        instrument.id = 1
        instrument.symbol = "AAPL"
        mock_resolve.return_value = instrument

        orchestrator = MagicMock()
        orchestrator.get_forecast = AsyncMock(return_value=_sample_hierarchy_output())
        mock_orchestrator_factory.return_value = orchestrator

        builder = MagicMock()
        builder.build = AsyncMock(return_value={"as_of": "2026-07-18", "market_outlook": []})
        mock_builder_factory.return_value = builder

        explain = MagicMock()
        explain.explain_for_instrument = AsyncMock(
            return_value=MagicMock(
                forecast_explanation="ok",
                regime_explanation="ok",
                risk_explanation="ok",
                source_metrics={"risk": {}},
            )
        )
        mock_explain_cls.return_value = explain
        mock_macro_bundle.return_value = {"indicators": {}}
        mock_gather_analysis.return_value = AnalysisContext(symbol="AAPL")

        resp = client.get("/api/v1/forecast/AAPL", params={"include_narrative": "false"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert data["ensemble_forecast"] is None
        mock_load_prices.assert_not_awaited()

    @patch("app.api.v1.endpoints.forecast.ExplainabilityLayer")
    @patch("app.api.v1.endpoints.forecast.get_daily_forecast_builder")
    @patch("app.api.v1.endpoints.forecast.get_hierarchy_orchestrator")
    @patch("app.api.v1.endpoints.forecast._resolve_instrument", new_callable=AsyncMock)
    def test_forecast_health_returns_200(
        self,
        mock_resolve,
        mock_orchestrator_factory,
        mock_builder_factory,
        mock_explain_cls,
        client,
    ):
        instrument = MagicMock()
        instrument.id = 2
        instrument.symbol = "SPY"
        mock_resolve.return_value = instrument

        orchestrator = MagicMock()
        orchestrator.get_forecast = AsyncMock(return_value=_sample_hierarchy_output())
        mock_orchestrator_factory.return_value = orchestrator

        resp = client.get("/api/v1/forecast/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["symbol"] == "SPY"
        assert data["hierarchy_output"]["instrument_id"] == 1

    @patch("app.api.v1.endpoints.forecast.build_market_forecast", new_callable=AsyncMock)
    def test_market_forecast_returns_200(self, mock_market, client):
        mock_market.return_value = {
            "as_of": "2026-07-18T00:00:00+00:00",
            "global_regime": {"dominant_regime": "risk_on"},
            "market_outlook": [
                {
                    "title": "Тестовый прогноз",
                    "what_happens": "Рынок в risk-on",
                    "how": "GlobalMacroRegimeEngine",
                    "where": "SPY, QQQ",
                    "expectations": "Умеренный risk",
                    "prognosis": "Держать exposure",
                    "evidence_basis": ["GlobalMacroRegimeEngine"],
                    "confidence_pct": 72.0,
                }
            ],
            "sector_rotation": [],
            "calibrated_probabilities": {"risk_on": 0.4},
            "macro_indicators": {"vix": 18.0},
            "market_prediction_summary": {
                "paragraphs": ["Тестовый сводный прогноз risk-on."],
                "coverage": ["US_equities"],
                "engines_used": ["GlobalMacroRegimeEngine"],
                "evidence": ["global_regime.dominant=risk_on"],
                "missing_resources": ["market_ohlcv.moex"],
                "confidence_pct": 72.0,
            },
            "scenario_disclosure": {
                "paragraphs": ["По рынку: Наиболее вероятный сценарий — «Реалистичный» (42.0%)."],
                "top_scenario": "realistic",
                "top_probability": 0.42,
                "second_scenario": None,
                "second_probability": None,
                "scenarios": [],
                "evidence": ["global_regime.dominant=risk_on"],
                "engines_used": ["ScenarioEngine"],
                "scope": "market",
            },
        }
        resp = client.get("/api/v1/forecast/market")
        assert resp.status_code == 200
        data = resp.json()
        assert data["market_outlook"][0]["title"] == "Тестовый прогноз"
        assert data["market_outlook"][0]["confidence_pct"] == 72.0
        assert data["market_prediction_summary"]["paragraphs"][0] == "Тестовый сводный прогноз risk-on."
        assert "market_ohlcv.moex" in data["market_prediction_summary"]["missing_resources"]
        assert data["scenario_disclosure"]["top_scenario"] == "realistic"


class TestMarketOutlookNormalization:
    def test_normalize_title_style_point(self):
        item = normalize_market_outlook_item(
            {
                "title": "Макро-контекст",
                "what_happens": "VIX 18.5; ставка ФРС 5.25%",
                "confidence_pct": 72.0,
            },
            default_probability=0.5,
        )
        assert item["scenario"] == "макро_контекст"
        assert item["label_ru"] == "Макро-контекст"
        assert item["probability"] == pytest.approx(0.72)
        assert item["engine"] == "ForecastEngine"

    def test_normalize_preserves_scenario_shape(self):
        raw = {
            "scenario": "bullish",
            "label_ru": "Благоприятный сценарий",
            "probability": 0.42,
            "probability_pct": 42.0,
            "engine": "RegimeEngine",
        }
        item = normalize_market_outlook_item(raw)
        assert item == raw

    def test_structured_from_payload_normalizes_legacy_outlook(self):
        structured = _structured_from_payload(
            {
                "market_outlook": [
                    {
                        "title": "Макро-контекст",
                        "what_happens": "VIX 18.5",
                    }
                ],
                "confidence": 0.65,
            }
        )
        assert len(structured.market_outlook) == 1
        assert structured.market_outlook[0].scenario == "макро_контекст"
        assert structured.market_outlook[0].label_ru == "Макро-контекст"
        assert structured.market_outlook[0].engine == "ForecastEngine"

    def test_enrich_structured_forecast_produces_valid_sections(self):
        from dataclasses import replace

        hierarchy = replace(
            _sample_hierarchy_output(),
            risk_forecast=replace(
                _sample_hierarchy_output().risk_forecast,
                plain_language_summary="Повышенная волатильность",
            ),
        )

        disclosure = MagicMock()
        disclosure.executive_summary = "Краткий disclosure"
        disclosure.to_dict.return_value = {"executive_summary": "Краткий disclosure"}

        analysis = AnalysisContext(
            symbol="AAPL",
            macro_snippet="VIX 18.5; ставка ФРС 5.25%",
        )

        enriched = enrich_structured_forecast(
            StructuredForecastSections(),
            hierarchy=hierarchy,
            payload={
                "sector_opportunities": [
                    {
                        "label": "tech momentum",
                        "label_ru": "Сектор tech: моментум",
                        "probability": 0.6,
                        "engine": "FactorEngine",
                    }
                ]
            },
            analysis=analysis,
            narrator_texts=["Рынок в режиме ожидания"],
            disclosure=disclosure,
            symbol="AAPL",
        )

        assert enriched is not None
        assert all(
            item.scenario and item.label_ru and item.engine is not None
            for item in enriched.market_outlook
        )
        labels = {item.label_ru for item in enriched.market_outlook}
        assert "Макро-контекст" in labels
        assert "AAPL" in labels
        assert "MacroRegistry" in enriched.engines_used
        assert "Повышенная волатильность" in enriched.actionable_summary


class TestForecastProbabilityMap:
    def test_build_hierarchy_probability_map_includes_risk_signals(self):
        from app.services.forecast.probability_map import build_hierarchy_probability_map

        hierarchy = _sample_hierarchy_output()
        prob = build_hierarchy_probability_map(hierarchy)
        assert prob["volatility_expansion_probability"] == pytest.approx(0.42)
        assert prob["interval_p10"] == pytest.approx(-0.05)

    def test_build_metric_validity_flags_missing_risk_metrics(self):
        from app.services.forecast.probability_map import build_metric_validity

        hierarchy = _sample_hierarchy_output()
        validity = build_metric_validity(hierarchy)
        assert validity["volatility_expansion_probability"] is True
        assert validity["event_impact_score"] is False

    def test_resolve_factor_exposures_prefers_assembler_over_placeholder_payload(self):
        from app.services.forecast.probability_map import resolve_factor_exposures_for_forecast

        resolved = resolve_factor_exposures_for_forecast(
            payload_factors={"value": 0.0, "momentum": 0.0},
            analysis_factors={"value": 0.0},
            ticker_analysis_factors={"value": 0.55, "momentum": -0.12},
        )
        assert resolved["value"] == pytest.approx(0.55)
        assert resolved["momentum"] == pytest.approx(-0.12)
