"""Tests for keyed terminal news providers (Finnhub / Tiingo / Polygon)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.market_data.http_providers import FinnhubMarketClient, TiingoClient
from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi
from app.services.terminal_platform.providers.keyed_market import FinnhubDataProvider
from app.services.terminal_platform.types import DataType


@pytest.mark.asyncio
async def test_finnhub_get_company_news_parses_list():
    client = FinnhubMarketClient()
    client._api_key = "test-key"
    payload = [
        {
            "headline": "AAPL beats estimates",
            "summary": "Strong quarter",
            "source": "Reuters",
            "url": "https://example.com/a",
            "datetime": 1_700_000_000,
            "related": "AAPL",
        }
    ]
    with patch.object(client, "_get_any", new=AsyncMock(return_value=payload)):
        rows = await client.get_company_news("AAPL", limit=5)
    assert len(rows) == 1
    assert rows[0]["title"] == "AAPL beats estimates"
    assert rows[0]["provider"] == "finnhub"


@pytest.mark.asyncio
async def test_tiingo_get_news_parses_list():
    client = TiingoClient()
    client._api_key = "test-key"
    payload = [
        {
            "title": "Markets rally",
            "description": "Risk-on",
            "source": "Bloomberg",
            "url": "https://example.com/b",
            "publishedDate": "2026-08-08T12:00:00Z",
            "tickers": ["aapl"],
        }
    ]
    with patch.object(client, "_get", new=AsyncMock(return_value=payload)):
        rows = await client.get_news(symbols=["AAPL"], limit=5)
    assert len(rows) == 1
    assert rows[0]["provider"] == "tiingo"
    assert rows[0]["symbols"] == ["AAPL"]


@pytest.mark.asyncio
async def test_finnhub_provider_supports_news():
    provider = FinnhubDataProvider()
    assert DataType.NEWS in provider.supported_data_types
    provider._api_key = "test-key"
    fake_rows = [
        {
            "title": "Headline",
            "summary": None,
            "source": "finnhub",
            "url": "https://example.com",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "symbols": ["AAPL"],
            "provider": "finnhub",
        }
    ]
    with patch(
        "app.services.market_data.http_providers.FinnhubMarketClient.get_news",
        new=AsyncMock(return_value=fake_rows),
    ):
        result = await provider.fetch_news(symbols=["AAPL"], limit=5)
    assert result.success
    assert result.provider == "finnhub"
    assert len(result.data) == 1


@pytest.mark.asyncio
async def test_fetch_terminal_news_prefers_keyed_when_configured():
    keyed_row = [
        {
            "title": "Keyed Finnhub headline",
            "source": "finnhub-test",
            "url": "https://example.com/keyed",
            "published_at": "2026-08-08T18:00:00+00:00",
            "summary": "from finnhub",
            "provider": "finnhub",
        }
    ]

    async def _fake_rss(**kwargs):
        return []

    async def _fake_router_news(*args, **kwargs):
        class R:
            success = False
            data = None

        return R()

    with (
        patch(
            "app.services.market_data.http_providers.key_configured",
            side_effect=lambda name: name == "finnhub",
        ),
        patch(
            "app.services.market_data.http_providers.FinnhubMarketClient.get_news",
            new=AsyncMock(return_value=keyed_row),
        ),
        patch(
            "app.services.news.client.fetch_rss_articles",
            new=_fake_rss,
        ),
        patch(
            "app.services.terminal_platform.factory.get_terminal_router",
        ) as router_mock,
    ):
        router_mock.return_value.get_news = AsyncMock(side_effect=_fake_router_news)
        rows = await fetch_terminal_news_multi(limit=5)

    assert any("Keyed Finnhub headline" == r.headline for r in rows)
    assert any("finnhub" in (r.source or "").lower() for r in rows)


@pytest.mark.asyncio
async def test_fetch_rss_uses_httpx_with_user_agent():
    from app.services.news.client import fetch_rss_articles

    fake_xml = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>Macro headline</title>
      <link>https://example.com/rss-1</link>
      <pubDate>Mon, 10 Aug 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>"""

    class FakeResp:
        def raise_for_status(self):
            return None

        content = fake_xml

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            assert "investing.com" in url or "rbc" in url or "interfax" in url
            return FakeResp()

    with patch("app.services.news.client.httpx.AsyncClient", FakeClient):
        items = await fetch_rss_articles(max_results=5)

    assert items
    assert items[0]["title"] == "Macro headline"
    assert items[0]["url"] == "https://example.com/rss-1"
