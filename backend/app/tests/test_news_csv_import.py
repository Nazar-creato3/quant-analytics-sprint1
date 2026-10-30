"""Tests for bulk financial news CSV import and sentiment wiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.analysis.context import NewsHeadline, summarize_news_sentiment
from app.services.analysis.enrichment import enrich_structured_forecast
from app.services.analysis.context import AnalysisContext
from app.services.chat.advisor_prompt import format_news_from_payload
from app.services.news.csv_bulk_import import (
    _parse_csv_row,
    discover_csv_files,
    import_csv_news,
    parse_relative_published_at,
    synthetic_url,
    title_hash,
)
from app.schemas.forecast import StructuredForecastSections
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

FIXTURES = Path(__file__).parent / "fixtures" / "news"
REFERENCE = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def test_title_hash_is_stable():
    assert title_hash("Microsoft Hits 4-week High") == title_hash("Microsoft Hits 4-week High")
    assert title_hash("A") != title_hash("B")


def test_synthetic_url_uses_hash_prefix():
    url = synthetic_url("Test headline")
    assert url.startswith("csv://financial-dataset/")


def test_parse_relative_published_at_days_ago():
    published = parse_relative_published_at("foo bar 3 days ago", reference=REFERENCE)
    assert published == REFERENCE - timedelta(days=3)


def test_parse_relative_published_at_stuck_price_suffix():
    published = parse_relative_published_at(
        "UnitedHealth increased to a 4-week high of 483.243 days ago",
        reference=REFERENCE,
    )
    assert published == REFERENCE - timedelta(days=3)


def test_parse_csv_row_extracts_tickers_and_sentiment():
    row = {
        "Title": "Microsoft Hits 4-week High",
        "Tag": "stocks",
        "Content": "Microsoft increased to a 4-week high of 348.56 3 days ago",
        "Category": "Market Indicators",
    }
    parsed = _parse_csv_row(row, reference=REFERENCE)
    assert parsed is not None
    assert "MSFT" in parsed.tickers_mentioned
    assert parsed.sentiment_label in {"positive", "negative", "neutral"}
    assert -1.0 <= parsed.sentiment_score <= 1.0
    assert parsed.description == "stocks · Market Indicators"
    assert parsed.extracted_events[0]["category"] == "Market Indicators"


def test_discover_csv_files_prefers_categorized():
    files = discover_csv_files(FIXTURES)
    assert files
    assert files[0].name == "financial_sample.csv"


@pytest.mark.asyncio
async def test_import_csv_news_dry_run_counts_rows():
    db = AsyncMock()
    stats = await import_csv_news(
        db,
        FIXTURES,
        reference=REFERENCE,
        dry_run=True,
    )
    assert stats.files_seen >= 1
    assert stats.rows_parsed == 3
    assert stats.inserted == 3
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_csv_news_skips_existing_urls():
    db = AsyncMock()
    existing = MagicMock()
    existing.scalar_one_or_none.return_value = "existing-id"
    db.execute = AsyncMock(return_value=existing)

    stats = await import_csv_news(
        db,
        FIXTURES,
        reference=REFERENCE,
        dry_run=False,
    )
    assert stats.rows_parsed == 3
    assert stats.skipped_duplicate == 3
    assert stats.inserted == 0


def test_summarize_news_sentiment_counts_labels():
    headlines = [
        NewsHeadline(title="a", sentiment_label="positive", sentiment_score=0.5),
        NewsHeadline(title="b", sentiment_label="negative", sentiment_score=-0.4),
        NewsHeadline(title="c", sentiment_label="neutral", sentiment_score=0.0),
    ]
    summary = summarize_news_sentiment(headlines)
    assert summary is not None
    assert summary.positive == 1
    assert summary.negative == 1
    assert summary.neutral == 1
    assert summary.avg_score == pytest.approx(0.0333, abs=0.01)


def test_format_news_from_payload_includes_sentiment():
    text = format_news_from_payload(
        ("Microsoft beats estimates",),
        positive=2,
        negative=1,
        neutral=0,
        avg_score=0.25,
    )
    assert "Microsoft beats estimates" in text
    assert "+2/−1" in text
    assert "+0.25" in text


def test_enrich_structured_forecast_includes_sentiment_in_news_section():
    hierarchy = ForecastOutput(
        instrument_id=1,
        symbol="MSFT",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.5,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=10,
            p10=-0.04,
            p90=0.07,
            rolling_volatility=0.02,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.08,
            p25=-0.01,
            p50=0.02,
            p75=0.04,
            p95=0.09,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.0),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={},
            portfolio_metrics={},
            plain_language_summary="",
            risk_items=(),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="test",
        ),
        calibrated_confidence=0.7,
        high_confidence=False,
    )
    analysis = AnalysisContext(
        symbol="MSFT",
        news_headlines=[
            NewsHeadline(
                title="Microsoft Hits 4-week High",
                sentiment_label="positive",
                sentiment_score=0.42,
            )
        ],
        news_sentiment=summarize_news_sentiment(
            [
                NewsHeadline(
                    title="Microsoft Hits 4-week High",
                    sentiment_label="positive",
                    sentiment_score=0.42,
                )
            ]
        ),
    )
    result = enrich_structured_forecast(
        StructuredForecastSections(),
        hierarchy=hierarchy,
        payload=None,
        analysis=analysis,
        narrator_texts=[],
        disclosure=MagicMock(to_dict=lambda: {}),
        symbol="MSFT",
    )
    blob = str(result.market_outlook) + " ".join(result.actionable_summary)
    assert "NewsAggregator" in blob
    assert "Microsoft" in blob or "avg" in blob.lower()
