"""Tests for configurable maneuver scoring weights and event blending."""
from __future__ import annotations

import pytest

from app.services.ml.model import ModelPrediction
from app.services.risk.engine import TradeRiskResult
from app.services.risk.maneuver_generator import (
    ManeuverCandidate,
    score_weights,
)


def _prediction(confidence=0.7, strength=0.5, direction="long") -> ModelPrediction:
    return ModelPrediction(
        ticker="AAPL",
        direction=direction,
        confidence=confidence,
        raw_score=0.6,
        signal_strength=strength,
        features_used={},
        model_version="test",
    )


def _risk(tradeable=True, rr=3.0) -> TradeRiskResult:
    return TradeRiskResult(
        ticker="AAPL",
        direction="long",
        is_tradeable=tradeable,
        reason="ok" if tradeable else "no",
        entry_price=100.0,
        risk_reward_ratio=rr,
    )


class TestScoreWeights:
    def test_defaults_normalized(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "SCORE_WEIGHT_TECHNICAL", 0.40)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_NEWS", 0.35)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_REGIME", 0.25)
        w = score_weights()
        assert pytest.approx(sum(w), rel=1e-9) == 1.0
        assert w == (0.40, 0.35, 0.25)

    def test_normalizes_arbitrary_weights(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "SCORE_WEIGHT_TECHNICAL", 2.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_NEWS", 1.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_REGIME", 1.0)
        w_tech, w_news, w_regime = score_weights()
        assert pytest.approx(w_tech) == 0.5
        assert pytest.approx(w_news) == 0.25
        assert pytest.approx(w_regime) == 0.25

    def test_zero_sum_falls_back_to_defaults(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "SCORE_WEIGHT_TECHNICAL", 0.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_NEWS", 0.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_REGIME", 0.0)
        assert score_weights() == (0.40, 0.35, 0.25)


class TestComponents:
    def test_non_tradeable_still_has_rank_score(self):
        c = ManeuverCandidate(ticker="AAPL", prediction=_prediction(), risk=_risk(tradeable=False))
        assert c.composite_score >= 0.0

    def test_components_in_unit_range(self):
        c = ManeuverCandidate(
            ticker="AAPL",
            prediction=_prediction(),
            risk=_risk(),
            news_sentiment=0.5,
            event_score=0.4,
            macro_score=0.3,
            regime="bull",
        )
        assert 0.0 <= c.technical_component <= 1.0
        assert 0.0 <= c.news_events_component <= 1.0
        assert 0.0 <= c.regime_component <= 1.0
        assert 0.0 <= c.composite_score <= 1.0

    def test_positive_news_and_events_raise_component(self):
        neg = ManeuverCandidate(
            ticker="AAPL", prediction=_prediction(), risk=_risk(),
            news_sentiment=-0.8, event_score=-0.5,
        )
        pos = ManeuverCandidate(
            ticker="AAPL", prediction=_prediction(), risk=_risk(),
            news_sentiment=0.8, event_score=0.5,
        )
        assert pos.news_events_component > neg.news_events_component

    def test_weight_change_shifts_composite(self, monkeypatch):
        from app.core.config import settings

        c = ManeuverCandidate(
            ticker="AAPL", prediction=_prediction(confidence=0.9), risk=_risk(rr=3.0),
            news_sentiment=-0.9, event_score=-0.9, macro_score=-0.9, regime="bear",
        )
        # Technical is strong, news/regime weak: heavier technical weight -> higher score.
        monkeypatch.setattr(settings, "SCORE_WEIGHT_TECHNICAL", 1.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_NEWS", 0.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_REGIME", 0.0)
        tech_heavy = c.composite_score
        monkeypatch.setattr(settings, "SCORE_WEIGHT_TECHNICAL", 0.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_NEWS", 1.0)
        monkeypatch.setattr(settings, "SCORE_WEIGHT_REGIME", 0.0)
        news_heavy = c.composite_score
        assert tech_heavy > news_heavy


class TestEventsByTicker:
    def test_aggregates_weighted_by_confidence(self):
        from app.tasks.pipeline import _events_by_ticker

        events = [
            {"tickers_affected": ["AAPL"], "market_effect": 0.8, "confidence": 1.0},
            {"tickers_affected": ["AAPL"], "market_effect": -0.4, "confidence": 1.0},
            {"tickers_affected": ["TSLA"], "market_effect": 0.5, "confidence": 0.5},
        ]
        result = _events_by_ticker(events, ["AAPL", "TSLA", "MSFT"])
        assert pytest.approx(result["AAPL"], rel=1e-6) == 0.2
        assert pytest.approx(result["TSLA"], rel=1e-6) == 0.5
        assert "MSFT" not in result  # no events -> absent (treated as 0.0)

    def test_ignores_unlisted_tickers(self):
        from app.tasks.pipeline import _events_by_ticker

        events = [{"tickers_affected": ["NFLX"], "market_effect": 0.9, "confidence": 1.0}]
        assert _events_by_ticker(events, ["AAPL"]) == {}
