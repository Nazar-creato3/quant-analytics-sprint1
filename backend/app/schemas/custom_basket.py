"""API schemas for CustomBasket CRUD."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CustomBasketItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    basket_id: str
    instrument_id: int
    weight_pct: Decimal
    created_at: datetime
    updated_at: datetime


class CustomBasketItemIn(BaseModel):
    instrument_id: int = Field(gt=0, description="Instrument registry id")
    weight_pct: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Allocation weight within the basket (must sum to 100%)",
    )


class CustomBasketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_id: str
    name: str
    description: str | None
    sleeve_id: str | None = Field(
        default=None,
        description="Optional sleeve context for analytics; does not replace sleeve allocation",
    )
    items: list[CustomBasketItemOut]
    created_at: datetime
    updated_at: datetime


class CustomBasketCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    sleeve_id: str | None = None
    items: list[CustomBasketItemIn] = Field(
        min_length=1,
        description="Weighted composition; each instrument executes via its own DealIntent",
    )


class CustomBasketUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    sleeve_id: str | None = None
    items: list[CustomBasketItemIn] | None = Field(
        default=None,
        min_length=1,
        description="Replace full basket composition",
    )
