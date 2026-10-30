"""Kill switch state — global trading halt per system/profile/sleeve."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class KillSwitchStateORM(Base):
    __tablename__ = "kill_switch_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    unlock_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    unlocked_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KillSwitchStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope: str
    scope_id: str | None
    active: bool
    trigger_type: str
    reason: str
    unlock_comment: str | None
    triggered_by: str | None
    unlocked_by: str | None
    triggered_at: datetime
    unlocked_at: datetime | None
