"""Equity-specific analytics ORM models (Prompt 10)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class EarningsCalendarORM(Base):
    __tablename__ = "earnings_calendar"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CorporateActionORM(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DividendEventORM(Base):
    __tablename__ = "dividend_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ex_dividend_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SplitHistoryORM(Base):
    __tablename__ = "split_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    split_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ratio: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SectorRotationScoreORM(Base):
    __tablename__ = "sector_rotation_score"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    sector: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketSessionProfileORM(Base):
    __tablename__ = "market_session_profile"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False)
    avg_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_volume_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volatility: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LiquidityFilterORM(Base):
    __tablename__ = "liquidity_filter"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    min_volume_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_volume_20d: Mapped[int] = mapped_column(Integer, nullable=False)
    passes_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VolatilityByRegimeORM(Base):
    __tablename__ = "volatility_by_regime"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)
    realized_vol: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class NewsImpactScoreORM(Base):
    __tablename__ = "news_impact_score"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nearest_event_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


__all__ = [
    "CorporateActionORM",
    "DividendEventORM",
    "EarningsCalendarORM",
    "LiquidityFilterORM",
    "MarketSessionProfileORM",
    "NewsImpactScoreORM",
    "SectorRotationScoreORM",
    "SplitHistoryORM",
    "VolatilityByRegimeORM",
]
