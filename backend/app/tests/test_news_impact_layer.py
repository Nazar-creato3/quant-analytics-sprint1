"""Tests for News Impact Layer (Prompt 24)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.event_risk.news_impact import (
    NewsImpactAnalog,
    bayesian_strong_move_probability,
    compute_analog_probability,
    compute_news_impact_probability,
    extract_topic_tags,
    is_strong_move,
    update_posterior_from_feedback,
)
from app.services.event_risk.scoring import compute_news_shock_score


def _article(*, sentiment: float = -0.5, tags: list[str] | None = None, title: str = "Fed raises rates") -> SimpleNamespace:
    return SimpleNamespace(
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        sentiment_score=sentiment,
        tickers_mentioned=["AAPL"],
        title=title,
        summary="",
        tags=tags or ["fed", "rates"],
    )


class TestNewsImpactClassifier:
    def test_extract_topic_tags_from_keywords(self):
        article = SimpleNamespace(
            title="Oil prices surge after OPEC cut",
            summary="Brent crude jumps",
            tags=[],
        )
        tags = extract_topic_tags(article)
        assert "oil" in tags
        assert "brent" in tags

    def test_analog_probability_rises_after_strong_moves(self):
        tags = ("fed", "rates")
        baseline_history: list[NewsImpactAnalog] = []
        baseline_prob, _, _ = compute_analog_probability(tags, baseline_history)

        calibrated_history = [
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
        ]
        calibrated_prob, count, strong_count = compute_analog_probability(tags, calibrated_history)

        assert count == 3
        assert strong_count == 3
        assert calibrated_prob > baseline_prob

    def test_similar_news_gets_higher_probability_after_history(self):
        tags = ("fed", "rates")
        history_before: list[NewsImpactAnalog] = []
        before = compute_news_impact_probability(
            topic_tags=tags,
            factor_exposures={"rates_sensitivity": 0.2},
            history=history_before,
            daily_volatility=0.02,
        )

        history_after = [
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
        ]
        after = compute_news_impact_probability(
            topic_tags=tags,
            factor_exposures={"rates_sensitivity": 0.2},
            history=history_after,
            daily_volatility=0.02,
        )

        assert after.probability > before.probability
        assert after.analog_probability > before.analog_probability

    def test_factor_alignment_boosts_rate_sensitive_instrument(self):
        tags = ("fed", "rates")
        low_alignment = compute_news_impact_probability(
            topic_tags=tags,
            factor_exposures={"market_beta": 0.3},
            history=[],
            daily_volatility=0.015,
        )
        high_alignment = compute_news_impact_probability(
            topic_tags=tags,
            factor_exposures={"rates_sensitivity": 0.95, "macro_shock_sensitivity": 0.7},
            history=[],
            daily_volatility=0.015,
        )
        assert high_alignment.probability > low_alignment.probability
        assert "rates_sensitivity" in high_alignment.matched_factors

    def test_bayesian_update_increases_posterior_after_strong_move(self):
        weak_posterior = update_posterior_from_feedback(
            predicted_probability=0.4,
            strong_move=False,
        )
        strong_posterior = update_posterior_from_feedback(
            predicted_probability=0.4,
            strong_move=True,
        )
        assert strong_posterior > weak_posterior

    def test_strong_move_detection_uses_sigma_threshold(self):
        assert is_strong_move(2.1, sigma_threshold=2.0) is True
        assert is_strong_move(1.5, sigma_threshold=2.0) is False

    def test_bayesian_prior_is_stable_with_no_data(self):
        assert bayesian_strong_move_probability(strong_count=0, total_count=0) == pytest.approx(
            2 / 7,
            rel=1e-6,
        )


class TestNewsImpactScoringIntegration:
    def test_scoring_returns_probability_payload(self):
        score, impact, calendar_boost, macro_boost, count, reason, probability = compute_news_shock_score(
            [_article(sentiment=-0.9, tags=["fed", "rates"])],
            as_of=datetime.now(timezone.utc),
            factor_exposures={"rates_sensitivity": 0.9},
            daily_volatility=0.02,
        )
        assert score > 0.0
        assert impact < 0
        assert count == 1
        assert 0.0 <= probability.probability <= 1.0
        assert probability.factor_alignment > 0.0

    def test_repeated_strong_analogs_raise_probability_for_similar_news(self):
        tags = ("fed", "rates")
        history: list[NewsImpactAnalog] = []
        first_score, _, _, _, _, _, first_probability = compute_news_shock_score(
            [_article(tags=list(tags))],
            as_of=datetime.now(timezone.utc),
            factor_exposures={"rates_sensitivity": 0.4},
            impact_history=history,
            daily_volatility=0.02,
        )

        history = [
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
            NewsImpactAnalog(topic_tags=tags, strong_move=True),
        ]
        second_score, _, _, _, _, _, second_probability = compute_news_shock_score(
            [_article(tags=list(tags))],
            as_of=datetime.now(timezone.utc),
            factor_exposures={"rates_sensitivity": 0.4},
            impact_history=history,
            daily_volatility=0.02,
        )

        assert second_probability.probability > first_probability.probability
        assert second_probability.analog_probability > first_probability.analog_probability


class TestNewsImpactFeedbackService:
    @pytest.mark.asyncio
    async def test_feedback_updates_pending_record(self):
        from app.services.event_risk.feedback import NewsImpactFeedbackService
        from app.domain.news_impact import NewsImpactHistoryORM

        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        row = NewsImpactHistoryORM(
            id=1,
            instrument_id=101,
            topic_tags=["fed", "rates"],
            predicted_probability=0.45,
            predicted_at=now - timedelta(hours=5),
            daily_volatility=0.02,
            sigma_threshold=2.0,
            metadata_={},
        )

        repo = MagicMock()
        repo.list_pending_feedback = AsyncMock(return_value=[row])
        repo.apply_feedback = AsyncMock(return_value=row)

        service = NewsImpactFeedbackService(repository=repo, feedback_horizons_hours=(4,))
        db = AsyncMock()

        bar_at_news = SimpleNamespace(close=100.0)
        bar_after = SimpleNamespace(close=104.5)
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=bar_at_news)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=bar_after)),
            ]
        )

        updated = await service.process_pending(db, as_of=now)
        assert updated == 1
        repo.apply_feedback.assert_awaited_once()
        kwargs = repo.apply_feedback.await_args.kwargs
        assert kwargs["strong_move"] is True
        assert kwargs["actual_move_sigma"] > 2.0
