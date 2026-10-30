"""Secure application → trial → paywall domain models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class ApplicationStatus(str, Enum):
    PENDING_PHONE_OTP = "pending_phone_otp"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PaywallSubscriptionStatus(str, Enum):
    NONE = "none"
    TRIAL_ACTIVE = "trial_active"
    TRIAL_EXPIRED = "trial_expired"
    PAID = "paid"


TRIAL_DURATION_DAYS = 2


class ApplicationORM(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    capital_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experience: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strategy_interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ApplicationStatus.PENDING_PHONE_OTP.value, index=True
    )
    email_verification_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duplicate_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    twenty_crm_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    twenty_company_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    crm_sync_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", index=True
    )
    crm_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WebAuthnCredentialORM(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(default=0)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSubscriptionStateORM(Base):
    __tablename__ = "user_subscription_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    subscription_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PaywallSubscriptionStatus.NONE.value, index=True
    )
    trial_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SubscriptionStatusAuditORM(Base):
    __tablename__ = "subscription_status_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApplicationSubmitIn(BaseModel):
    name: str | None = None
    email: EmailStr
    phone: str = Field(min_length=5, max_length=50)
    jurisdiction: str | None = None
    capital_range: str | None = None
    experience: str | None = None
    strategy_interest: str | None = None
    comments: str | None = None
    turnstile_token: str = Field(min_length=1)
    otp_code: str = Field(min_length=4, max_length=8)


class ApplicationRequestOtpIn(BaseModel):
    phone: str = Field(min_length=5, max_length=50)
    turnstile_token: str = Field(min_length=1)


class ApplicationRead(BaseModel):
    id: str
    status: ApplicationStatus
    email: str
    duplicate_flag: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangePasswordIn(BaseModel):
    email: EmailStr
    current_password: str
    new_password: str = Field(min_length=12)


class PaymentWebhookIn(BaseModel):
    event: str
    user_id: str
    external_ref: str | None = None
    amount_usd: float | None = None
    signature: str
