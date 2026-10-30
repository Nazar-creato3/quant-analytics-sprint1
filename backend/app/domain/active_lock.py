"""Temporary news/event locks with TTL (Prompt 11 EventRiskLayer)."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ActiveLockType(str, Enum):
    NEWS_SHOCK = "news_shock"
    MACRO_EVENT = "macro_event"
    CALENDAR_PROXIMITY = "calendar_proximity"
    LIQUIDITY_DROUGHT = "liquidity_drought"


class ActiveLockORM(Base):
    __tablename__ = "active_locks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    lock_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sleeve_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sleeves.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    news_shock_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActiveLockCreate(BaseModel):
    lock_type: ActiveLockType
    news_shock_score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    expires_at: datetime
    instrument_id: int | None = None
    sleeve_id: str | None = None
    sector: str | None = None
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActiveLockRead(ActiveLockCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
