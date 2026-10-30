"""Links between domain instruments and existing persistence layers."""
from __future__ import annotations

from app.domain.enums import InstrumentSource
from app.domain.instrument import InstrumentORM


def trade_venue_for_source(source: InstrumentSource) -> str:
    """Map domain instrument source to ``trades.venue`` values."""
    return source.value


def instrument_lookup_key(symbol: str, source: InstrumentSource) -> tuple[str, str]:
    """Natural key shared by ``instruments`` and ingestion upserts."""
    return symbol, source.value


def link_to_app_trade(symbol: str, venue: str) -> tuple[str, str]:
    """Resolve ``trades`` row via (symbol, venue) ↔ (symbol, source)."""
    return symbol, venue


def instrument_id_for_market_data(instrument: InstrumentORM) -> int:
    """Primary key used by ``market_trades`` and ``ohlcv`` FK constraints."""
    return instrument.id
