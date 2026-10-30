"""Tests for politics JSON news import and analysis wiring."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.analysis.context import NewsHeadline, gather_analysis_context
from app.services.chat.deep_advisor import politics_intent_requested, parse_question_intent, QuestionIntent
from app.services.news.politics_json_import import (
    POLITICS_JSON_SOURCE,
    discover_politics_dirs,
    import_politics_json_news,
    politics_dirs_present,
    synthetic_politics_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "news"
REFERENCE = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def test_discover_politics_dirs_finds_sentiment_folders():
    dirs = discover_politics_dirs(FIXTURES)
    names = [path.name for path, _, _ in dirs]
    assert "Politics_positive_sample" in names
    assert "Politics_negative_sample" in names


def test_politics_dirs_present():
    assert politics_dirs_present(FIXTURES) is True


def test_synthetic_politics_url_prefix():
    url = synthetic_politics_url("headline", "2026-07-20")
    assert url.startswith("csv://politics/")


@pytest.mark.asyncio
async def test_import_politics_json_news_dry_run_counts_rows():
    db = AsyncMock()
    stats = await import_politics_json_news(
        db,
        FIXTURES,
        reference=REFERENCE,
        dry_run=True,
    )
    assert stats.files_seen == 2
    assert stats.rows_parsed == 2
    assert stats.inserted == 2
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_politics_json_news_skips_existing_urls():
    db = AsyncMock()
    existing = MagicMock()
    existing.scalar_one_or_none.return_value = "existing-id"
    db.execute = AsyncMock(return_value=existing)

    stats = await import_politics_json_news(
        db,
        FIXTURES,
        reference=REFERENCE,
        dry_run=False,
    )
    assert stats.rows_parsed == 2
    assert stats.skipped_duplicate == 2
    assert stats.inserted == 0


def test_politics_intent_requested_for_macro_and_politics_questions():
    assert politics_intent_requested(parse_question_intent("Как макро-фон влияет на MSFT?"))
    assert politics_intent_requested(parse_question_intent("Какие геополитические риски у AAPL?"))
    assert not politics_intent_requested(parse_question_intent("Стоит ли купить MSFT?"))


@pytest.mark.asyncio
async def test_gather_analysis_context_can_include_politics(monkeypatch):
    async def fake_politics(*args, **kwargs):
        return [
            NewsHeadline(
                title="NATO allies debate sanctions escalation amid conflict",
                relevance_score=0.35,
                sentiment_score=-1.0,
                sentiment_label="negative",
            )
        ]

    monkeypatch.setattr(
        "app.services.analysis.context._load_politics_headlines",
        fake_politics,
    )
    monkeypatch.setattr("app.services.analysis.context._load_news_headlines", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.analysis.context._load_macro_bundle",
        AsyncMock(return_value=({}, "")),
    )
    monkeypatch.setattr("app.services.analysis.context._load_factor_exposures", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.analysis.context._load_event_risk", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.analysis.context._load_ticker_analysis", AsyncMock(return_value=None))

    db = AsyncMock()
    ctx = await gather_analysis_context(
        db,
        instrument_id=1,
        symbol="AAPL",
        include_structured=False,
        include_politics=True,
    )
    assert len(ctx.news_headlines) == 1
    assert "NATO" in ctx.news_headlines[0].title
    assert POLITICS_JSON_SOURCE  # constant referenced for wiring docs
