"""Tests for unified bot catalog service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.bots import unified as unified_mod
from app.services.bots.unified import create_bot, delete_bot, get_bot, list_bots, patch_bot


@pytest.fixture(autouse=True)
def clear_memory_bots():
    for bucket in unified_mod._memory.values():
        bucket.clear()
    yield
    for bucket in unified_mod._memory.values():
        bucket.clear()


@pytest.fixture
def db():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.mark.asyncio
@patch("app.services.bots.store.cache_set", new_callable=AsyncMock, return_value=False)
@patch("app.services.bots.store.cache_get", new_callable=AsyncMock, return_value=None)
async def test_create_list_filter_patch_delete(_get, _set, db):
    dca = await create_bot(
        db=db,
        email="test@example.com",
        user_id="user-1",
        bot_type="dca",
        symbol="btcusdt",
        params={"interval_ticks": 5, "dip_pct": 0.02, "current_price": 50000},
        balance_allocated=10000,
    )
    assert dca["bot_type"] == "dca"
    assert dca["symbol"] == "BTCUSDT"
    assert dca["status"] == "active"
    assert dca["params"]["interval_ticks"] == 5

    mom = await create_bot(
        db=db,
        email="test@example.com",
        user_id="user-1",
        bot_type="momentum",
        symbol="ETHUSDT",
        params={"threshold": 0.03, "size": 0.5, "current_price": 3000},
        balance_allocated=8000,
    )
    assert mom["bot_type"] == "momentum"

    listed = await list_bots(db=db, email="test@example.com")
    assert len(listed) == 2

    only_dca = await list_bots(db=db, email="test@example.com", bot_type="dca")
    assert [row["bot_type"] for row in only_dca] == ["dca"]

    detail = await get_bot(db=db, email="test@example.com", bot_id=dca["id"])
    assert detail["id"] == dca["id"]

    stopped = await patch_bot(
        db=db,
        email="test@example.com",
        user_id="user-1",
        bot_id=dca["id"],
        status_value="stopped",
        params=None,
    )
    assert stopped["status"] == "stopped"

    await delete_bot(db=db, email="test@example.com", bot_id=dca["id"])
    remaining = await list_bots(db=db, email="test@example.com")
    assert len(remaining) == 1
    assert remaining[0]["bot_type"] == "momentum"


@pytest.mark.asyncio
async def test_rejects_unknown_type(db):
    with pytest.raises(Exception) as exc:
        await create_bot(
            db=db,
            email="test@example.com",
            user_id="user-1",
            bot_type="scalp",
            symbol="BTCUSDT",
            params={},
            balance_allocated=1000,
        )
    assert getattr(exc.value, "status_code", None) == 400
