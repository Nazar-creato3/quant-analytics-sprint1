"""GA-073…077: CoinGecko HTTP failures stay empty and are logged."""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.services.market_data.http_providers import CoinGeckoClient


def test_ga073_except_pass_gone() -> None:
    src = inspect.getsource(CoinGeckoClient)
    assert "except Exception:\n            return None" not in src
    assert "except Exception:\n            rows = []" not in src
    assert "except Exception:\n            return {}" not in src
    assert "coingecko ohlc failed" in src
    assert "geckoterminal trending pools failed" in src


@pytest.mark.asyncio
async def test_ga074_bars_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client = CoinGeckoClient()

    async def resolve(*_a, **_k):
        return "bitcoin"

    async def boom(*_a, **_k):
        raise RuntimeError("cg down")

    monkeypatch.setattr(client, "_resolve_coin_id", resolve)

    monkeypatch.setattr(client, "_get", boom)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)
    rows = await client.get_bars("BTC-USD", "1d", start, end)
    assert rows == []


@pytest.mark.asyncio
async def test_ga075_trending_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client = CoinGeckoClient()

    async def boom(*_a, **_k):
        raise RuntimeError("cg down")

    monkeypatch.setattr(client, "_get", boom)
    assert await client.trending() == {}
