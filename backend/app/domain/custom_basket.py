"""CustomBasket — user-defined instrument grouping within a profile (analytics only)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class CustomBasketItemORM(Base):
    """Weighted instrument membership in a custom basket."""

    __tablename__ = "custom_basket_items"
    __table_args__ = (
        UniqueConstraint("basket_id", "instrument_id", name="uq_custom_basket_items_basket_instrument"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    basket_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("custom_baskets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    basket = relationship("CustomBasketORM", back_populates="items")
    instrument = relationship("InstrumentORM", foreign_keys=[instrument_id])


class CustomBasketORM(Base):
    """User basket of instruments — grouping/analytics unit, not an execution container."""

    __tablename__ = "custom_baskets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sleeve_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sleeves.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    items = relationship(
        "CustomBasketItemORM",
        back_populates="basket",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sleeve = relationship("SleeveORM", foreign_keys=[sleeve_id])


class CustomBasketItemBase(BaseModel):
    instrument_id: int = Field(gt=0)
    weight_pct: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))

    @field_validator("weight_pct")
    @classmethod
    def quantize_weight(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"))


class CustomBasketItemCreate(CustomBasketItemBase):
    pass


class CustomBasketItemRead(CustomBasketItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    basket_id: str
    created_at: datetime
    updated_at: datetime


class CustomBasketBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    sleeve_id: str | None = Field(default=None, max_length=36)
    items: list[CustomBasketItemCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_composition(self) -> CustomBasketBase:
        validate_basket_composition(self.items)
        return self


class CustomBasketCreate(CustomBasketBase):
    pass


class CustomBasketUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    sleeve_id: str | None = Field(default=None, max_length=36)
    items: list[CustomBasketItemCreate] | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_composition(self) -> CustomBasketUpdate:
        if self.items is not None:
            validate_basket_composition(self.items)
        return self


class CustomBasketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_id: str
    name: str
    description: str | None
    sleeve_id: str | None
    items: list[CustomBasketItemRead]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row: CustomBasketORM) -> CustomBasketRead:
        return cls(
            id=row.id,
            profile_id=row.profile_id,
            name=row.name,
            description=row.description,
            sleeve_id=row.sleeve_id,
            items=[CustomBasketItemRead.model_validate(item) for item in row.items],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def validate_basket_composition(items: list[CustomBasketItemBase]) -> None:
    """Ensure basket weights sum to 100% and instruments are unique."""
    if not items:
        raise ValueError("basket must contain at least one instrument")

    seen: set[int] = set()
    total = Decimal("0")
    for item in items:
        if item.instrument_id in seen:
            raise ValueError(f"duplicate instrument_id in basket: {item.instrument_id}")
        seen.add(item.instrument_id)
        total += item.weight_pct

    if total != Decimal("100"):
        raise ValueError(f"basket weights must sum to 100, got {total}")
