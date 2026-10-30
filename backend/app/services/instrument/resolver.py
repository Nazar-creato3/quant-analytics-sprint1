"""Resolve watchlist symbols to ``instruments`` rows, auto-creating when missing."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import AssetCategory, InstrumentSource, TradableUnit
from app.domain.instrument import InstrumentORM, default_instrument_type
from app.services.instrument.category import detect_ticker_category
from app.services.catalog import resolve as catalog_resolve

logger = get_logger(__name__)


def _infer_instrument(symbol: str) -> tuple[InstrumentSource, AssetCategory, dict]:
    info = detect_ticker_category(symbol)
    return info.source, info.category, info.to_metadata()


async def resolve_or_create_instrument(db: AsyncSession, symbol: str) -> InstrumentORM:
    """Find instrument by symbol or create a registry row for watchlist/pipeline use."""
    try:
        hit = catalog_resolve(symbol)
        sym = hit.symbol
    except (KeyError, ValueError):
        raw = symbol.strip().upper()
        if not raw:
            raise ValueError("symbol must not be blank")
        sym = raw
    if not sym:
        raise ValueError("symbol must not be blank")

    result = await db.execute(
        select(InstrumentORM)
        .where(InstrumentORM.symbol == sym)
        .order_by(InstrumentORM.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        source, category, category_meta = _infer_instrument(sym)
        existing.category = category.value
        existing.instrument_type = default_instrument_type(category)
        existing.metadata_ = {**(existing.metadata_ or {}), **category_meta}
        if existing.source != source.value:
            existing.source = source.value
        return existing

    source, category, category_meta = _infer_instrument(sym)
    instrument_type = default_instrument_type(category)
    row = InstrumentORM(
        symbol=sym,
        source=source.value,
        instrument_type=instrument_type,
        category=category.value,
        tradable_unit=TradableUnit.PER_SHARE.value,
        metadata_={"auto_created": True, "watchlist": True, **category_meta},
    )
    db.add(row)
    try:
        await db.flush()
        await db.refresh(row)
        logger.info("Auto-created instrument", symbol=sym, source=source.value)
        return row
    except Exception:
        await db.rollback()
        retry = await db.execute(
            select(InstrumentORM).where(InstrumentORM.symbol == sym).limit(1)
        )
        found = retry.scalar_one_or_none()
        if found is not None:
            return found
        raise


async def ensure_instruments_for_symbols(db: AsyncSession, symbols: list[str]) -> list[InstrumentORM]:
    """Ensure every symbol in the list has an instrument row."""
    rows: list[InstrumentORM] = []
    for raw in symbols:
        sym = raw.strip().upper()
        if not sym:
            continue
        rows.append(await resolve_or_create_instrument(db, sym))
    return rows
