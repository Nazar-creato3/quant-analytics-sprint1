"""Tests for shared analysis context gathering."""
from __future__ import annotations

from app.services.analysis.context import (
    AnalysisContext,
    EventRiskSummary,
    NewsHeadline,
    NewsSentimentSummary,
    compute_macro_data_gaps,
    format_macro_snippet,
    format_factor_snippet,
    summarize_news_sentiment,
)


def test_format_macro_snippet_uses_available_indicators_only():
    snippet = format_macro_snippet(
        {"vix": 18.5, "rate_cb_us": 5.25, "oil_brent": 82.0},
        stale_reason="stale indicators: vix",
        symbol="SPY",
    )
    assert "VIX 18.5" in snippet
    assert "5.25%" in snippet
    assert "Brent 82.0" in snippet
    assert "устарела" in snippet


def test_format_macro_snippet_empty_when_no_data():
    assert format_macro_snippet({}) == ""


def test_compute_macro_data_gaps_lists_missing_core_series():
    gaps = compute_macro_data_gaps({"vix": 20.0})
    assert any("cpi" in g for g in gaps)
    assert any("credit_spread" in g for g in gaps)


def test_format_factor_snippet_dominant_factor():
    line = format_factor_snippet({"momentum": 0.42, "market_beta": 0.1})
    assert "моментум" in line
    assert "+0.42" in line


def test_analysis_context_dataclass_defaults():
    ctx = AnalysisContext(symbol="AAPL")
    assert ctx.news_headlines == []
    assert ctx.data_gaps == []


def test_event_risk_summary_fields():
    er = EventRiskSummary(
        score=0.55,
        news_impact_probability=0.4,
        article_count=3,
        reason="earnings window",
        topic_tags=("earnings",),
    )
    assert er.topic_tags == ("earnings",)


def test_news_headline_dataclass():
    h = NewsHeadline(title="Test headline", relevance_score=0.8)
    assert h.title == "Test headline"


def test_summarize_news_sentiment_empty():
    assert summarize_news_sentiment([]) is None


def test_news_sentiment_summary_defaults():
    ns = NewsSentimentSummary()
    assert ns.positive == 0
    assert ns.avg_score == 0.0
