"""Unit tests for ScenarioDisclosureNarrator — gap threshold and narrative prose."""
from __future__ import annotations

from app.services.forecast.scenario_disclosure_narrator import ScenarioDisclosureNarrator
from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine, MacroIndicatorSnapshot
from app.services.prediction_hierarchy.scenario_summary import CLOSE_SCENARIO_THRESHOLD
from app.services.prediction_hierarchy.types import SectorRotationFlag, SectorRotationScore

_ENGINE_NAMES = (
    "GlobalMacroRegimeEngine",
    "ScenarioEngine",
    "SectorRegimeEngine",
    "ForecastOutputBuilder",
)

_RAW_ENUMS = (
    "choppy_range",
    "reduce_size",
    "risk-on",
    "risk_on",
    "beta-экспозиция",
    "§",
)


def _global_result(*, vix: float = 22.0):
    engine = GlobalMacroRegimeEngine()
    return engine.classify(MacroIndicatorSnapshot(vix=vix, cpi=2.8, cross_asset_correlation=0.35))


def _rotation_scores() -> tuple[SectorRotationScore, ...]:
    return (
        SectorRotationScore(
            sector="energy",
            score_1w=0.012,
            score_1m=0.025,
            score_3m=0.018,
            composite_score=0.022,
            rotation_flag=SectorRotationFlag.SECTORS_STRENGTHENING,
            rank=1,
        ),
    )


class TestScenarioDisclosureNarrator:
    def test_top_scenario_only_when_gap_wide(self):
        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_market_engines(
            macro={"vix": 20.0, "cpi": 2.5},
            global_result=_global_result(),
            rotation_scores=_rotation_scores(),
            aggregated_archetypes={
                "realistic": 0.42,
                "pessimistic": 0.28,
                "optimistic": 0.18,
                "classic": 0.12,
            },
        )

        full_text = " ".join(result.paragraphs)
        assert result.top_scenario == "realistic"
        assert result.second_scenario is None
        assert len(result.paragraphs) >= 3
        assert "Вердикт -" in full_text
        assert "Почему -" in full_text
        assert "Действие -" in full_text
        assert "реалистичный" in full_text.lower()
        assert "Второй по вероятности" not in full_text
        assert "Альтернатива" not in full_text
        assert result.top_probability - 0.28 >= CLOSE_SCENARIO_THRESHOLD
        for token in _ENGINE_NAMES + _RAW_ENUMS:
            assert token not in full_text

    def test_both_scenarios_when_gap_under_five_percent(self):
        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_market_engines(
            macro={"vix": 18.0},
            global_result=_global_result(vix=18.0),
            rotation_scores=_rotation_scores(),
            aggregated_archetypes={
                "optimistic": 0.31,
                "realistic": 0.29,
                "pessimistic": 0.22,
                "classic": 0.18,
            },
        )

        full_text = " ".join(result.paragraphs)
        assert result.top_scenario == "optimistic"
        assert result.second_scenario == "realistic"
        assert result.top_probability - result.second_probability < CLOSE_SCENARIO_THRESHOLD
        assert len(result.paragraphs) >= 4
        assert "Что изменит взгляд -" in full_text
        assert "оптимистичный" in full_text.lower()
        assert "реалистичный" in full_text.lower()
        for token in _ENGINE_NAMES + _RAW_ENUMS:
            assert token not in full_text

    def test_disclosure_uses_narrative_macro_evidence(self):
        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_market_engines(
            macro={"vix": 19.5, "cpi": 3.1},
            global_result=_global_result(),
            rotation_scores=_rotation_scores(),
            aggregated_archetypes={
                "realistic": 0.35,
                "optimistic": 0.33,
                "pessimistic": 0.20,
                "classic": 0.12,
            },
        )

        full_text = " ".join(result.paragraphs)
        assert result.paragraphs
        assert "VIX" in full_text
        assert "инфляц" in full_text.lower()
        assert "данные макро обновлены" not in full_text.lower()
        assert ";" not in full_text
        for token in _ENGINE_NAMES:
            assert token not in full_text
        assert any("layer.global_macro" in e for e in result.evidence)
        assert any("layer.global_macro.vix" in e for e in result.evidence)

    def test_symbol_scope_from_hierarchy_dict(self):
        narrator = ScenarioDisclosureNarrator()
        hierarchy = {
            "symbol": "AAPL",
            "point_forecast": {"momentum_score": 0.62},
            "risk_forecast": {
                "instrument_metrics": {
                    "volatility_expansion_probability": 0.25,
                    "tail_risk_score": 0.15,
                    "composite_risk_score": 0.4,
                }
            },
            "scenario_forecast": {
                "scenarios": [
                    {
                        "scenario_type": "optimistic",
                        "name": "optimistic",
                        "label_ru": "Оптимистичный",
                        "probability": 0.38,
                        "impact": 0.03,
                    },
                    {
                        "scenario_type": "realistic",
                        "name": "realistic",
                        "label_ru": "Реалистичный",
                        "probability": 0.36,
                        "impact": 0.01,
                    },
                    {
                        "scenario_type": "pessimistic",
                        "name": "pessimistic",
                        "label_ru": "Пессимистичный",
                        "probability": 0.16,
                        "impact": -0.04,
                    },
                    {
                        "scenario_type": "classic",
                        "name": "classic",
                        "label_ru": "Классический (исторический)",
                        "probability": 0.10,
                        "impact": 0.0,
                    },
                ]
            },
        }
        result = narrator.from_hierarchy_dict(
            hierarchy,
            macro={"vix": 17.0},
            global_result=_global_result(),
            symbol="AAPL",
        )

        full_text = " ".join(result.paragraphs)
        assert result.scope == "symbol"
        assert result.top_scenario == "optimistic"
        assert result.second_scenario == "realistic"
        assert any("AAPL" in p for p in result.paragraphs)
        assert "расчётный ход +3.0%" in full_text
        assert "AAPL" in full_text
        for token in _ENGINE_NAMES + _RAW_ENUMS:
            assert token not in full_text

    def test_spy_like_classic_scenario_prose(self):
        """Regression: SPY-like case must read as prose, not parameter list."""
        narrator = ScenarioDisclosureNarrator()
        hierarchy = {
            "symbol": "SPY",
            "point_forecast": {"momentum_score": 0.09},
            "risk_forecast": {
                "instrument_metrics": {
                    "volatility_expansion_probability": 0.0,
                }
            },
            "scenario_forecast": {
                "scenarios": [
                    {
                        "scenario_type": "classic",
                        "label_ru": "Классический (исторический)",
                        "probability": 0.408,
                        "impact": -0.008,
                    },
                    {
                        "scenario_type": "realistic",
                        "label_ru": "Реалистичный",
                        "probability": 0.30,
                        "impact": 0.005,
                    },
                ]
            },
        }
        global_result = GlobalMacroRegimeEngine().classify(
            MacroIndicatorSnapshot(vix=16.7, cpi=3.5, cross_asset_correlation=0.3)
        )
        result = narrator.from_hierarchy_dict(
            hierarchy,
            macro={"vix": 16.7, "cpi": 3.5},
            global_result=global_result,
            symbol="SPY",
        )

        full_text = " ".join(result.paragraphs)
        assert result.top_scenario == "classic"
        assert abs(result.top_probability - 0.408) < 0.001
        assert "классический" in full_text.lower()
        assert "GlobalMacroRegimeEngine" not in full_text
        assert "ScenarioEngine" not in full_text
        assert ";" not in full_text
        assert "§" not in full_text
        assert "choppy_range" not in full_text
        assert "Почему -" in full_text

    def test_btc_like_cautious_scenario_tone(self):
        """BTC-USD style: flowing lead with action recommendation in plain Russian."""
        narrator = ScenarioDisclosureNarrator()
        hierarchy = {
            "symbol": "BTC-USD",
            "as_of": "2026-07-20T11:50:51+00:00",
            "calibrated_confidence": 0.62,
            "action_forecast": {"recommendation": "reduce_size"},
            "point_forecast": {"momentum_score": 0.42},
            "risk_forecast": {
                "instrument_metrics": {
                    "volatility_expansion_probability": 0.55,
                    "tail_risk_score": 0.86,
                    "composite_risk_score": 0.58,
                }
            },
            "sector_regime": {
                "sector": "digital_assets",
                "sector_momentum": 0.01,
                "regime": {"dominant_regime": "choppy_range", "distribution": {}},
                "rotation": {
                    "composite_score": 0.01,
                    "score_1w": 0.005,
                    "score_1m": 0.01,
                    "score_3m": 0.008,
                    "rotation_flag": SectorRotationFlag.NEUTRAL.value,
                },
            },
            "scenario_forecast": {
                "scenarios": [
                    {
                        "scenario_type": "pessimistic",
                        "label_ru": "Пессимистичный",
                        "probability": 0.31,
                        "impact": -0.03,
                    },
                    {
                        "scenario_type": "realistic",
                        "label_ru": "Реалистичный",
                        "probability": 0.29,
                        "impact": -0.01,
                    },
                ]
            },
        }
        macro_bundle = {
            "indicators": {"vix": 17.0, "cpi": 2.8},
            "loaded_at": "2026-07-20T11:50:51+00:00",
        }
        result = narrator.from_hierarchy_dict(
            hierarchy,
            macro_bundle=macro_bundle,
            global_result=_global_result(vix=17.0),
            symbol="BTC-USD",
        )

        full_text = " ".join(result.paragraphs)
        assert "BTC-USD" in full_text
        assert "пессимистичный" in full_text.lower()
        assert "уменьшить размер позиции" in full_text
        assert "Действие - разумно снизить" in full_text or "Действие -" in full_text
        assert "данные макро обновлены" not in full_text.lower()
        assert result.freshness["global_macro"]["loaded_at"].startswith("2026-07-20")
        for token in _RAW_ENUMS:
            assert token not in full_text


# Documented template regression samples (Prompt 93 — before vs after prose fallback)
_LEGACY_AAPL_WHY_SNIPPET = (
    "Почему - - импульс инструмента 62%, ожидаемый ход +1.0% · "
    "- vol regime умеренная, expansion 25%"
)
_LEGACY_GAZP_WHY_SNIPPET = (
    "Почему - - импульс инструмента 35%, ожидаемый ход -1.2% · "
    "- vol regime повышенная, expansion 40%"
)


class TestCompactProseBeforeAfter:
    """Fixture-backed samples: old param-dump vs new analyst sentences (LLM-off path)."""

    def _symbol_hierarchy(self, symbol: str, momentum: float, vol_expansion: float):
        return {
            "symbol": symbol,
            "point_forecast": {"momentum_score": momentum},
            "risk_forecast": {
                "instrument_metrics": {
                    "volatility_expansion_probability": vol_expansion,
                    "tail_risk_score": 0.2,
                    "composite_risk_score": 0.45,
                }
            },
            "action_forecast": {"recommendation": "wait"},
            "scenario_forecast": {
                "scenarios": [
                    {
                        "scenario_type": "realistic",
                        "label_ru": "Реалистичный",
                        "probability": 0.44,
                        "impact": 0.008,
                    },
                    {
                        "scenario_type": "pessimistic",
                        "label_ru": "Пессимистичный",
                        "probability": 0.30,
                        "impact": -0.02,
                    },
                ]
            },
            "sector_regime": {
                "sector": "technology" if symbol == "AAPL" else "energy",
                "sector_momentum": 0.02,
                "regime": {"dominant_regime": "bullish_trend", "distribution": {}},
                "rotation": {
                    "composite_score": 0.02,
                    "score_1w": 0.01,
                    "score_1m": 0.02,
                    "score_3m": 0.015,
                    "rotation_flag": SectorRotationFlag.NEUTRAL.value,
                },
            },
        }

    def test_aapl_prose_not_param_dump(self):
        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_hierarchy_dict(
            self._symbol_hierarchy("AAPL", 0.62, 0.25),
            macro={"vix": 17.0, "cpi": 2.9},
            global_result=_global_result(vix=17.0),
            symbol="AAPL",
        )
        why = next(p for p in result.paragraphs if p.startswith("Почему -"))
        assert _LEGACY_AAPL_WHY_SNIPPET not in why
        assert "vol regime" not in why.lower()
        assert "expansion 25%" not in why
        assert "импульс" in why.lower()
        assert "AAPL" not in why  # why layer is instrument-focused, symbol in verdict

    def test_gazp_prose_not_param_dump(self):
        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_hierarchy_dict(
            self._symbol_hierarchy("GAZP", 0.35, 0.40),
            macro={"vix": 22.0, "cpi": 5.1},
            global_result=_global_result(vix=22.0),
            symbol="GAZP",
        )
        why = next(p for p in result.paragraphs if p.startswith("Почему -"))
        assert _LEGACY_GAZP_WHY_SNIPPET not in why
        assert "vol regime" not in why.lower()
        assert " · " not in why
        assert "расширения" in why.lower() or "волатильности" in why.lower()
