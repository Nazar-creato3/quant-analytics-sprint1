"""GA16-363: cockpit correlations from series only — no SPY/QQQ stubs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.cockpit import service as cockpit_service


@pytest.mark.asyncio
async def test_ga16_363_no_stub_when_short_series():
    bars = [SimpleNamespace(close=100.0 + i) for i in range(5)]
    out = await cockpit_service._correlations_from_series(
        AsyncMock(),
        symbol="AAPL",
        sector="Technology",
        bars=bars,
    )
    assert out == []


@pytest.mark.asyncio
async def test_ga16_363_no_spy_qqq_fallback_without_sector(monkeypatch):
    bars = [SimpleNamespace(close=100.0 * (1.01**i)) for i in range(40)]

    async def _no_bars(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.services.market_data.bars.get_bars_for_chart",
        _no_bars,
    )
    out = await cockpit_service._correlations_from_series(
        AsyncMock(),
        symbol="ZZZ",
        sector=None,
        bars=bars,
    )
    symbols = {p.symbol for p in out}
    assert "SPY" not in symbols
    assert "QQQ" not in symbols
    assert out == []


@pytest.mark.asyncio
async def test_ga16_363_computes_from_peer_series(monkeypatch):
    base = [100.0 * (1.01**i) for i in range(40)]
    peer = [50.0 * (1.008**i) for i in range(40)]
    bars = [SimpleNamespace(close=c) for c in base]

    async def _peer_bars(db, symbol, *args, **kwargs):
        if symbol == "MSFT":
            return [SimpleNamespace(close=c) for c in peer]
        return []

    monkeypatch.setattr(
        "app.services.market_data.bars.get_bars_for_chart",
        _peer_bars,
    )
    out = await cockpit_service._correlations_from_series(
        AsyncMock(),
        symbol="AAPL",
        sector="Technology",
        bars=bars,
    )
    assert len(out) == 1
    assert out[0].symbol == "MSFT"
    assert out[0].correlation is not None
    assert -1.0 <= out[0].correlation <= 1.0
