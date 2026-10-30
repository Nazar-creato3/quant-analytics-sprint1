"""Unit tests for Instrument domain entity."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.enums import AssetCategory, InstrumentSource, TradableUnit
from app.domain.instrument import InstrumentCreate, InstrumentRead, InstrumentORM, default_instrument_type
from app.domain.links import instrument_lookup_key, link_to_app_trade, trade_venue_for_source


class TestInstrumentCreate:
    def test_create_minimal(self):
        inst = InstrumentCreate(
            symbol="BTCUSDT",
            category=AssetCategory.CRYPTO,
            source=InstrumentSource.BINANCE,
        )
        assert inst.symbol == "BTCUSDT"
        assert inst.tradable_unit == TradableUnit.PER_SHARE
        assert inst.metadata == {}

    def test_create_with_metadata(self):
        inst = InstrumentCreate(
            symbol="AAPL",
            category=AssetCategory.EQUITIES,
            source=InstrumentSource.FINAM,
            metadata={"exchange": "NASDAQ", "lot_size": 1},
            figi="BBG000B9XRY4",
        )
        assert inst.metadata["exchange"] == "NASDAQ"
        assert inst.figi == "BBG000B9XRY4"

    def test_resolved_instrument_type_from_category(self):
        inst = InstrumentCreate(
            symbol="ETHUSDT",
            category=AssetCategory.CRYPTO,
            source=InstrumentSource.BINANCE,
        )
        assert inst.resolved_instrument_type() == "crypto"
        assert default_instrument_type(AssetCategory.ETF) == "etf"

    def test_explicit_instrument_type_override(self):
        inst = InstrumentCreate(
            symbol="TEST",
            category=AssetCategory.EQUITIES,
            source=InstrumentSource.MOEX,
            instrument_type="preferred",
        )
        assert inst.resolved_instrument_type() == "preferred"

    def test_rejects_blank_symbol(self):
        with pytest.raises(ValidationError):
            InstrumentCreate(
                symbol="  ",
                category=AssetCategory.FX,
                source=InstrumentSource.FINAM,
            )

    def test_rejects_invalid_source(self):
        with pytest.raises(ValidationError):
            InstrumentCreate(
                symbol="EURUSD",
                category=AssetCategory.FX,
                source="yahoo",  # type: ignore[arg-type]
            )


class TestInstrumentRead:
    def test_from_orm_row(self):
        row = InstrumentORM(
            id=42,
            symbol="GAZP",
            source="moex",
            instrument_type="stock",
            category="equities",
            tradable_unit="per_share",
            metadata_={"board": "TQBR"},
        )
        read = InstrumentRead.from_orm_row(row)
        assert read.id == 42
        assert read.category == AssetCategory.EQUITIES
        assert read.source == InstrumentSource.MOEX
        assert read.metadata["board"] == "TQBR"


class TestInstrumentLinks:
    def test_lookup_key_matches_ingestion(self):
        assert instrument_lookup_key("SBER", InstrumentSource.TINKOFF) == ("SBER", "tinkoff")

    def test_trade_venue_mapping(self):
        assert trade_venue_for_source(InstrumentSource.BINANCE) == "binance"

    def test_link_to_app_trade(self):
        symbol, venue = link_to_app_trade("BTCUSDT", "binance")
        assert symbol == "BTCUSDT"
        assert venue == "binance"
