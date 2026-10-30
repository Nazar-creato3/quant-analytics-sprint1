"""Static sector/industry mapping seed for configured watchlist instruments."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.market_data import SectorMappingORM

# symbol (upper) -> (sector, industry); source resolved at seed time.
SECTOR_SEED: dict[str, tuple[str, str]] = {
    # Crypto (Binance)
    "BTCUSDT": ("digital_assets", "layer1"),
    "ETHUSDT": ("digital_assets", "layer1"),
    "SOL-USD": ("digital_assets", "layer1"),
    "SOL": ("digital_assets", "layer1"),
    "SOLUSDT": ("digital_assets", "layer1"),
    "BNBUSDT": ("digital_assets", "exchange_token"),
    "BTC-USD": ("digital_assets", "layer1"),
    "ETH-USD": ("digital_assets", "layer1"),
    "ETH": ("digital_assets", "layer1"),
    # MOEX
    "SBER": ("financials", "banks"),
    "GAZP": ("energy", "integrated_oil_gas"),
    "LKOH": ("energy", "integrated_oil_gas"),
    "GMKN": ("materials", "mining"),
    "YNDX": ("technology", "internet"),
    "ROSN": ("energy", "integrated_oil_gas"),
    "NVTK": ("energy", "exploration_production"),
    # US equities / ETFs
    "AAPL": ("technology", "consumer_electronics"),
    "MSFT": ("technology", "software"),
    "GOOGL": ("communication_services", "internet"),
    "AMZN": ("consumer_discretionary", "ecommerce"),
    "META": ("communication_services", "social_media"),
    "NVDA": ("technology", "semiconductors"),
    "SPY": ("indices", "us_large_cap"),
    "QQQ": ("indices", "us_tech"),
    "GLD": ("macro_hedge", "gold_etf"),
}


def sector_for_symbol(symbol: str) -> tuple[str, str] | None:
    normalized = symbol.strip().upper()
    return SECTOR_SEED.get(normalized)


async def seed_sector_mapping(session: AsyncSession) -> dict[str, Any]:
    """Ensure sector_mapping rows exist for known symbols in instruments registry."""
    from app.domain.instrument import InstrumentORM

    symbols = set(SECTOR_SEED.keys())
    symbols.update(s.upper() for s in settings.default_watchlist_list)

    result = await session.execute(select(InstrumentORM).where(InstrumentORM.symbol.in_(list(symbols))))
    instruments = result.scalars().all()

    seeded = 0
    for instrument in instruments:
        mapping = sector_for_symbol(instrument.symbol)
        if mapping is None:
            continue
        sector, industry = mapping
        stmt = (
            insert(SectorMappingORM)
            .values(instrument_id=instrument.id, sector=sector, industry=industry)
            .on_conflict_do_update(
                index_elements=["instrument_id"],
                set_={"sector": sector, "industry": industry},
            )
        )
        await session.execute(stmt)
        seeded += 1

    await session.commit()
    return {"seeded": seeded, "symbols_in_seed": len(SECTOR_SEED)}
