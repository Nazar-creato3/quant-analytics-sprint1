"""Tests for greedy diversified maneuver selection (spec A.2b)."""
from __future__ import annotations

from app.services.ml.model import ModelPrediction
from app.services.risk.engine import TradeRiskResult
from app.services.risk.maneuver_diversification import (
    cosine_similarity,
    select_diversified_candidates,
)
from app.services.risk.maneuver_generator import ManeuverCandidate


def _candidate(ticker: str, score: float, profile: str = "tech") -> ManeuverCandidate:
    if profile == "energy":
        features = {
            "roc_5": 8.0,
            "roc_20": 6.0,
            "price_vs_sma20": 0.08,
            "volatility_20d": 0.45,
            "atr_pct": 0.04,
            "volume_ratio": 1.5,
        }
    else:
        features = {
            "roc_5": -4.0,
            "roc_20": -2.0,
            "price_vs_sma20": -0.05,
            "volatility_20d": 0.18,
            "atr_pct": 0.015,
            "volume_ratio": 0.9,
        }
    pred = ModelPrediction(
        ticker=ticker,
        direction="long",
        confidence=score,
        raw_score=score,
        signal_strength=0.5,
        features_used=features,
        model_version="test",
    )
    return ManeuverCandidate(
        ticker=ticker,
        prediction=pred,
        risk=TradeRiskResult(
            ticker=ticker,
            direction="long",
            is_tradeable=True,
            reason="ok",
            entry_price=100.0,
        ),
    )


class TestDiversification:
    def test_cosine_identical_vectors(self):
        v = [1.0, 0.5, 0.2]
        assert cosine_similarity(v, v) > 0.99

    def test_select_spreads_sectors(self):
        candidates = [
            _candidate("LKOH", 0.9, "energy"),
            _candidate("GAZP", 0.88, "energy"),
            _candidate("ROSN", 0.87, "energy"),
            _candidate("AAPL", 0.86, "tech"),
            _candidate("MSFT", 0.85, "tech"),
            _candidate("NVDA", 0.84, "tech"),
        ]
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        picked = select_diversified_candidates(candidates, target=4, max_sector_count=2)
        tickers = {c.ticker for c in picked}
        assert len(picked) >= 2
        energy = sum(1 for c in picked if c.ticker in {"LKOH", "GAZP", "ROSN"})
        assert energy <= 2
        assert len(tickers) == len(picked)

    def test_empty_input(self):
        assert select_diversified_candidates([], target=10) == []
