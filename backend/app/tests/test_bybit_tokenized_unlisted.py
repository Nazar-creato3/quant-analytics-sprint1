"""Execution availability uses live Bybit instrument cache (not static lists)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.execution.capability import resolve_execution_capability
from app.services.execution.symbol_mapping import (
    EXECUTION_UNAVAILABLE_RU,
    bybit_tokenized_unavailable_reason,
    list_bybit_tradeable_tokenized_bases,
)

MOCK_LIVE_BYBIT = {
    "AAPL": "AAPLXUSDT",
    "MSFT": "MSFTXUSDT",
    "GOOGL": "GOOGLXUSDT",
    "AMZN": "AMZNXUSDT",
    "NVDA": "NVDAXUSDT",
    "TSLA": "TSLAXUSDT",
    "COIN": "COINXUSDT",
}


@pytest.fixture
def mock_bybit_instruments(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_map(*_args, **_kwargs):
        return dict(MOCK_LIVE_BYBIT)

    monkeypatch.setattr(
        "app.services.execution.bybit_instruments.get_bybit_tokenized_instruments",
        _fake_map,
    )


@pytest.mark.asyncio
async def test_unlisted_symbols_get_reason(mock_bybit_instruments) -> None:
    for sym in ("SPY", "QQQ", "AMD", "NFLX", "MSTR", "GLD"):
        assert await bybit_tokenized_unavailable_reason(sym) == EXECUTION_UNAVAILABLE_RU


@pytest.mark.asyncio
async def test_listed_symbols_have_no_reason(mock_bybit_instruments) -> None:
    bases = await list_bybit_tradeable_tokenized_bases()
    for sym in bases:
        assert await bybit_tokenized_unavailable_reason(sym) is None


@pytest.mark.asyncio
async def test_msft_connect_required_when_listed_but_no_user_key(mock_bybit_instruments) -> None:
    db = AsyncMock()
    with patch(
        "app.services.execution.capability.user_has_trading_key",
        new=AsyncMock(return_value=False),
    ):
        cap = await resolve_execution_capability(db, ticker="MSFT", user_id="u1")

    assert cap.bybit_tokenized_listed is True
    assert cap.execution_enabled is False
    assert cap.block_type == "connect_provider"


@pytest.mark.asyncio
async def test_msft_unavailable_when_absent_from_live_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(*_args, **_kwargs):
        return {"AAPL": "AAPLXUSDT"}

    monkeypatch.setattr(
        "app.services.execution.bybit_instruments.get_bybit_tokenized_instruments",
        _empty,
    )
    db = AsyncMock()
    cap = await resolve_execution_capability(db, ticker="MSFT", user_id="u1")
    assert cap.execution_enabled is False
    assert cap.bybit_tokenized_listed is False
    assert cap.block_type == "unavailable"


@pytest.mark.asyncio
async def test_aapl_allowed_with_user_key(mock_bybit_instruments) -> None:
    db = AsyncMock()
    with patch(
        "app.services.execution.capability.user_has_trading_key",
        new=AsyncMock(return_value=True),
    ):
        cap = await resolve_execution_capability(db, ticker="AAPL", user_id="u1")

    assert cap.bybit_tokenized_listed is True
    assert cap.execution_enabled is True
