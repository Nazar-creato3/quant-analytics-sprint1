"""Subscription stub module — no real Stripe charges (Prompt 59)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.domain.access_policy import AccessLevel
from app.utils.helpers import new_uuid, utcnow


class SubscriptionTier(str, Enum):
    STARTER = "starter"
    PRO = "pro"
    MANAGED = "managed"
    ENTERPRISE = "enterprise"


TIER_TO_ACCESS: dict[SubscriptionTier, AccessLevel] = {
    SubscriptionTier.STARTER: AccessLevel.PAPER_TRADING,
    SubscriptionTier.PRO: AccessLevel.APPROVED_LIVE,
    SubscriptionTier.MANAGED: AccessLevel.MANAGED_ACCOUNT,
    SubscriptionTier.ENTERPRISE: AccessLevel.ENTERPRISE,
}

TIER_PRICES_USD: dict[SubscriptionTier, float] = {
    SubscriptionTier.STARTER: 49.0,
    SubscriptionTier.PRO: 149.0,
    SubscriptionTier.MANAGED: 499.0,
    SubscriptionTier.ENTERPRISE: 0.0,  # custom
}


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class SubscriptionORM(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(30), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SubscriptionStatus.ACTIVE.value)
    failed_payments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class InvoiceORM(Base):
    __tablename__ = "subscription_invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subscription_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")


class SubscriptionCreate(BaseModel):
    profile_id: str
    tier: SubscriptionTier
    billing_cycle: str = "monthly"


class PaymentWebhookStub(BaseModel):
    """Stub webhook payload from future payment processor."""

    event: str  # payment_succeeded | payment_failed
    subscription_id: str
    amount_usd: float | None = None
    external_ref: str | None = None


MAX_DUNNING_ATTEMPTS = 3
DUNNING_RETRY_HOURS = [24, 72, 168]


class SubscriptionService:
    def create_subscription(self, body: SubscriptionCreate, *, owner_profile_id: str) -> SubscriptionORM:
        if body.profile_id != owner_profile_id:
            raise PermissionError("foreign profile")
        return SubscriptionORM(
            id=new_uuid(),
            profile_id=owner_profile_id,
            tier=body.tier.value,
            billing_cycle=body.billing_cycle,
            status="open",
        )

    def create_invoice(self, subscription: SubscriptionORM) -> InvoiceORM:
        tier = SubscriptionTier(subscription.tier)
        return InvoiceORM(
            id=new_uuid(),
            subscription_id=subscription.id,
            amount_usd=TIER_PRICES_USD[tier],
            status="open",
        )

    def record_payment(self, subscription: SubscriptionORM, invoice: InvoiceORM) -> None:
        invoice.status = "paid"
        invoice.paid_at = utcnow()
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.failed_payments = 0
        subscription.next_retry_at = None
        subscription.updated_at = utcnow()

    def handle_failed_payment(self, subscription: SubscriptionORM) -> dict[str, Any]:
        subscription.failed_payments += 1
        subscription.status = SubscriptionStatus.PAST_DUE.value
        attempt = subscription.failed_payments
        if attempt >= MAX_DUNNING_ATTEMPTS:
            subscription.status = SubscriptionStatus.SUSPENDED.value
            subscription.next_retry_at = None
            return {"action": "suspend_access", "failed_payments": attempt}
        hours = DUNNING_RETRY_HOURS[min(attempt - 1, len(DUNNING_RETRY_HOURS) - 1)]
        subscription.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        subscription.updated_at = utcnow()
        return {"action": "retry", "retry_hours": hours, "failed_payments": attempt}

    def resume_access(self, subscription: SubscriptionORM) -> None:
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.failed_payments = 0
        subscription.next_retry_at = None
        subscription.updated_at = utcnow()

    def access_level_for_tier(self, tier: SubscriptionTier | str) -> AccessLevel:
        t = SubscriptionTier(tier) if not isinstance(tier, SubscriptionTier) else tier
        return TIER_TO_ACCESS[t]


subscription_service = SubscriptionService()
