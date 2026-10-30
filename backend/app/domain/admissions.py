"""Admissions CRM — AdmissionCase state machine (Prompt 57)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class AdmissionStatus(str, Enum):
    LEAD = "lead"
    TRIAL = "trial"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAYING = "paying"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    OFFBOARDED = "offboarded"


ALLOWED_TRANSITIONS: dict[AdmissionStatus, frozenset[AdmissionStatus]] = {
    AdmissionStatus.LEAD: frozenset(
        {
            AdmissionStatus.TRIAL,
            AdmissionStatus.CONTACTED,
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.OFFBOARDED,
        }
    ),
    AdmissionStatus.TRIAL: frozenset(
        {
            AdmissionStatus.CONTACTED,
            AdmissionStatus.QUALIFIED,
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.SUSPENDED,
            AdmissionStatus.OFFBOARDED,
        }
    ),
    AdmissionStatus.CONTACTED: frozenset(
        {
            AdmissionStatus.QUALIFIED,
            AdmissionStatus.TRIAL,
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.OFFBOARDED,
        }
    ),
    AdmissionStatus.QUALIFIED: frozenset(
        {
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
            AdmissionStatus.CONTACTED,
            AdmissionStatus.OFFBOARDED,
        }
    ),
    AdmissionStatus.APPROVED: frozenset(
        {
            AdmissionStatus.PAYING,
            AdmissionStatus.ACTIVE,
            AdmissionStatus.REJECTED,
            AdmissionStatus.SUSPENDED,
        }
    ),
    AdmissionStatus.REJECTED: frozenset({AdmissionStatus.LEAD, AdmissionStatus.CONTACTED}),
    AdmissionStatus.PAYING: frozenset(
        {AdmissionStatus.ACTIVE, AdmissionStatus.SUSPENDED, AdmissionStatus.OFFBOARDED}
    ),
    AdmissionStatus.ACTIVE: frozenset(
        {AdmissionStatus.SUSPENDED, AdmissionStatus.OFFBOARDED, AdmissionStatus.PAYING}
    ),
    AdmissionStatus.SUSPENDED: frozenset(
        {AdmissionStatus.ACTIVE, AdmissionStatus.OFFBOARDED, AdmissionStatus.REJECTED}
    ),
    AdmissionStatus.OFFBOARDED: frozenset({AdmissionStatus.LEAD}),
}

DISPLAY_BUCKETS: dict[str, tuple[str, ...]] = {
    "trial": ("lead", "trial", "contacted", "qualified"),
    "paying": ("paying",),
    "full": ("approved", "active"),
    "blocked": ("suspended", "rejected", "offboarded"),
}


def display_bucket_for_status(status: str | AdmissionStatus) -> str:
    value = status.value if isinstance(status, AdmissionStatus) else (status or "")
    for bucket, statuses in DISPLAY_BUCKETS.items():
        if value in statuses:
            return bucket
    return "trial"


class AdmissionTransitionError(ValueError):
    pass


def assert_admission_transition(
    current: AdmissionStatus,
    target: AdmissionStatus,
    *,
    admin_override: bool = False,
) -> None:
    if current == target:
        return
    if admin_override:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise AdmissionTransitionError(
            f"Illegal admission transition {current.value} → {target.value}"
        )


class AdmissionCaseORM(Base):
    __tablename__ = "admission_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AdmissionStatus.LEAD.value, index=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")
    jurisdiction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    capital_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strategy_interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AdmissionStatusHistoryORM(Base):
    __tablename__ = "admission_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("admission_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AdmissionCaseCreate(BaseModel):
    contact_email: str
    contact_name: str | None = None
    contact_phone: str | None = None
    source: str = "manual"
    jurisdiction: str | None = None
    capital_range: str | None = None
    experience_level: str | None = None
    strategy_interest: str | None = None
    notes: str | None = None
    user_id: str | None = None


class AdmissionApplicationCreate(BaseModel):
    """Public web form — no auth required."""

    contact_email: str
    contact_name: str | None = None
    contact_phone: str | None = None
    jurisdiction: str | None = None
    capital_range: str | None = None
    experience_level: str | None = None
    strategy_interest: str | None = None
    notes: str | None = None
    fingerprint: str | None = None
    user_agent: str | None = None
    turnstile_token: str | None = None


class AdmissionCaseRead(BaseModel):
    id: str
    status: AdmissionStatus
    source: str
    jurisdiction: str | None = None
    capital_range: str | None = None
    experience_level: str | None = None
    strategy_interest: str | None = None
    owner_user_id: str | None = None
    contact_email: str
    contact_name: str | None = None
    contact_phone: str | None = None
    user_id: str | None = None
    notes: str | None = None
    trial_used: bool = False
    has_platform_account: bool = False
    is_admin: bool = False
    display_bucket: str = "trial"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CallNoteCreate(BaseModel):
    note: str = Field(min_length=1)


class RejectBody(BaseModel):
    reason: str = Field(min_length=3)


class ChangeStatusBody(BaseModel):
    status: AdmissionStatus
    reason: str | None = None


class AssignOwnerBody(BaseModel):
    owner_user_id: str


class InviteAccessBody(BaseModel):
    contact_email: str
    contact_name: str | None = None
