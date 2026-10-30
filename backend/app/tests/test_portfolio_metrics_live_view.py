"""Header switch «Боевой» shows the broker account even with real trading off."""
from types import SimpleNamespace

import pytest

from app.services.portfolio import metrics as m


@pytest.mark.asyncio
async def test_live_view_uses_broker_totals(monkeypatch):
    async def user(_db, _email):
        return SimpleNamespace(id="u1")

    async def has_key(_db, _uid, **_kw):
        return True

    async def mode(_db, _uid):
        return "paper"  # trading off

    async def totals(_db, *, user_id, account_mode):
        assert account_mode == "live"
        return 2000.0, 10000.0

    monkeypatch.setattr("app.services.portfolio.user_scope.get_user_by_email", user)
    monkeypatch.setattr("app.services.trading_keys.user_executor.user_has_trading_key", has_key)
    monkeypatch.setattr("app.services.trading_keys.user_executor.resolve_user_account_mode", mode)
    monkeypatch.setattr(m, "_venue_account_totals", totals)

    out = await m.build_portfolio_metrics("a@b.c", db=None, view_mode="live")
    assert out.mode == "live" and out.source == "broker"
    assert out.total_usd == 10000.0 and out.balance_usd == 2000.0 and out.trading_usd == 8000.0


@pytest.mark.asyncio
async def test_live_view_without_broker_data_is_empty_not_demo(monkeypatch):
    async def totals(_db, *, user_id, account_mode):
        return None, None

    monkeypatch.setattr(m, "_venue_account_totals", totals)
    out = await m._broker_view_metrics(None, "u1")
    assert out.mode == "live" and out.total_usd == 0.0 and out.source == "broker_unavailable"
