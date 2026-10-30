"""Unified strategy bot catalog (grid / dca / momentum)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum
import uuid

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class BotType(str, PyEnum):
    GRID = "grid"
    DCA = "dca"
    MOMENTUM = "momentum"


class BotStatus(str, PyEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    bot_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BotStatus.ACTIVE.value)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    balance_allocated: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
