"""Ranks page guards: no SEC lookups for non-US symbols; SEC ticker file fetched once."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.forecast.fund_news_extras import _sec_candidate
from app.services.fundamental_data import native_sec_finra as sec


def test_sec_only_for_us_symbols() -> None:
    assert _sec_candidate("AAPL")
    assert not _sec_candidate("SBER")
    assert not _sec_candidate("BTC-USD")


@pytest.mark.asyncio
async def test_ticker_map_downloaded_once(monkeypatch) -> None:
    sec._CIK_CACHE.clear()
    sec._TICKER_MAP_AT = None
    resp = MagicMock()
    resp.json.return_value = {"0": {"ticker": "AAPL", "cik_str": 320193}}
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    p = sec.NativeSecFinraProvider()
    monkeypatch.setattr(p, "_client", AsyncMock(return_value=client))
    assert await p.resolve_cik("AAPL")
    assert await p.resolve_cik("ZZZZ") is None
    assert await p.resolve_cik("QQQQ") is None
    assert client.get.await_count == 1
