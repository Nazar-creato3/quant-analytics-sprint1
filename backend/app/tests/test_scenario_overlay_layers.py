"""Tests for four-layer scenario overlay architecture."""
from __future__ import annotations

from app.services.forecast.scenario_disclosure_narrator import ScenarioDisclosureNarrator
from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine, MacroIndicatorSnapshot
from app.services.prediction_hierarchy.scenario_overlay import (
    InstrumentOverlay,
    SectorOverlay,
    build_global_macro_snapshot,
    compute_layered_scenario_probabilities,
)
from app.services.prediction_hierarchy.types import GlobalRegimeResult, SectorRotationFlag, SectorRotationScore


def _global_result(*, vix: float = 16.7, cpi: float = 3.5) -> GlobalRegimeResult:
    engine = GlobalMacroRegimeEngine()
    return engine.classify(
        MacroIndicatorSnapshot(vix=vix, cpi=cpi, cross_asset_correlation=0.35)
    )


def _macro_snapshot(global_result: GlobalRegimeResult) -> "GlobalMacroSnapshot":
    return build_global_macro_snapshot(
        indicators={"vix": 16.7, "cpi": 3.5},
        global_result=global_result,
        loaded_at="2026-07-20T10:00:00+00:00",
    )


def _sector_overlay(
    sector: str,
    *,
    composite: float,
    momentum: float,
) -> SectorOverlay:
    rotation = SectorRotationScore(
        sector=sector,
        score_1w=composite * 0.4,
        score_1m=composite,
        score_3m=composite * 0.8,
        composite_score=composite,
        rotation_flag=SectorRotationFlag.SECTORS_STRENGTHENING,
        rank=1,
    )
    return SectorOverlay(
        sector=sector,
        rotation=rotation,
        sector_momentum=momentum,
        dominant_sector_regime="bullish_trend",
        as_of="2026-07-20T10:00:00+00:00",
    )


def _instrument_overlay(symbol: str, *, momentum: float, vol: float = 0.2) -> InstrumentOverlay:
    return InstrumentOverlay(
        symbol=symbol,
        momentum=momentum,
        vol_expansion=vol,
        tail_risk=0.15,
        composite_risk=0.35,
        realized_vol=0.018,
        liquidity_score=0.1,
        relative_strength=momentum - 0.5,
        regime_distribution={"bullish_trend": 0.6, "choppy_range": 0.4},
        as_of="2026-07-20T10:00:00+00:00",
        expected_move=(momentum - 0.5) * 0.08,
        volatility_regime="moderate",
    )


class TestScenarioOverlayLayers:
    def test_same_global_macro_different_sector_and_instrument_probs(self):
        global_result = _global_result()
        macro = _macro_snapshot(global_result)

        tech_sector = _sector_overlay("technology", composite=0.025, momentum=0.02)
        energy_sector = _sector_overlay("energy", composite=-0.018, momentum=-0.015)

        googl_inst = _instrument_overlay("GOOGL", momentum=0.62)
        gazp_inst = _instrument_overlay("GAZP", momentum=0.38, vol=0.35)
        aapl_inst = _instrument_overlay("AAPL", momentum=0.55)

        googl_probs, googl_breakdown, _ = compute_layered_scenario_probabilities(
            macro=macro,
            sector=tech_sector,
            instrument=googl_inst,
        )
        gazp_probs, gazp_breakdown, _ = compute_layered_scenario_probabilities(
            macro=macro,
            sector=energy_sector,
            instrument=gazp_inst,
        )
        aapl_probs, aapl_breakdown, _ = compute_layered_scenario_probabilities(
            macro=macro,
            sector=tech_sector,
            instrument=aapl_inst,
        )

        assert googl_probs != gazp_probs
        assert googl_breakdown.sector_score != gazp_breakdown.sector_score
        assert googl_breakdown.symbol_score > 0
        assert gazp_probs["pessimistic"] > googl_probs["pessimistic"]
        assert googl_probs["optimistic"] > gazp_probs["optimistic"]
        assert aapl_probs != googl_probs or aapl_breakdown.symbol_score != googl_breakdown.symbol_score

    def test_sector_momentum_not_zero_when_data_exists(self):
        sector = _sector_overlay("energy", composite=0.022, momentum=0.018)
        assert sector.momentum_bp != 0.0
        assert abs(sector.momentum_bp) >= 100.0

    def test_narrator_produces_separated_layer_sections(self):
        global_result = _global_result()
        macro = _macro_snapshot(global_result)
        overlays_bundle = compute_layered_scenario_probabilities(
            macro=macro,
            sector=_sector_overlay("technology", composite=0.02, momentum=0.015),
            instrument=_instrument_overlay("AAPL", momentum=0.58),
        )
        probs, breakdown, audit = overlays_bundle

        from app.services.prediction_hierarchy.scenario_overlay import ForecastOverlayBundle

        bundle = ForecastOverlayBundle(
            global_macro=macro,
            sector=_sector_overlay("technology", composite=0.02, momentum=0.015),
            instrument=_instrument_overlay("AAPL", momentum=0.58),
            portfolio=None,
            scenario_probabilities=probs,
            breakdown=breakdown,
            audit=audit,
        )

        narrator = ScenarioDisclosureNarrator()
        result = narrator.from_overlay_bundle(bundle, scope="symbol")

        full_text = " ".join(result.paragraphs)
        assert "Вердикт -" in full_text
        assert "Почему -" in full_text
        assert "Для AAPL" in full_text or "AAPL" in full_text
        assert "Действие -" in full_text
        assert result.breakdown.get("macro_score", 0) > 0
        assert result.layers.get("global_macro") is not None
        assert result.layers.get("instrument") is not None
        assert result.freshness.get("global_macro") is not None
        assert "GlobalMacroRegimeEngine" not in full_text
        assert "§" not in full_text

    def test_googl_vs_gazp_same_macro_block_different_overlays(self):
        global_result = _global_result()
        narrator = ScenarioDisclosureNarrator()

        def hierarchy_for(symbol: str, sector: str, momentum: float, composite: float):
            return {
                "symbol": symbol,
                "as_of": "2026-07-20T10:00:00+00:00",
                "calibrated_confidence": 0.746,
                "action_forecast": {"recommendation": "hold"},
                "point_forecast": {"momentum_score": momentum},
                "risk_forecast": {
                    "instrument_metrics": {
                        "volatility_expansion_probability": 0.22,
                        "tail_risk_score": 0.12,
                        "composite_risk_score": 0.38,
                    }
                },
                "sector_regime": {
                    "sector": sector,
                    "sector_momentum": composite,
                    "regime": {"dominant_regime": "bullish_trend", "distribution": {}},
                    "rotation": {
                        "composite_score": composite,
                        "score_1w": composite * 0.5,
                        "score_1m": composite,
                        "score_3m": composite * 0.7,
                        "rotation_flag": SectorRotationFlag.SECTORS_STRENGTHENING.value,
                    },
                },
                "scenario_forecast": {
                    "scenarios": [
                        {
                            "scenario_type": "realistic",
                            "label_ru": "Реалистичный",
                            "probability": 0.35,
                            "impact": 0.01,
                        },
                        {
                            "scenario_type": "pessimistic",
                            "label_ru": "Пессимистичный",
                            "probability": 0.30,
                            "impact": -0.03,
                        },
                        {
                            "scenario_type": "optimistic",
                            "label_ru": "Оптимистичный",
                            "probability": 0.22,
                            "impact": 0.04,
                        },
                        {
                            "scenario_type": "classic",
                            "label_ru": "Классический (исторический)",
                            "probability": 0.13,
                            "impact": 0.0,
                        },
                    ]
                },
            }

        macro_bundle = {
            "indicators": {"vix": 16.7, "cpi": 3.5},
            "loaded_at": "2026-07-20T10:00:00+00:00",
            "source_timestamps": {"vix": "2026-07-19T00:00:00+00:00", "cpi": "2026-07-18T00:00:00+00:00"},
        }

        googl = narrator.from_hierarchy_dict(
            hierarchy_for("GOOGL", "communication_services", 0.62, 0.022),
            macro_bundle=macro_bundle,
            global_result=global_result,
            symbol="GOOGL",
        )
        gazp = narrator.from_hierarchy_dict(
            hierarchy_for("GAZP", "energy", 0.38, -0.018),
            macro_bundle=macro_bundle,
            global_result=global_result,
            symbol="GAZP",
        )

        googl_macro = googl.layers["global_macro"]
        gazp_macro = gazp.layers["global_macro"]
        assert googl_macro["indicators"]["vix"] == gazp_macro["indicators"]["vix"]
        assert googl_macro["indicators"]["cpi"] == gazp_macro["indicators"]["cpi"]

        assert googl.layers["sector"]["sector"] != gazp.layers["sector"]["sector"]
        assert googl.layers["sector"]["momentum_bp"] != gazp.layers["sector"]["momentum_bp"]
        assert googl.breakdown != gazp.breakdown
        assert "Почему -" in googl.paragraphs[1]
        assert "GOOGL" in " ".join(googl.paragraphs)
        assert "GAZP" in " ".join(gazp.paragraphs)
        assert "§" not in " ".join(googl.paragraphs)
