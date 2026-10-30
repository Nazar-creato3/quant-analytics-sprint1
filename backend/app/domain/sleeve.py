"""Sleeve domain entity — capital bucket within a trading profile."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.domain.enums import AssetCategory, SleeveStatus
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class SleeveORM(Base):
    __tablename__ = "sleeves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    capital_allocation_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_budget: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=lambda: SleeveStatus.ACTIVE.value,
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SleeveBase(BaseModel):
    profile_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=100)
    category: AssetCategory
    capital_allocation_pct: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))
    risk_budget: Decimal = Field(ge=Decimal("0"))
    status: SleeveStatus = SleeveStatus.ACTIVE

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class SleeveCreate(SleeveBase):
    pass


class SleeveRead(SleeveBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
