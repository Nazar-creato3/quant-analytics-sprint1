"""Tests for LLM scenario verdict generation and cache."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.forecast.scenario_verdict_llm import (
    SCENARIO_VERDICT_SYSTEM_RU,
    parse_verdict_layers,
    shared_multiword_phrases,
    verdict_data_fingerprint,
    _build_structured_context,
    _looks_like_template_boilerplate,
)
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


def _minimal_hierarchy(symbol: str, *, confidence: float, as_of: str) -> ForecastOutput:
    return ForecastOutput(
        instrument_id=1,
        symbol=symbol,
        as_of=as_of,
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.NEUTRAL,
            expected_return_sign=0,
            momentum_score=0.45,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=10,
            p10=-0.03,
            p90=0.04,
            rolling_volatility=0.02,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.05,
            p25=-0.01,
            p50=0.0,
            p75=0.01,
            p95=0.05,
            method="test",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.1),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={"composite_risk_score": 0.35},
            portfolio_metrics={},
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="test",
        ),
        calibrated_confidence=confidence,
        high_confidence=False,
    )


class TestVerdictFingerprint:
    def test_different_symbols_same_scenarios_differ(self):
        disclosure = {
            "scenarios": [{"archetype": "realistic", "probability": 0.325}],
            "top_scenario": "realistic",
            "top_probability": 0.325,
            "breakdown": {"macro_score": 0.2, "symbol_score": 0.5},
            "expected_move": 0.01,
            "confidence": 0.45,
        }
        h_aapl = _minimal_hierarchy("AAPL", confidence=0.45, as_of="2026-08-06T00:00:00Z")
        h_btc = _minimal_hierarchy("BTC-USD", confidence=0.45, as_of="2026-08-06T00:00:00Z")
        assert verdict_data_fingerprint("AAPL", h_aapl, disclosure) != verdict_data_fingerprint(
            "BTC-USD", h_btc, disclosure
        )

    def test_data_change_invalidates_fingerprint(self):
        h = _minimal_hierarchy("AAPL", confidence=0.45, as_of="2026-08-06T00:00:00Z")
        d1 = {"top_probability": 0.32, "scenarios": []}
        d2 = {"top_probability": 0.41, "scenarios": []}
        assert verdict_data_fingerprint("AAPL", h, d1) != verdict_data_fingerprint("AAPL", h, d2)


class TestDistinctivenessHelper:
    def test_detects_identical_boilerplate(self):
        aapl = (
            "Почему - Импульс слабый или отрицательный, базовый расчётный ход около -1.2%, "
            "режим волатильности — умеренная."
        )
        btc = (
            "Почему - Импульс слабый или отрицательный, базовый расчётный ход около -1.2%, "
            "режим волатильности — умеренная."
        )
        shared = shared_multiword_phrases(aapl, btc, min_words=5)
        assert shared

    def test_different_texts_no_long_shared_phrases(self):
        aapl = (
            "Почему - У Apple сейчас слабый импульс, но сектор технологий держит поддержку "
            "и движение может быть около плюс двух процентов."
        )
        btc = (
            "Почему - У Bitcoin волатильность выше нормы, импульс скачет и диапазон шире "
            "обычного для акций."
        )
        shared = shared_multiword_phrases(aapl, btc, min_words=5)
        assert not shared


class TestParseVerdictLayers:
    def test_parses_standard_format(self):
        raw = (
            "Вердикт - Apple в реалистичном сценарии.\n"
            "Почему - Импульс слабый, но tech-сектор держит.\n"
            "Что изменит взгляд - пробой 180$.\n"
            "Действие - не наращивать риск."
        )
        layers = parse_verdict_layers(raw)
        assert layers and len(layers) == 4

    def test_rejects_template_boilerplate(self):
        text = "Почему - импульс слабый или отрицательный, базовый расчётный ход около -1%"
        assert _looks_like_template_boilerplate(text)


class TestScenarioVerdictLLM:
    def test_system_prompt_forbids_directional_accuracy_wording(self):
        lower = SCENARIO_VERDICT_SYSTEM_RU.lower()
        assert "точность классификации режима" in lower
        assert "запрещено" in lower and "directional accuracy" in lower
        assert "точность направления" in lower

    def test_structured_context_uses_regime_match_labels(self):
        hierarchy = _minimal_hierarchy("AAPL", confidence=0.45, as_of="2026-08-06T00:00:00Z")
        disclosure = {"top_scenario": "realistic", "top_probability": 0.325}
        context = _build_structured_context(
            "AAPL",
            hierarchy,
            disclosure,
            drift_flag=True,
            aggregate_calibration_error=0.18,
            rolling_regime_accuracy=[
                {"window_days": 30, "regime_match_accuracy": 0.23, "mae": 0.47},
                {"window_days": 90, "regime_match_accuracy": 0.35, "mae": 0.54},
            ],
        )
        assert "точность классификации режима" in context
        assert "23.0%" in context or "23%" in context
        assert "directional accuracy" not in context.lower()
        assert "live vs backtest" not in context.lower()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_second_llm_call(self):
        from app.services.forecast.scenario_verdict_llm import try_generate_scenario_verdict

        hierarchy = _minimal_hierarchy("AAPL", confidence=0.45, as_of="2026-08-06T00:00:00Z")
        disclosure = {
            "scenarios": [{"archetype": "realistic", "probability": 0.325, "label_ru": "Реалистичный"}],
            "top_scenario": "realistic",
            "top_probability": 0.325,
            "breakdown": {"symbol_score": 0.4},
            "expected_move": 0.012,
            "confidence": 0.45,
        }
        layers = [
            "Вердикт - AAPL: реалистичный сценарий около 32%.",
            "Почему - Импульс у Apple слабый, но сектор tech поддерживает.",
            "Что изменит взгляд - пробой волатильности выше 25%.",
            "Действие - держать небольшую позицию и не наращивать риск.",
        ]

        db = AsyncMock()
        with patch("app.services.forecast.scenario_verdict_llm.llm_enabled", return_value=True):
            with patch(
                "app.services.forecast.scenario_verdict_llm.cache_get",
                new=AsyncMock(side_effect=[None, {"paragraphs": layers}]),
            ):
                with patch("app.services.forecast.scenario_verdict_llm.cache_set", new=AsyncMock()):
                    with patch(
                        "app.services.forecast.scenario_verdict_llm._prefetch_verdict_tools",
                        new=AsyncMock(return_value={}),
                    ):
                        with patch(
                            "app.services.forecast.scenario_verdict_llm._run_verdict_llm",
                            new=AsyncMock(return_value="\n".join(layers)),
                        ) as mock_llm:
                            first = await try_generate_scenario_verdict(
                                db,
                                symbol="AAPL",
                                hierarchy=hierarchy,
                                disclosure=disclosure,
                            )
                            second = await try_generate_scenario_verdict(
                                db,
                                symbol="AAPL",
                                hierarchy=hierarchy,
                                disclosure=disclosure,
                            )
        assert first == layers
        assert second == layers
        mock_llm.assert_awaited_once()
