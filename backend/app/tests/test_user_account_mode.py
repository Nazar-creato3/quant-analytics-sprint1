"""Live trading requires approval + the user's own API keys."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.settings.new_user_defaults import DEMO_PAPER_EQUITY_USD, new_user_settings_payload
from app.services.trading_keys import user_executor as ue


def test_new_user_gets_demo_paper_equity():
    payload = new_user_settings_payload()
    assert payload["paper_equity_usd"] == DEMO_PAPER_EQUITY_USD
    assert payload["portfolio_size"] == DEMO_PAPER_EQUITY_USD


@pytest.mark.asyncio
async def test_trial_user_stays_paper_even_if_platform_live(monkeypatch):
    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(
        "app.services.access_policy.service.access_policy_service.read",
        AsyncMock(return_value=SimpleNamespace(access_level="trial_read_only")),
    )
    monkeypatch.setattr(ue, "user_has_trading_key", AsyncMock(return_value=True))
    mode = await ue.resolve_user_account_mode(AsyncMock(), "user-1")
    assert mode == "paper"


@pytest.mark.asyncio
async def test_approved_without_keys_stays_paper(monkeypatch):
    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(
        "app.services.access_policy.service.access_policy_service.read",
        AsyncMock(return_value=SimpleNamespace(access_level="approved_live")),
    )
    monkeypatch.setattr(ue, "user_has_trading_key", AsyncMock(return_value=False))
    mode = await ue.resolve_user_account_mode(AsyncMock(), "user-1")
    assert mode == "paper"


@pytest.mark.asyncio
async def test_approved_with_keys_goes_live(monkeypatch):
    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(
        "app.services.access_policy.service.access_policy_service.read",
        AsyncMock(return_value=SimpleNamespace(access_level="approved_live")),
    )
    monkeypatch.setattr(ue, "user_has_trading_key", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.portfolio.user_venue_balances.live_wallet_has_funds",
        AsyncMock(return_value=True),
    )
    mode = await ue.resolve_user_account_mode(AsyncMock(), "user-1")
    assert mode == "live"


@pytest.mark.asyncio
async def test_approved_with_empty_live_wallet_stays_paper(monkeypatch):
    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(
        "app.services.access_policy.service.access_policy_service.read",
        AsyncMock(return_value=SimpleNamespace(access_level="approved_live")),
    )
    monkeypatch.setattr(ue, "user_has_trading_key", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.portfolio.user_venue_balances.live_wallet_has_funds",
        AsyncMock(return_value=False),
    )
    mode = await ue.resolve_user_account_mode(AsyncMock(), "user-1")
    assert mode == "paper"


@pytest.mark.asyncio
async def test_trial_cannot_force_live_executor(monkeypatch):
    """An explicit live request is refused, never silently filled on paper."""
    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(ue, "resolve_user_account_mode", AsyncMock(return_value="paper"))
    monkeypatch.setattr(ue, "live_unavailable_reason", AsyncMock(return_value="нет доступа"))
    with pytest.raises(ue.LiveTradingUnavailable) as err:
        await ue.get_user_executor(
            AsyncMock(),
            user_id="trial-user",
            ticker="AAPL",
            account_mode="live",
        )
    assert "нет доступа" in str(err.value)


@pytest.mark.asyncio
async def test_paper_request_stays_paper_even_when_live_allowed(monkeypatch):
    from app.services.execution.adapter import PaperExecutor

    monkeypatch.setattr(ue, "settings", SimpleNamespace(live_trading_unlocked=True))
    monkeypatch.setattr(ue, "resolve_user_account_mode", AsyncMock(return_value="live"))
    executor = await ue.get_user_executor(
        AsyncMock(),
        user_id="approved-user",
        ticker="SBER",
        account_mode="paper",
    )
    assert isinstance(executor, PaperExecutor)


@pytest.mark.asyncio
async def test_connect_live_tbank_token_allowed_for_viewing(monkeypatch):
    """A live T-Bank token is accepted while live trading is off (portfolio view)."""
    from app.services.trading_keys import service as svc
    from app.services.trading_keys.validators import ValidationResult
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LIVE_TRADING_ENABLED", False)
    seen: dict = {}

    async def fake_validate(venue, credentials, *, account_mode="live", provider_type=None):
        seen["mode"] = account_mode
        return ValidationResult(ok=False, error="stop here")

    monkeypatch.setattr(svc, "validate_venue_credentials", fake_validate)
    meta, validation = await svc.connect_trading_account(
        AsyncMock(),
        user_id="u1",
        venue="tinkoff",
        credentials={"token": "t.abc"},
        account_mode="live",
        no_withdrawal_confirmed=True,
    )
    # Got past the live gate to the broker check.
    assert seen["mode"] == "live"
    assert validation.error == "stop here"


@pytest.mark.asyncio
async def test_trial_full_grant_false():
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(role="viewer"))
    with patch(
        "app.services.access_policy.service.access_policy_service.read",
        AsyncMock(return_value=SimpleNamespace(access_level="trial_read_only")),
    ):
        assert await ue.user_has_full_trading_grant(db, "trial-user") is False


@pytest.mark.asyncio
async def test_connect_live_keys_blocked_without_grant(monkeypatch):
    from app.services.trading_keys.service import connect_trading_account
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(app_settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    with patch(
        "app.services.trading_keys.user_executor.user_has_full_trading_grant",
        new=AsyncMock(return_value=False),
    ):
        meta, validation = await connect_trading_account(
            AsyncMock(),
            user_id="trial-user",
            venue="binance",
            credentials={"api_key": "k" * 16, "api_secret": "s" * 16},
            account_mode="live",
            no_withdrawal_confirmed=True,
        )
    assert meta is None
    assert validation.ok is False
    # L-04: B — foreign venues stay paper-only for real users; refused before the grant check.
    assert "недоступно" in (validation.error or "")


@pytest.mark.asyncio
async def test_billing_stub_webhook_disabled():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.v1.endpoints.origination import billing_router
    from app.core.deps import get_db

    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")

    async def fake_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/billing/webhook/stub",
            json={
                "event": "payment_succeeded",
                "subscription_id": "sub-1",
                "amount_usd": 149,
            },
        )
    assert resp.status_code == 404


def test_lawyer_decisions_drive_live_gates(monkeypatch):
    from app.services.legal import gates

    monkeypatch.setattr(gates, "load_decisions", lambda: {"L-03": "Б", "L-04": "B"})
    assert gates.real_orders_allowed() is True
    assert gates.foreign_venues_live_allowed() is False
    monkeypatch.setattr(gates, "load_decisions", lambda: {"L-03": "A", "L-04": "A"})
    assert gates.real_orders_allowed() is False
    assert gates.foreign_venues_live_allowed() is True


@pytest.mark.asyncio
async def test_live_refused_when_l03_is_a(monkeypatch):
    from app.services.legal import gates

    monkeypatch.setattr(gates, "load_decisions", lambda: {"L-03": "A"})
    reason = await ue.live_unavailable_reason(AsyncMock(), "u1")
    assert reason and "Учебный" in reason
