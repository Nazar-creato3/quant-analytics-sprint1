"""News/calendar feed freshness — staleness detection and health-check regression."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.health.reporter import check_news_feed_freshness
from app.services.terminal_platform.market.feed_freshness import (
    NEWS_STALE_AFTER_SEC,
    build_freshness_meta,
    freshness_from_news_cache,
    set_cached_news,
    simulate_stale_news_cache,
)


def test_build_freshness_meta_fresh():
    now = datetime.now(timezone.utc)
    items = [{"published_at": now.isoformat(), "headline": "Live headline"}]
    meta = build_freshness_meta(items, refreshed_at=now)
    assert meta.is_stale is False
    assert meta.item_count == 1
    assert meta.age_sec is not None
    assert meta.age_sec < 5


def test_build_freshness_meta_stale_when_refresh_old():
    refreshed = datetime.now(timezone.utc) - timedelta(seconds=NEWS_STALE_AFTER_SEC + 120)
    items = [{"published_at": refreshed.isoformat(), "headline": "Old"}]
    meta = build_freshness_meta(items, refreshed_at=refreshed)
    assert meta.is_stale is True
    assert meta.age_sec >= NEWS_STALE_AFTER_SEC


def test_build_freshness_meta_stale_when_empty():
    now = datetime.now(timezone.utc)
    meta = build_freshness_meta([], refreshed_at=now)
    assert meta.is_stale is True
    assert meta.item_count == 0


def test_simulate_stale_news_cache_marks_stale():
    meta = simulate_stale_news_cache()
    assert meta.is_stale is True
    rows, cached_meta = freshness_from_news_cache()
    assert rows is not None
    assert cached_meta is not None
    assert cached_meta.is_stale is True


def test_set_cached_news_serves_with_freshness():
    now = datetime.now(timezone.utc)
    rows = [{"id": "n1", "headline": "Test", "source": "rss", "published_at": now.isoformat()}]
    set_cached_news(rows, refreshed_at=now)
    served, meta = freshness_from_news_cache()
    assert served is not None
    assert meta is not None
    assert meta.is_stale is False
    assert meta.from_cache is True


@pytest.mark.asyncio
async def test_health_check_news_feed_freshness_catches_stale():
    stale_meta = simulate_stale_news_cache().model_dump()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "success": True,
                "data": [{"title": "Stale headline (test)"}],
                "metadata": {"freshness": stale_meta},
            }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=FakeResponse())
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.health.reporter.httpx.AsyncClient", return_value=mock_cm):
        result = await check_news_feed_freshness()

    assert result["status"] == "failed"
    assert "stale" in (result.get("error") or "").lower()


@pytest.mark.asyncio
async def test_health_check_news_feed_freshness_passes_fresh():
    now = datetime.now(timezone.utc).isoformat()
    fresh_meta = {
        "last_refreshed_at": now,
        "is_stale": False,
        "age_sec": 12.0,
        "item_count": 3,
        "stale_after_sec": NEWS_STALE_AFTER_SEC,
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "success": True,
                "data": [{"title": "Fresh headline"}],
                "metadata": {"freshness": fresh_meta},
            }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=FakeResponse())
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.health.reporter.httpx.AsyncClient", return_value=mock_cm):
        result = await check_news_feed_freshness()

    assert result["status"] == "passed"
