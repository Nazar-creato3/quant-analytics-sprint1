"""HTTP tests for DealIntent approve/reject endpoints and ownership."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.deal_intents import router as deal_intents_router
from app.core.deps import get_current_user_email, get_user_db
from app.db.models import User, UserRole
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.rbac import SystemRole
from app.services.approval.deal_intent_ops import DealIntentDecisionResult


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(deal_intents_router, prefix="/api/v1")

    async def fake_user():
        return "operator@test.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_user_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _regular_user() -> User:
    return User(
        id="user-a",
        email="alice@test.com",
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TestDealIntentEndpoints:
    @patch("app.api.v1.endpoints.deal_intents.approve_deal_intent", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.deal_intents._require_deal_intent_for_user", new_callable=AsyncMock)
    def test_approve_returns_200(self, scope_mock, approve_mock, client):
        scope_mock.return_value = MagicMock()
        approve_mock.return_value = DealIntentDecisionResult(
            deal_intent_id="intent-1",
            status_before=DealIntentStatus.PENDING_APPROVAL.value,
            status_after=DealIntentStatus.APPROVED.value,
            action="approve",
            message="DealIntent approved.",
        )
        resp = client.post("/api/v1/deal-intents/intent-1/approve", json={"action": "approve"})
        assert resp.status_code == 200
        assert resp.json()["status_after"] == DealIntentStatus.APPROVED.value
        scope_mock.assert_awaited_once()

    @patch("app.api.v1.endpoints.deal_intents.reject_deal_intent", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.deal_intents._require_deal_intent_for_user", new_callable=AsyncMock)
    def test_reject_returns_200(self, scope_mock, reject_mock, client):
        scope_mock.return_value = MagicMock()
        reject_mock.return_value = DealIntentDecisionResult(
            deal_intent_id="intent-1",
            status_before=DealIntentStatus.PENDING_APPROVAL.value,
            status_after=DealIntentStatus.REJECTED.value,
            action="reject",
            message="DealIntent rejected.",
        )
        resp = client.post(
            "/api/v1/deal-intents/intent-1/reject",
            json={"action": "reject", "reason": "risk too high"},
        )
        assert resp.status_code == 200
        assert resp.json()["status_after"] == DealIntentStatus.REJECTED.value

    @patch("app.api.v1.endpoints.deal_intents.approve_deal_intent", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.deal_intents._require_deal_intent_for_user", new_callable=AsyncMock)
    def test_approve_empty_body_defaults(self, scope_mock, approve_mock, client):
        scope_mock.return_value = MagicMock()
        approve_mock.return_value = DealIntentDecisionResult(
            deal_intent_id="intent-2",
            status_before=DealIntentStatus.PENDING_APPROVAL.value,
            status_after=DealIntentStatus.APPROVED.value,
            action="approve",
        )
        resp = client.post("/api/v1/deal-intents/intent-2/approve")
        assert resp.status_code == 200
        approve_mock.assert_awaited_once()

    @patch("app.api.v1.endpoints.deal_intents.edit_deal_intent", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.deal_intents._require_deal_intent_for_user", new_callable=AsyncMock)
    def test_patch_edit_forwards_extended_fields(self, scope_mock, edit_mock, client):
        from decimal import Decimal

        from app.domain.deal_intent import DealIntentRead
        from app.domain.deal_intent_enums import DealIntentDirection, RiskTag, TimeInForce, TriggerType
        from app.domain.enums import Strategy

        scope_mock.return_value = MagicMock()
        edit_mock.return_value = DealIntentRead(
            id="intent-96",
            instrument_id=1,
            sleeve_id="sleeve",
            direction=DealIntentDirection.SHORT,
            target_price=Decimal("50"),
            entry_reason="reason",
            strategy=Strategy.TREND,
            required_confidence=0.8,
            max_slippage_bps=12,
            max_spread_bps=6,
            time_in_force=TimeInForce.GTC,
            trigger_type=TriggerType.MARKET,
            exit_logic={"take_profit": {"price": 55}},
            hedge_attachment_id=None,
            approval_threshold=Decimal("0.7"),
            risk_tag=RiskTag.HIGH,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        resp = client.patch(
            "/api/v1/deal-intents/intent-96",
            json={
                "direction": "short",
                "max_slippage_bps": 12,
                "trigger_type": "market",
                "exit_logic": {"take_profit": {"price": 55}},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["direction"] == "short"
        edit_mock.assert_awaited_once()
        _, kwargs = edit_mock.await_args
        assert kwargs["direction"] == "short"
        assert kwargs["max_slippage_bps"] == 12


class TestDealIntentOwnership:
    @pytest.fixture
    def scoped_client(self):
        app = FastAPI()
        app.include_router(deal_intents_router, prefix="/api/v1")
        mock_db = AsyncMock()

        async def fake_db():
            yield mock_db

        app.dependency_overrides[get_user_db] = fake_db
        app.dependency_overrides[get_current_user_email] = lambda: "alice@test.com"

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client, mock_db

    def test_get_foreign_deal_intent_returns_404(self, scoped_client):
        client, mock_db = scoped_client
        user = _regular_user()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.core.rbac_deps.get_user_and_role",
            new=AsyncMock(return_value=(user, SystemRole.USER)),
        ), patch(
            "app.services.portfolio.user_scope.load_deal_intent_for_user",
            new=AsyncMock(return_value=None),
        ):
            resp = client.get("/api/v1/deal-intents/foreign-intent-id")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Намерение не найдено"

    def test_approve_foreign_deal_intent_returns_404(self, scoped_client):
        client, mock_db = scoped_client
        user = _regular_user()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.core.rbac_deps.get_user_and_role",
            new=AsyncMock(return_value=(user, SystemRole.USER)),
        ), patch(
            "app.services.portfolio.user_scope.load_deal_intent_for_user",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post(
                "/api/v1/deal-intents/foreign-intent-id/approve",
                json={"action": "approve"},
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Намерение не найдено"

    def test_cancel_foreign_deal_intent_returns_404(self, scoped_client):
        client, mock_db = scoped_client
        user = _regular_user()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.core.rbac_deps.get_user_and_role",
            new=AsyncMock(return_value=(user, SystemRole.USER)),
        ), patch(
            "app.services.portfolio.user_scope.load_deal_intent_for_user",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post("/api/v1/deal-intents/foreign-intent-id/cancel", json={})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Намерение не найдено"


def test_deal_intents_for_user_scoped_via_sleeve_profile():
    from app.services.portfolio.user_scope import deal_intents_for_user

    stmt = deal_intents_for_user("user-a")
    compiled = str(stmt).lower()
    assert "sleeves" in compiled or "sleeve" in compiled
    assert "profile_id" in compiled


def test_deal_intents_staff_all_skips_profile_filter():
    from app.services.portfolio.user_scope import deal_intents_for_user

    stmt = deal_intents_for_user("user-a", staff_all=True)
    compiled = str(stmt).lower()
    assert "profile_id" not in compiled
