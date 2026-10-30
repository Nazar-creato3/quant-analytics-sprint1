"""Unit tests for MarketPredictionNarrator — summary must change with inputs."""
from __future__ import annotations

from app.services.forecast.market_prediction_narrator import (
    MarketCoverage,
    MarketPredictionNarrator,
)
from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine, MacroIndicatorSnapshot
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import SectorRotationFlag, SectorRotationScore


def _global_result(*, vix: float = 22.0):
    engine = GlobalMacroRegimeEngine()
    return engine.classify(
        MacroIndicatorSnapshot(vix=vix, cpi=2.8, cross_asset_correlation=0.35),
    )


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
        SectorRotationScore(
            sector="technology",
            score_1w=-0.008,
            score_1m=-0.015,
            score_3m=-0.010,
            composite_score=-0.012,
            rotation_flag=SectorRotationFlag.SECTORS_WEAKENING,
            rank=2,
        ),
    )


class TestMarketPredictionNarrator:
    def test_summary_contains_computed_regime_values(self):
        narrator = MarketPredictionNarrator()
        result = global_result = _global_result(vix=18.0)

        summary = narrator.synthesize(
            global_result=global_result,
            macro={"vix": 18.0, "cpi": 2.8},
            rotation_scores=_rotation_scores(),
            coverage=MarketCoverage(
                markets=("MOEX", "US_equities"),
                moex_symbols=("SBER", "GAZP"),
                us_symbols=("SPY",),
            ),
            cross_asset_correlation=0.35,
        )

        assert summary.paragraphs
        full_text = " ".join(summary.paragraphs)
        assert "Наиболее вероятный сценарий" in full_text
        assert global_result.dominant_regime in full_text or "risk" in full_text.lower() or "шок" in full_text.lower() or "защит" in full_text.lower() or "неопред" in full_text.lower()
        assert "18.0" in full_text or "18" in full_text
        assert "MOEX" in full_text or "российск" in full_text.lower()
        assert "GlobalMacroRegimeEngine" in " ".join(summary.engines_used)
        assert any("global_regime" in e for e in summary.evidence)

    def test_summary_text_changes_when_vix_changes(self):
        narrator = MarketPredictionNarrator()
        low_vix = narrator.synthesize(
            global_result=_global_result(vix=15.0),
            macro={"vix": 15.0, "cpi": 2.5},
            rotation_scores=_rotation_scores(),
            coverage=MarketCoverage(markets=("US_equities",), us_symbols=("SPY",)),
            cross_asset_correlation=0.2,
        )
        high_vix = narrator.synthesize(
            global_result=_global_result(vix=32.0),
            macro={"vix": 32.0, "cpi": 2.5},
            rotation_scores=_rotation_scores(),
            coverage=MarketCoverage(markets=("US_equities",), us_symbols=("SPY",)),
            cross_asset_correlation=0.2,
        )

        assert low_vix.paragraphs
        assert high_vix.paragraphs
        assert " ".join(low_vix.paragraphs) != " ".join(high_vix.paragraphs)
        assert any("15" in p or "16" in p or "низк" in p.lower() for p in low_vix.paragraphs)
        assert any("32" in p or "30" in p or "стресс" in p.lower() for p in high_vix.paragraphs)

    def test_summary_text_changes_when_sector_leader_changes(self):
        narrator = MarketPredictionNarrator()
        energy_leader = _rotation_scores()
        tech_leader = (
            SectorRotationScore(
                sector="technology",
                score_1w=0.020,
                score_1m=0.030,
                score_3m=0.015,
                composite_score=0.025,
                rotation_flag=SectorRotationFlag.SECTORS_STRENGTHENING,
                rank=1,
            ),
        )

        energy_summary = narrator.synthesize(
            global_result=_global_result(),
            macro={"vix": 20.0},
            rotation_scores=energy_leader,
            coverage=MarketCoverage(markets=("MOEX",), moex_symbols=("SBER",)),
        )
        tech_summary = narrator.synthesize(
            global_result=_global_result(),
            macro={"vix": 20.0},
            rotation_scores=tech_leader,
            coverage=MarketCoverage(markets=("MOEX",), moex_symbols=("SBER",)),
        )

        assert "энергетика" in " ".join(energy_summary.paragraphs).lower()
        assert "технологии" in " ".join(tech_summary.paragraphs).lower()
        assert " ".join(energy_summary.paragraphs) != " ".join(tech_summary.paragraphs)

    def test_insufficient_data_returns_empty_paragraphs_and_missing_resources(self):
        narrator = MarketPredictionNarrator()
        summary = narrator.synthesize(
            global_result=None,
            macro={},
            rotation_scores=(),
            coverage=MarketCoverage(markets=()),
        )

        assert summary.paragraphs == ()
        assert summary.missing_resources
        assert "macro_indicators.vix" in summary.missing_resources
        assert summary.confidence_pct == 0.0

    def test_missing_resources_lists_gaps_for_richer_report(self):
        narrator = MarketPredictionNarrator()
        summary = narrator.synthesize(
            global_result=_global_result(),
            macro={"vix": 20.0},
            rotation_scores=_rotation_scores(),
            coverage=MarketCoverage(markets=("MOEX",), moex_symbols=("SBER",)),
        )

        assert summary.paragraphs
        missing = summary.missing_resources
        assert any("us_equities" in m.lower() for m in missing)
        assert any("credit_spread" in m for m in missing)

    def test_no_credit_spread_gap_when_fred_data_present(self):
        narrator = MarketPredictionNarrator()
        summary = narrator.synthesize(
            global_result=GlobalMacroRegimeEngine().classify(
                MacroIndicatorSnapshot(
                    vix=20.0,
                    hy_oas_pct=5.5,
                    gov_10y_pct=4.2,
                    credit_spread_proxy=0.013,
                )
            ),
            macro={"vix": 20.0, "credit_spread": 0.013, "hy_oas": 5.5, "gov_10y": 4.2},
            rotation_scores=_rotation_scores(),
            coverage=MarketCoverage(markets=("US_equities",), us_symbols=("SPY",)),
        )

        assert not any("credit_spread" in m for m in summary.missing_resources)

    def test_sector_regime_engine_rank_sectors_integration(self):
        """SectorRegimeEngine output feeds distinct narrative from raw scores."""
        engine = SectorRegimeEngine()
        sector_returns = {
            "energy": [0.01, 0.005, -0.002, 0.008, 0.012] * 5,
            "technology": [-0.005, -0.003, 0.001, -0.004, -0.006] * 5,
        }
        market_returns = [0.002, 0.001, 0.0, 0.001, 0.002] * 5
        scores = engine.rank_sectors(sector_returns, market_returns)

        narrator = MarketPredictionNarrator()
        summary = narrator.synthesize(
            global_result=_global_result(),
            macro={"vix": 19.0, "cpi": 3.0},
            rotation_scores=scores,
            coverage=MarketCoverage(markets=("US_equities",), us_symbols=("SPY",)),
        )

        assert summary.paragraphs
        assert "SectorRegimeEngine" in " ".join(summary.engines_used)
        assert scores[0].sector in " ".join(summary.evidence)
