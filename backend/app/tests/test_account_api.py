"""Tests for personal cabinet (/account) API."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.api.v1.endpoints.account import router as account_router
from app.core.deps import get_current_user_email, get_db
from app.db.models import User, UserRole
from app.schemas.portfolio import PortfolioMetricsOut


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(account_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user_email] = lambda: "trader@test.com"

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _sample_user() -> User:
    return User(
        id="user-1",
        email="trader@test.com",
        hashed_password="x",
        role=UserRole.ANALYST,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _sample_metrics(**overrides) -> PortfolioMetricsOut:
    base = dict(
        trading_usd=25_000.0,
        balance_usd=75_000.0,
        total_usd=100_000.0,
        currency="USD",
        mode="paper",
        source="internal",
        open_maneuvers=2,
        active_grid_bots=0,
        as_of="2026-07-19T12:00:00+00:00",
        exposure_pct=25.0,
        max_exposure_pct=80.0,
        cash_buffer_usd=10_000.0,
        max_position_usd=5_000.0,
        max_position_pct=5.0,
    )
    base.update(overrides)
    return PortfolioMetricsOut(**base)


def _sample_balance(**overrides) -> "AccountBalanceOut":
    from app.schemas.account import AccountBalanceOut

    base = dict(
        total_usd=100_000.0,
        free_usd=75_000.0,
        locked_usd=25_000.0,
        currency="USD",
        mode="paper",
        is_paper=True,
        as_of="2026-07-19T12:00:00+00:00",
    )
    base.update(overrides)
    return AccountBalanceOut(**base)


class TestAccountSummary:
    @patch("app.services.account.service._build_portfolios", new_callable=AsyncMock)
    @patch("app.services.account.service.build_portfolio_metrics", new_callable=AsyncMock)
    @patch("app.services.account.service._get_user", new_callable=AsyncMock)
    def test_get_account_returns_profile_and_balance(
        self, mock_user, mock_metrics, mock_portfolios, client
    ):
        mock_user.return_value = _sample_user()
        mock_metrics.return_value = _sample_metrics()
        mock_portfolios.return_value = []

        resp = client.get("/api/v1/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["email"] == "trader@test.com"
        assert data["user"]["name"] == "Trader"
        assert data["balance"]["total_usd"] == 100_000.0
        assert data["balance"]["free_usd"] == 75_000.0
        assert data["balance"]["locked_usd"] == 25_000.0
        assert data["balance"]["is_paper"] is True

    @patch("app.api.v1.endpoints.account.get_account_summary", new_callable=AsyncMock)
    def test_profile_alias(self, mock_summary, client):
        from app.schemas.account import AccountSummaryOut, AccountUserOut

        mock_summary.return_value = AccountSummaryOut(
            user=AccountUserOut(
                id="user-1",
                email="trader@test.com",
                name="Trader",
                role="analyst",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            balance=_sample_balance(),
            portfolios=[],
        )
        resp = client.get("/api/v1/account/profile")
        assert resp.status_code == 200

class TestPaperTransfers:
    @patch("app.api.v1.endpoints.account.paper_deposit", new_callable=AsyncMock)
    def test_deposit_endpoint(self, mock_deposit, client):
        from app.schemas.account import PaperTransferOut

        mock_deposit.return_value = PaperTransferOut(
            transaction_type="deposit",
            amount_usd=5000.0,
            balance=_sample_balance(total_usd=105_000.0, free_usd=80_000.0),
            message="ok",
        )
        resp = client.post("/api/v1/account/deposit", json={"amount_usd": 5000})
        assert resp.status_code == 200
        mock_deposit.assert_called_once()

    @patch("app.api.v1.endpoints.account.paper_withdraw", new_callable=AsyncMock)
    def test_withdraw_endpoint(self, mock_withdraw, client):
        from app.schemas.account import PaperTransferOut

        mock_withdraw.return_value = PaperTransferOut(
            transaction_type="withdraw",
            amount_usd=1000.0,
            balance=_sample_balance(total_usd=99_000.0, free_usd=74_000.0),
            message="ok",
        )
        resp = client.post("/api/v1/account/withdraw", json={"amount_usd": 1000})
        assert resp.status_code == 200
        mock_withdraw.assert_called_once()

    def test_deposit_rejects_invalid_amount(self, client):
        resp = client.post("/api/v1/account/deposit", json={"amount_usd": -10})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_paper_deposit_increases_paper_equity():
    from app.services.account.service import paper_deposit

    db = AsyncMock()
    with patch(
        "app.services.account.service._metrics_to_balance",
        new_callable=AsyncMock,
        return_value=_sample_balance(total_usd=110_000.0, free_usd=85_000.0, locked_usd=25_000.0),
    ):
        with patch(
            "app.services.account.service._user_paper_equity",
            new_callable=AsyncMock,
            return_value=100_000.0,
        ):
            with patch(
                "app.services.account.service.set_user_paper_equity",
                new_callable=AsyncMock,
            ) as mock_set_equity:
                with patch("app.services.account.service._require_paper_transfers"):
                    result = await paper_deposit("trader@test.com", 10_000.0, db)
                    mock_set_equity.assert_awaited_once_with("trader@test.com", 110_000.0)
                    assert result.transaction_type == "deposit"
                    assert result.amount_usd == 10_000.0


@pytest.mark.asyncio
async def test_paper_withdraw_rejects_over_free_balance():
    from app.services.account.service import paper_withdraw
    from fastapi import HTTPException

    db = AsyncMock()
    with patch(
        "app.services.account.service._metrics_to_balance",
        new_callable=AsyncMock,
        return_value=_sample_balance(free_usd=500.0, locked_usd=0.0, total_usd=500.0),
    ):
        with patch("app.services.account.service._require_paper_transfers"):
            with pytest.raises(HTTPException) as exc:
                await paper_withdraw("trader@test.com", 1000.0, db)
            assert exc.value.status_code == 400


def test_ga16_308_missing_price_not_zero_usd():
    """Position without price must not appear as 0 USD (GA16-308)."""
    from app.schemas.account import PortfolioPositionOut
    from app.services.account.service import _market_value_usd, _sum_known_usd

    assert _market_value_usd(None) is None
    assert _market_value_usd("") is None
    assert _market_value_usd("123.45") == 123.45

    bare = PortfolioPositionOut(ticker="SBER", market_value_usd=_market_value_usd(None), side="long")
    assert bare.market_value_usd is None
    assert bare.model_dump()["market_value_usd"] is None

    priced = PortfolioPositionOut(ticker="GAZP", market_value_usd=50.0, side="long")
    assert _sum_known_usd([bare, priced]) == 50.0
    assert _sum_known_usd([bare]) is None
