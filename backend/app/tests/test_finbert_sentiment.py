"""Tests for FinBERT sentiment pipeline."""
from __future__ import annotations

from unittest.mock import patch

from app.services.news.finbert_sentiment import SentimentResult, score_finbert_batch, score_text_sentiment


def test_score_text_sentiment_vader_fallback():
    with patch("app.services.news.finbert_sentiment.score_finbert", return_value=None):
        r = score_text_sentiment("Stock surges on strong earnings beat")
    assert r.label in {"positive", "negative", "neutral"}
    assert -1.0 <= r.score <= 1.0
    assert r.engine == "vader"


def test_finbert_batch_returns_aligned_results():
    texts = ["good earnings beat", "short"]
    with patch("app.services.news.finbert_sentiment.finbert_available", return_value=False):
        results = score_finbert_batch(texts)
    assert len(results) == 2
    assert results == [None, None]


def test_score_text_sentiment_finbert_path():
    fake = SentimentResult(score=0.8, label="positive", confidence=0.91, engine="finbert")
    with patch("app.services.news.finbert_sentiment.score_finbert", return_value=fake):
        r = score_text_sentiment("Apple reports record revenue")
    assert r.engine == "finbert"
    assert r.confidence == 0.91
