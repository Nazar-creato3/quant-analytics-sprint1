"""Manual review queue for DealIntents held by ApprovalPolicyEngine."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ReviewQueueStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ReviewQueueORM(Base):
    __tablename__ = "review_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sleeve_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sleeves.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    deal_intent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deal_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_state: Mapped[str] = mapped_column(String(30), nullable=False, default="hold_for_review")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    intent_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ReviewQueueStatus.PENDING.value,
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewQueueCreate(BaseModel):
    profile_id: str = Field(min_length=1, max_length=36)
    sleeve_id: str = Field(min_length=1, max_length=36)
    deal_intent_id: str = Field(min_length=1, max_length=36)
    policy_state: str = "hold_for_review"
    reason: str = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=1.0)
    intent_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReviewQueueRead(ReviewQueueCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: ReviewQueueStatus
    created_at: datetime
    resolved_at: datetime | None = None
