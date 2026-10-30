"""Device trust + signup abuse + billing stub + subportfolio tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import User, UserRole
from app.domain.access_policy import AccessLevel
from app.domain.rbac import TrustLevel
from app.domain.sub_portfolio import diversification_score
from app.domain.subscription import (
    SubscriptionCreate,
    SubscriptionORM,
    SubscriptionTier,
    subscription_service,
)
from app.services.device_identity.service import device_identity_service
from app.services.device_trust.policy import PrivilegedIdentityPolicy, StandardUserPolicy, policy_for_trust_level
from app.services.signup_abuse.guard import score_signup_abuse


def test_standard_blocks_second_account():
    d = StandardUserPolicy().evaluate(
        active_devices=1, accounts_on_device=1, is_new_account_on_device=True
    )
    assert d.allowed is False
    assert d.require_manual_review is True


def test_privileged_allows_many():
    d = PrivilegedIdentityPolicy().evaluate(
        active_devices=5, accounts_on_device=3, is_new_account_on_device=True
    )
    assert d.allowed is True
    assert policy_for_trust_level(TrustLevel.PRIVILEGED).__class__ is PrivilegedIdentityPolicy


@pytest.mark.asyncio
async def test_resolve_device_trust_staff_on_device():
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(UserRole.ADMIN, TrustLevel.STANDARD.value, "user")]
    db.execute = AsyncMock(return_value=result)
    trust = await device_identity_service.resolve_device_trust(db, "device-1")
    assert trust == TrustLevel.PRIVILEGED


def test_abuse_combined_weak_signals_raise_review():
    r = score_signup_abuse(
        email="user@mailinator.com",
        velocity_flag=True,
        proxy_risk=0.4,
        timezone_mismatch=True,
    )
    assert r.risk_score >= 0.45
    assert r.decision_hint in ("manual_review", "block")


def test_dunning_suspends_after_max_failures():
    sub = SubscriptionORM(
        id="s1",
        profile_id="p1",
        tier=SubscriptionTier.STARTER.value,
        billing_cycle="monthly",
        status="active",
        failed_payments=0,
    )
    for _ in range(2):
        out = subscription_service.handle_failed_payment(sub)
        assert out["action"] == "retry"
    out = subscription_service.handle_failed_payment(sub)
    assert out["action"] == "suspend_access"
    assert sub.status == "suspended"


def test_tier_maps_to_access():
    assert subscription_service.access_level_for_tier(SubscriptionTier.PRO) == AccessLevel.APPROVED_LIVE


def test_create_subscription_rejects_foreign_profile():
    """GA16-028: body.profile_id cannot take over another account."""
    body = SubscriptionCreate(profile_id="victim", tier=SubscriptionTier.STARTER)
    with pytest.raises(PermissionError):
        subscription_service.create_subscription(body, owner_profile_id="alice")
    own = subscription_service.create_subscription(body.model_copy(update={"profile_id": "alice"}), owner_profile_id="alice")
    assert own.profile_id == "alice"
    assert own.status == "open"
    assert own.status != "active"


def test_diversification_score_range():
    s = diversification_score(
        strategy_tags=["momentum", "us"],
        peer_tags=[["mean_reversion"], ["momentum", "eu"]],
        risk_budget=1.0,
    )
    assert 0.0 <= s <= 1.0
