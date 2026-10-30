"""Trading cap cannot exceed account total (100% of money on trading accounts)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.settings import router as settings_router
from app.core.deps import get_current_user_email, get_db
from app.services.portfolio.cap_limit import cap_exceeds_balance, clamp_cap_to_balance


def test_clamp_cap_never_exceeds_balance():
    assert clamp_cap_to_balance(15_000, 10_000) == 10_000.0
    assert clamp_cap_to_balance(4_000, 10_000) == 4_000.0
    assert clamp_cap_to_balance(10_000, 10_000) == 10_000.0
    assert clamp_cap_to_balance(500, 0) == 0.0


def test_cap_exceeds_balance_uses_cent_epsilon():
    assert cap_exceeds_balance(10_000.02, 10_000.0) is True
    assert cap_exceeds_balance(10_000.0, 10_000.0) is False
    assert cap_exceeds_balance(10_000.005, 10_000.0) is False


@pytest.mark.asyncio
async def test_settings_put_rejects_cap_above_account_total():
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "trial@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db

    with patch(
        "app.api.v1.endpoints.settings.cache_get",
        new=AsyncMock(return_value={"portfolio_size": 10_000}),
    ), patch(
        "app.services.portfolio.metrics.user_account_total_usd",
        new=AsyncMock(return_value=10_000.0),
    ):
        client = TestClient(app)
        resp = client.put("/api/v1/settings", json={"portfolio_size": 50_000})
    assert resp.status_code == 400
    assert "баланса" in resp.json()["detail"].lower() or "Кап" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_settings_put_allows_cap_at_full_balance():
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "trial@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db

    with patch(
        "app.api.v1.endpoints.settings.cache_get",
        new=AsyncMock(return_value={"portfolio_size": 8_000}),
    ), patch(
        "app.api.v1.endpoints.settings.cache_set",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.endpoints.settings.audit.log",
        new=AsyncMock(),
    ), patch(
        "app.services.portfolio.metrics.user_account_total_usd",
        new=AsyncMock(return_value=10_000.0),
    ):
        client = TestClient(app)
        resp = client.put("/api/v1/settings", json={"portfolio_size": 10_000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["portfolio_size"] == 10_000
    assert resp.json()["cap_max_usd"] == 10_000.0


@pytest.mark.asyncio
async def test_empty_live_wallet_cap_uses_paper_ledger():
    from types import SimpleNamespace

    from app.services.portfolio.metrics import user_account_total_usd

    with patch(
        "app.services.portfolio.user_scope.get_user_by_email",
        new=AsyncMock(return_value=SimpleNamespace(id="u1")),
    ), patch(
        "app.services.trading_keys.user_executor.resolve_user_account_mode",
        new=AsyncMock(return_value="live"),
    ), patch(
        "app.services.portfolio.metrics._venue_account_totals",
        new=AsyncMock(return_value=(0.0, 0.0)),
    ), patch(
        "app.services.portfolio.metrics._ledger_total_usd",
        new=AsyncMock(return_value=300.31),
    ):
        total = await user_account_total_usd("demo@example.com", AsyncMock())
    assert total == 300.31


@pytest.mark.asyncio
async def test_empty_paper_book_seeds_demo_cash_for_cap():
    from app.services.portfolio.metrics import user_account_total_usd
    from app.services.settings.new_user_defaults import DEMO_PAPER_EQUITY_USD

    with patch(
        "app.services.portfolio.user_scope.get_user_by_email",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.portfolio.metrics._ledger_total_usd",
        new=AsyncMock(side_effect=[0.0, DEMO_PAPER_EQUITY_USD]),
    ), patch(
        "app.services.portfolio.metrics.cache_get",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.services.portfolio.metrics.set_user_paper_equity",
        new=AsyncMock(),
    ) as seed:
        total = await user_account_total_usd("legacy@example.com", AsyncMock())
    seed.assert_awaited_once()
    assert total == DEMO_PAPER_EQUITY_USD


@pytest.mark.asyncio
async def test_redis_miss_does_not_reseed_demo_cash():
    from app.services.portfolio.metrics import user_account_total_usd

    with patch(
        "app.services.portfolio.user_scope.get_user_by_email",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.portfolio.metrics._ledger_total_usd",
        new=AsyncMock(return_value=0.0),
    ), patch(
        "app.services.portfolio.metrics.cache_get",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.portfolio.metrics.set_user_paper_equity",
        new=AsyncMock(),
    ) as seed:
        total = await user_account_total_usd("ops@example.com", AsyncMock())
    seed.assert_not_awaited()
    assert total == 0.0
