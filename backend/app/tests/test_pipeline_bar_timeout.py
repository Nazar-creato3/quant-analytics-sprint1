"""A hanging market-data provider must not hold the whole analysis."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.pipeline import io


@pytest.mark.asyncio
async def test_slow_ticker_is_skipped_and_others_load(monkeypatch) -> None:
    async def no_db(_ticker: str, _limit: int):
        return None, False

    async def fake_bars(ticker: str, *_a, **_kw):
        if ticker == "SLOW":
            await asyncio.sleep(30)
        now = datetime.now(timezone.utc)
        return [
            {"timestamp": (now - timedelta(days=i)).isoformat(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            for i in range(40, 0, -1)
        ]

    monkeypatch.setattr(io, "_load_bars_from_db", no_db)
    monkeypatch.setattr(io, "_BAR_FETCH_TICKER_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr("app.services.market_data.client.get_bars_resolved", fake_bars)
    end = datetime.now(timezone.utc)
    started = asyncio.get_running_loop().time()
    data, raw = await io.fetch_watchlist_bars_parallel(["SBER", "SLOW", "GAZP"], end - timedelta(days=60), end, bar_limit=60)
    assert set(data) == {"SBER", "GAZP"}
    assert asyncio.get_running_loop().time() - started < 5


@pytest.mark.asyncio
async def test_stale_db_bars_used_when_provider_hangs(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    old = [
        {"timestamp": (now - timedelta(days=i + 7)).isoformat(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        for i in range(80, 0, -1)
    ]

    async def stale_db(_ticker: str, _limit: int):
        return old, True

    async def hang(*_a, **_kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(io, "_load_bars_from_db", stale_db)
    monkeypatch.setattr(io, "_BAR_FETCH_TICKER_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr("app.services.market_data.client.get_bars_resolved", hang)
    data, raw = await io.fetch_watchlist_bars_parallel(["TSLA"], now - timedelta(days=60), now, bar_limit=60)
    assert set(data) == {"TSLA"} and len(raw["TSLA"]) == 80
