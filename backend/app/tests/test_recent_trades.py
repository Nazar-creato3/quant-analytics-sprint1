"""Tests for recent trades tape fetchers."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.orders.recent_trades import _fetch_binance_trades, fetch_recent_trades


@pytest.mark.asyncio
async def test_fetch_binance_trades_parses_rows():
    mock_rows = [
        {"id": 1, "price": "65000.10", "qty": "0.015", "time": 1700000000000, "isBuyerMaker": False},
        {"id": 2, "price": "65000.05", "qty": "0.022", "time": 1700000001000, "isBuyerMaker": True},
    ]

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list:
            return mock_rows

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    with patch("app.services.orders.recent_trades.httpx.AsyncClient", return_value=FakeClient()):
        trades = await _fetch_binance_trades("BTCUSDT", limit=10)

    assert len(trades) == 2
    assert trades[0].source == "binance_trades"
    assert trades[0].side == "sell"
    assert trades[1].side == "buy"


@pytest.mark.asyncio
async def test_fetch_recent_trades_routes_crypto():
    with patch(
        "app.services.orders.recent_trades._fetch_binance_trades",
        return_value=[],
    ) as mock_binance:
        await fetch_recent_trades("ADAUSDT", limit=5)
    mock_binance.assert_awaited_once()
