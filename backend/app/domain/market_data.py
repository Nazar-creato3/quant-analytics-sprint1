"""ORM mappings for realtime market data tables (migrations 0006, 0016)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class MarketTradeORM(Base):
    """Exchange tick stored in ``market_trades`` (not app ``trades``)."""

    __tablename__ = "market_trades"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id"),
        primary_key=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    side: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    instrument = relationship("InstrumentORM", back_populates="market_trades")


class MarketOhlcvORM(Base):
    """OHLCV bar in Timescale ``ohlcv`` hypertable."""

    __tablename__ = "ohlcv"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id"),
        primary_key=True,
    )
    timeframe: Mapped[str] = mapped_column(Text, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    instrument = relationship("InstrumentORM", back_populates="ohlcv_bars")


class OrderBookSnapshotORM(Base):
    """Top-of-book / depth snapshot (Timescale ``order_book_snapshots``)."""

    __tablename__ = "order_book_snapshots"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id"),
        primary_key=True,
    )
    bid_depth: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    ask_depth: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    spread_bps: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    instrument = relationship("InstrumentORM", back_populates="order_book_snapshots")


class MacroIndicatorORM(Base):
    """Published macro series point (FRED, CBR, etc.)."""

    __tablename__ = "macro_indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator_code: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "indicator_code",
            "published_at",
            "source",
            name="macro_indicators_indicator_code_published_at_source_key",
        ),
    )


class SectorMappingORM(Base):
    """Static sector/industry reference for an instrument."""

    __tablename__ = "sector_mapping"

    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sector: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str] = mapped_column(Text, nullable=False, default="")

    instrument = relationship("InstrumentORM", back_populates="sector_mapping")


class FactorExposureORM(Base):
    """Rolling multi-factor beta estimates per instrument (Prompt 19)."""

    __tablename__ = "factor_exposure"

    instrument_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    factor_name: Mapped[str] = mapped_column(Text, primary_key=True)
    beta: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    r_squared_of_model: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    instrument = relationship("InstrumentORM", back_populates="factor_exposures")
