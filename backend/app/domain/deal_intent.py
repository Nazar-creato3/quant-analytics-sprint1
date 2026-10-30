"""DealIntent — unit of work for trade execution (intent container, not a broker order)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.domain.deal_intent_enums import (
    DealIntentDirection,
    DealIntentStatus,
    RiskTag,
    TimeInForce,
    TriggerType,
)
from app.domain.deal_intent_fsm import DealIntentEvent, DealIntentStateMachine, DealIntentTransitionError
from app.domain.enums import Strategy
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class DealIntentORM(Base):
    """ORM mapping for ``deal_intents`` — the sole path to broker execution."""

    __tablename__ = "deal_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sleeve_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sleeves.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    entry_reason: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    required_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    max_slippage_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_spread_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(10), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_logic: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    hedge_attachment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("deal_intents.id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    risk_tag: Mapped[str] = mapped_column(String(20), nullable=False)
    news_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    correlation_lock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    volatility_lock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: DealIntentStatus.DRAFT.value,
        server_default="draft",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    instrument = relationship("InstrumentORM", foreign_keys=[instrument_id])
    sleeve = relationship("SleeveORM", foreign_keys=[sleeve_id])
    hedge_attachment = relationship(
        "DealIntentORM",
        remote_side="DealIntentORM.id",
        foreign_keys=[hedge_attachment_id],
    )


class DealIntentBase(BaseModel):
    instrument_id: int = Field(gt=0)
    sleeve_id: str = Field(min_length=1, max_length=36)
    direction: DealIntentDirection
    target_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    entry_reason: str = Field(min_length=1)
    strategy: Strategy
    required_confidence: float = Field(ge=0.0, le=1.0)
    max_slippage_bps: int = Field(ge=0)
    max_spread_bps: int = Field(ge=0)
    time_in_force: TimeInForce = TimeInForce.DAY
    trigger_type: TriggerType
    exit_logic: dict[str, Any] = Field(default_factory=dict)
    hedge_attachment_id: str | None = Field(default=None, max_length=36)
    approval_threshold: Decimal = Field(ge=Decimal("0"))
    risk_tag: RiskTag
    news_lock: bool = False
    correlation_lock: bool = False
    volatility_lock: bool = False
    status: DealIntentStatus = DealIntentStatus.DRAFT

    @field_validator("entry_reason")
    @classmethod
    def strip_entry_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("entry_reason must not be blank")
        return normalized


class DealIntentCreate(DealIntentBase):
    pass


class DealIntentRead(DealIntentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row: DealIntentORM) -> DealIntentRead:
        return cls(
            id=row.id,
            instrument_id=row.instrument_id,
            sleeve_id=row.sleeve_id,
            direction=DealIntentDirection(row.direction),
            target_price=row.target_price,
            entry_reason=row.entry_reason,
            strategy=Strategy(row.strategy),
            required_confidence=row.required_confidence,
            max_slippage_bps=row.max_slippage_bps,
            max_spread_bps=row.max_spread_bps,
            time_in_force=TimeInForce(row.time_in_force),
            trigger_type=TriggerType(row.trigger_type),
            exit_logic=row.exit_logic or {},
            hedge_attachment_id=row.hedge_attachment_id,
            approval_threshold=row.approval_threshold,
            risk_tag=RiskTag(row.risk_tag),
            news_lock=row.news_lock,
            correlation_lock=row.correlation_lock,
            volatility_lock=row.volatility_lock,
            status=DealIntentStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def transition_deal_intent_status(
    current: DealIntentStatus,
    event: DealIntentEvent,
    *,
    machine: DealIntentStateMachine | None = None,
) -> DealIntentStatus:
    """Apply a lifecycle event and return the next status."""
    fsm = machine or DealIntentStateMachine()
    return fsm.apply_to_status(current, event)


__all__ = [
    "DealIntentCreate",
    "DealIntentEvent",
    "DealIntentORM",
    "DealIntentRead",
    "DealIntentStateMachine",
    "DealIntentTransitionError",
    "transition_deal_intent_status",
]
