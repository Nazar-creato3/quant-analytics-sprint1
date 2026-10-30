"""Instrument domain entity — maps to the shared ``instruments`` registry table."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.domain.enums import AssetCategory, InstrumentSource, TradableUnit

# Legacy ``instrument_type`` values used by the realtime ingestion pipeline (0006).
_CATEGORY_TO_INSTRUMENT_TYPE: dict[AssetCategory, str] = {
    AssetCategory.EQUITIES: "stock",
    AssetCategory.ETF: "etf",
    AssetCategory.CRYPTO: "crypto",
    AssetCategory.FX: "fx",
    AssetCategory.COMMODITIES: "commodity",
    AssetCategory.RATES_BONDS: "bond",
    AssetCategory.INDICES: "index",
    AssetCategory.THEMATIC_BASKET: "basket",
    AssetCategory.SECTOR_BASKET: "basket",
    AssetCategory.MACRO_HEDGE: "hedge",
    AssetCategory.EVENT_DRIVEN_WATCHLIST: "watchlist",
    AssetCategory.INCOME_SLEEVE: "sleeve",
    AssetCategory.DEFENSIVE_SLEEVE: "sleeve",
    AssetCategory.SPECULATIVE_SLEEVE: "sleeve",
    AssetCategory.CUSTOM_USER_BASKET: "basket",
    AssetCategory.OTHER: "other",
}


def default_instrument_type(category: AssetCategory) -> str:
    return _CATEGORY_TO_INSTRUMENT_TYPE[category]


class InstrumentORM(Base):
    """ORM mapping for ``instruments`` (created in migration 0006, extended in 0007)."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_type: Mapped[str] = mapped_column(Text, nullable=False)
    figi: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tradable_unit: Mapped[str] = mapped_column(String(20), nullable=False, default=TradableUnit.PER_SHARE.value)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    market_trades = relationship("MarketTradeORM", back_populates="instrument")
    ohlcv_bars = relationship("MarketOhlcvORM", back_populates="instrument")
    order_book_snapshots = relationship("OrderBookSnapshotORM", back_populates="instrument")
    sector_mapping = relationship("SectorMappingORM", back_populates="instrument", uselist=False)
    factor_exposures = relationship("FactorExposureORM", back_populates="instrument")

    __table_args__ = (UniqueConstraint("symbol", "source", name="instruments_symbol_source_key"),)


class InstrumentBase(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    category: AssetCategory
    source: InstrumentSource
    tradable_unit: TradableUnit = TradableUnit.PER_SHARE
    metadata: dict[str, Any] = Field(default_factory=dict)
    figi: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class InstrumentCreate(InstrumentBase):
    instrument_type: str | None = None

    def resolved_instrument_type(self) -> str:
        if self.instrument_type:
            return self.instrument_type
        return default_instrument_type(self.category)


class InstrumentRead(InstrumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_type: str
    created_at: datetime | None = None

    @classmethod
    def from_orm_row(cls, row: InstrumentORM) -> InstrumentRead:
        return cls(
            id=row.id,
            symbol=row.symbol,
            category=AssetCategory(row.category) if row.category else AssetCategory.EQUITIES,
            source=InstrumentSource(row.source),
            tradable_unit=TradableUnit(row.tradable_unit),
            metadata=row.metadata_ or {},
            figi=row.figi,
            instrument_type=row.instrument_type,
            created_at=row.created_at,
        )
