"""Direct Deals support endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user_email, get_db
from app.domain.instrument import InstrumentORM
from app.services.instrument.category import enrich_watchlist_entry
from app.services.market_data.moex_currency import list_moex_currency_instruments
from app.services.market_data.universe_search import search_universe
from app.services.settings.watchlist import get_effective_watchlist
from app.services.execution.capability import symbol_execution_hint
from app.services.execution.symbol_mapping import is_tokenized_equity

router = APIRouter(prefix="/direct-deals", tags=["direct-deals"])


class DirectDealsSymbolOut(BaseModel):
    symbol: str = Field(..., min_length=1)
    name: str | None = None
    asset_class: str
    exchange: str
    source: str
    tradable_unit: str = "per_share"
    bybit_tokenized: bool = False
    bybit_tokenized_available: bool | None = None
    unavailable_reason_ru: str | None = None
    execution_available_globally: bool | None = None
    execution_hint_ru: str | None = None
    required_provider_ru: str | None = None


_VENUE_SEED_UNIVERSE: tuple[dict[str, str], ...] = (
    # Crypto spot pairs routed through the Binance/CCXT data path.
    {"symbol": "BTCUSDT", "name": "Bitcoin / Tether", "exchange": "BINANCE"},
    {"symbol": "ETHUSDT", "name": "Ethereum / Tether", "exchange": "BINANCE"},
    {"symbol": "SOLUSDT", "name": "Solana / Tether", "exchange": "BINANCE"},
    {"symbol": "BNBUSDT", "name": "BNB / Tether", "exchange": "BINANCE"},
    {"symbol": "XRPUSDT", "name": "XRP / Tether", "exchange": "BINANCE"},
    {"symbol": "ADAUSDT", "name": "Cardano / Tether", "exchange": "BINANCE"},
    {"symbol": "DOGEUSDT", "name": "Dogecoin / Tether", "exchange": "BINANCE"},
    # Liquid ETFs and resource/energy equities covered by existing quote providers.
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "exchange": "US"},
    {"symbol": "QQQ", "name": "Invesco QQQ ETF", "exchange": "US"},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "exchange": "US"},
    {"symbol": "XLE", "name": "Energy Select Sector SPDR", "exchange": "US"},
    {"symbol": "XME", "name": "SPDR Metals & Mining ETF", "exchange": "US"},
    {"symbol": "USO", "name": "United States Oil Fund", "exchange": "US"},
    {"symbol": "AAPL", "name": "Apple", "exchange": "US"},
    {"symbol": "MSFT", "name": "Microsoft", "exchange": "US"},
    {"symbol": "NVDA", "name": "NVIDIA", "exchange": "US"},
    {"symbol": "TSLA", "name": "Tesla", "exchange": "US"},
    {"symbol": "XOM", "name": "Exxon Mobil", "exchange": "US"},
    {"symbol": "CVX", "name": "Chevron", "exchange": "US"},
    {"symbol": "COP", "name": "ConocoPhillips", "exchange": "US"},
    {"symbol": "FCX", "name": "Freeport-McMoRan", "exchange": "US"},
    {"symbol": "NEM", "name": "Newmont", "exchange": "US"},
    {"symbol": "GOLD", "name": "Barrick Gold", "exchange": "US"},
    {"symbol": "SBER", "name": "Sberbank", "exchange": "MOEX"},
    {"symbol": "GAZP", "name": "Gazprom", "exchange": "MOEX"},
    {"symbol": "LKOH", "name": "Lukoil", "exchange": "MOEX"},
    {"symbol": "GMKN", "name": "Nornickel", "exchange": "MOEX"},
    {"symbol": "NVTK", "name": "Novatek", "exchange": "MOEX"},
    {"symbol": "ROSN", "name": "Rosneft", "exchange": "MOEX"},
) + tuple(
    {"symbol": fx["symbol"], "name": fx["name"], "exchange": fx["exchange"]}
    for fx in list_moex_currency_instruments()
)

_SEEDED_ETF_SYMBOLS = {"XLE", "XME", "USO"}


def _symbol_name(symbol: str, metadata: dict[str, Any], fallback: str | None = None) -> str | None:
    for key in ("name", "short_name", "display_name", "description"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback or metadata.get("category_label")


def _upsert_symbol(
    symbols: dict[str, DirectDealsSymbolOut],
    *,
    symbol: str,
    name: str | None = None,
    exchange: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    tradable_unit: str = "per_share",
    execution_hint: dict[str, str | bool | None] | None = None,
) -> None:
    raw = symbol.strip().upper()
    if not raw:
        return
    meta = dict(metadata or {})
    if raw in _SEEDED_ETF_SYMBOLS or (name and "ETF" in name.upper()):
        meta.setdefault("instrument_type", "etf")
    existing = symbols.get(raw)
    enriched = enrich_watchlist_entry(raw, meta)
    asset_class = str(enriched.get("category") or "other")
    if existing and asset_class == "other":
        asset_class = existing.asset_class
    detected_exchange = (
        exchange
        or str(meta.get("exchange") or "")
        or (existing.exchange if existing else None)
    ) or str(enriched.get("market") or source or "market")
    bybit_tok = is_tokenized_equity(raw)
    hint = execution_hint or {}
    exec_global = hint.get("execution_available_globally")
    exec_hint_ru = hint.get("execution_hint_ru")
    required_provider = hint.get("required_provider_ru")
    bybit_avail = bool(exec_global) if bybit_tok and exec_global is not None else None
    unavail = str(exec_hint_ru) if exec_hint_ru and bybit_tok else None
    symbols[raw] = DirectDealsSymbolOut(
        symbol=raw,
        name=_symbol_name(raw, meta, name) or (existing.name if existing else None),
        asset_class=asset_class,
        exchange=detected_exchange.upper(),
        source=(source or (existing.source if existing else None) or detected_exchange).lower(),
        tradable_unit=tradable_unit or (existing.tradable_unit if existing else "per_share"),
        bybit_tokenized=bybit_tok,
        bybit_tokenized_available=bybit_avail,
        unavailable_reason_ru=unavail,
        execution_available_globally=bool(exec_global) if exec_global is not None else None,
        execution_hint_ru=str(exec_hint_ru) if exec_hint_ru else None,
        required_provider_ru=str(required_provider) if required_provider else None,
    )


async def _apply_execution_hints(symbols: dict[str, DirectDealsSymbolOut]) -> None:
    for raw, item in list(symbols.items()):
        hint = await symbol_execution_hint(raw)
        exec_global = hint.get("execution_available_globally")
        exec_hint_ru = hint.get("execution_hint_ru")
        required_provider = hint.get("required_provider_ru")
        bybit_tok = is_tokenized_equity(raw)
        symbols[raw] = item.model_copy(
            update={
                "execution_available_globally": bool(exec_global) if exec_global is not None else None,
                "execution_hint_ru": str(exec_hint_ru) if exec_hint_ru else None,
                "required_provider_ru": str(required_provider) if required_provider else None,
                "bybit_tokenized": bybit_tok,
                "bybit_tokenized_available": bool(exec_global) if bybit_tok and exec_global is not None else None,
                "unavailable_reason_ru": str(exec_hint_ru) if exec_hint_ru and bybit_tok else None,
            }
        )


@router.get("/symbols", response_model=list[DirectDealsSymbolOut])
async def list_direct_deals_symbols(
    q: str | None = Query(None, description="Optional symbol/name substring filter"),
    limit: int = Query(250, ge=1, le=1000),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[DirectDealsSymbolOut]:
    """Searchable universe for Direct Deals. Query hits Marketstack + MOEX + catalogs, not just watchlist."""
    symbols: dict[str, DirectDealsSymbolOut] = {}

    for seed in _VENUE_SEED_UNIVERSE:
        _upsert_symbol(symbols, **seed)

    for symbol in settings.default_watchlist_list:
        _upsert_symbol(symbols, symbol=symbol)

    for symbol in await get_effective_watchlist(db, email):
        _upsert_symbol(symbols, symbol=symbol)

    needle = (q or "").strip()
    if needle:
        try:
            hits = await search_universe(
                needle, limit=min(limit, 50), pinned_symbols=list(symbols.keys())
            )
        except Exception:
            hits = []
        for hit in hits:
            _upsert_symbol(
                symbols,
                symbol=hit.symbol,
                name=hit.name,
                exchange=hit.exchange,
                source=hit.source,
                metadata={"name": hit.name, "exchange": hit.exchange, "instrument_type": hit.category},
            )

    result = await db.execute(
        select(InstrumentORM).order_by(InstrumentORM.symbol.asc()).limit(1000)
    )
    for row in result.scalars().all():
        _upsert_symbol(
            symbols,
            symbol=row.symbol,
            exchange=(row.metadata_ or {}).get("exchange") or row.source,
            source=row.source,
            metadata={
                **(row.metadata_ or {}),
                "instrument_type": row.instrument_type,
            },
            tradable_unit=row.tradable_unit,
        )

    await _apply_execution_hints(symbols)

    needle = (q or "").strip().upper()
    rows = sorted(symbols.values(), key=lambda item: (item.exchange, item.asset_class, item.symbol))
    if needle:
        rows = [
            item
            for item in rows
            if needle in item.symbol.upper() or (item.name and needle in item.name.upper())
        ]
    return rows[:limit]
