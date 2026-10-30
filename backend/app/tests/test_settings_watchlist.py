"""Tests for settings/watchlist persistence helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.settings.watchlist import get_effective_watchlist, sync_default_watchlist


@pytest.mark.asyncio
async def test_get_effective_watchlist_prefers_redis():
    db = AsyncMock()
    with patch("app.services.settings.watchlist.cache_get", AsyncMock(return_value={"default_watchlist": ["TSLA"]})):
        tickers = await get_effective_watchlist(db, "user@test.com")
    assert tickers == ["TSLA"]
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_effective_watchlist_falls_back_to_db():
    db = AsyncMock()
    owned = MagicMock()
    owned.tickers = ["NVDA", "AMD"]
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=owned)))
    with patch("app.services.settings.watchlist.cache_get", AsyncMock(return_value=None)):
        tickers = await get_effective_watchlist(db, "user@test.com")
    assert tickers == ["NVDA", "AMD"]


@pytest.mark.asyncio
async def test_new_user_without_own_list_gets_configured_default():
    from app.core.config import settings

    db = AsyncMock()
    user = MagicMock(id="u-new")
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=user)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )
    with patch("app.services.settings.watchlist.cache_get", AsyncMock(return_value=None)):
        tickers = await get_effective_watchlist(db, "expert@test.com")
    assert tickers == list(dict.fromkeys(settings.default_watchlist_list))
    assert db.execute.await_count == 2  # the shared default row is not consulted

@pytest.mark.asyncio
async def test_get_effective_watchlist_preserves_long_lists():
    db = AsyncMock()
    long_list = [f"SYM{i}" for i in range(17)]
    with patch("app.services.settings.watchlist.cache_get", AsyncMock(return_value={"default_watchlist": long_list})):
        tickers = await get_effective_watchlist(db, "user@test.com")
    assert tickers == long_list
    assert len(tickers) == 17


@pytest.mark.asyncio
async def test_sync_default_watchlist_persists_and_ensures_instruments():
    db = AsyncMock()
    user = MagicMock()
    user.id = "user-1"
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=user)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )
    db.commit = AsyncMock()

    with patch(
        "app.services.instrument.resolver.ensure_instruments_for_symbols",
        AsyncMock(return_value=[]),
    ) as ensure_mock:
        await sync_default_watchlist(db, "user@test.com", ["AAPL", "MSFT"])

    ensure_mock.assert_awaited_once_with(db, ["AAPL", "MSFT"])
    db.commit.assert_awaited_once()
