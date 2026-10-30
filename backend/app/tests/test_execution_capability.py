"""Dynamic execution capability — live Bybit instruments, no hardcoded per-ticker lists."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.execution.symbol_mapping import (
    EXECUTION_UNAVAILABLE_RU,
    _BYBIT_TOKENIZED,
    bybit_tokenized_unavailable_reason,
    is_bybit_listed_tokenized,
    is_tokenized_equity,
    list_tokenized_equity_symbols,
)

# HOOD is intentionally absent from the legacy static map.
PROOF_SYMBOL = "HOOD"
MOCK_LIVE_BYBIT = {
    "AAPL": "AAPLXUSDT",
    "MSFT": "MSFTXUSDT",
    "GOOGL": "GOOGLXUSDT",
    "GOOG": "GOOGLXUSDT",
    "AMZN": "AMZNXUSDT",
    "META": "METAXUSDT",
    "NVDA": "NVDAXUSDT",
    "TSLA": "TSLAXUSDT",
    "COIN": "COINXUSDT",
    PROOF_SYMBOL: "HOODXUSDT",
}


@pytest.fixture
def mock_bybit_instruments(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_map(*_args, **_kwargs):
        return dict(MOCK_LIVE_BYBIT)

    monkeypatch.setattr(
        "app.services.execution.bybit_instruments.get_bybit_tokenized_instruments",
        _fake_map,
    )


def test_proof_symbol_not_in_legacy_hardcoded_map() -> None:
    assert PROOF_SYMBOL not in _BYBIT_TOKENIZED
    assert PROOF_SYMBOL not in list_tokenized_equity_symbols()


@pytest.mark.asyncio
async def test_live_api_listing_enables_symbol_outside_hardcoded_map(mock_bybit_instruments) -> None:
    assert is_tokenized_equity(PROOF_SYMBOL)
    assert await is_bybit_listed_tokenized(PROOF_SYMBOL) is True
    assert await bybit_tokenized_unavailable_reason(PROOF_SYMBOL) is None


@pytest.mark.asyncio
async def test_symbol_without_exchange_listing_is_unavailable(mock_bybit_instruments) -> None:
    assert is_tokenized_equity("GLD")
    assert await is_bybit_listed_tokenized("GLD") is False
    assert await bybit_tokenized_unavailable_reason("GLD") == EXECUTION_UNAVAILABLE_RU


@pytest.mark.asyncio
async def test_capability_hood_requires_connect_without_user_key(mock_bybit_instruments) -> None:
    from app.services.execution.capability import resolve_execution_capability

    db = AsyncMock()
    cap = await resolve_execution_capability(db, ticker=PROOF_SYMBOL, user_id=None)

    assert cap.globally_tradeable is True
    assert cap.bybit_tokenized_listed is True
    assert cap.execution_enabled is True  # no user context -> global availability only
    assert cap.block_type is None


@pytest.mark.asyncio
async def test_capability_hood_requires_connect_with_user_no_key(mock_bybit_instruments) -> None:
    from app.services.execution.capability import resolve_execution_capability

    db = AsyncMock()
    with patch(
        "app.services.execution.capability.user_has_trading_key",
        new=AsyncMock(return_value=False),
    ):
        cap = await resolve_execution_capability(db, ticker=PROOF_SYMBOL, user_id="u1")

    assert cap.globally_tradeable is True
    assert cap.execution_enabled is False
    assert cap.block_type == "connect_provider"
    assert "Bybit" in (cap.block_reason_ru or "")


@pytest.mark.asyncio
async def test_capability_gld_unavailable(mock_bybit_instruments) -> None:
    from app.services.execution.capability import resolve_execution_capability

    db = AsyncMock()
    cap = await resolve_execution_capability(db, ticker="GLD", user_id="u1")

    assert cap.globally_tradeable is False
    assert cap.execution_enabled is False
    assert cap.block_type == "unavailable"
    assert cap.block_reason_ru == EXECUTION_UNAVAILABLE_RU


@pytest.mark.asyncio
async def test_resolve_execution_capability_hood_with_connected_user(
    mock_bybit_instruments,
) -> None:
    from app.services.execution.capability import resolve_execution_capability

    db = AsyncMock()
    with patch(
        "app.services.execution.capability.user_has_trading_key",
        new=AsyncMock(return_value=True),
    ):
        cap = await resolve_execution_capability(db, ticker=PROOF_SYMBOL, user_id="u1")

    assert cap.globally_tradeable is True
    assert cap.user_can_execute is True
    assert cap.execution_enabled is True
    assert cap.block_type is None


@pytest.mark.asyncio
async def test_symbol_execution_hint_hood(mock_bybit_instruments) -> None:
    from app.services.execution.capability import symbol_execution_hint

    hint = await symbol_execution_hint(PROOF_SYMBOL)
    assert hint["execution_available_globally"] is True
    assert hint["required_provider_ru"] == "Bybit"
