"""Load daily price series for forecast engines — DB first, multi-provider fallback."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.market_data import MarketOhlcvORM
from app.services.market_data.binance_spot import (
    get_crypto_bars,
    is_crypto_ticker,
    normalize_crypto_ticker,
)
from app.services.market_data.bars import get_bars_for_chart
from app.services.market_data.client import YFinanceClient
from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

logger = get_logger(__name__)

MIN_FORECAST_BARS = 10
_DEFAULT_LIMIT = 120


def market_data_fetch_symbols(symbol: str) -> list[str]:
    """Ordered symbol variants to try when loading bars (SOL → SOL-USD, etc.)."""
    raw = symbol.strip().upper()
    if not raw:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        key = value.upper()
        if key and key not in seen:
            seen.add(key)
            candidates.append(key)

    crypto = normalize_crypto_ticker(raw)
    if crypto:
        add(crypto)
        add(raw)
        base = crypto[:-4]
        add(base)
        add(f"{base}USDT")
        return candidates

    if is_moex_ticker(raw):
        add(normalize_moex_symbol(raw))
        add(raw)
        return candidates

    from app.services.market_data.marketstack_catalog import resolve_marketstack_symbol

    ms = resolve_marketstack_symbol(raw)
    if ms:
        add(ms)
        add(raw)
        return candidates

    add(raw)
    return candidates


async def _load_from_ohlcv_table(
    db: AsyncSession,
    instrument_id: int,
    *,
    limit: int,
    as_of: datetime | None = None,
) -> tuple[list[float], list[float]]:
    filters = [
        MarketOhlcvORM.instrument_id == instrument_id,
        MarketOhlcvORM.timeframe == "1d",
    ]
    if as_of is not None:
        cutoff = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        filters.append(MarketOhlcvORM.time <= cutoff)
    stmt = (
        select(MarketOhlcvORM)
        .where(*filters)
        .order_by(MarketOhlcvORM.time.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    prices = [float(row.close) for row in rows if row.close is not None]
    volumes = [float(row.volume or 0) for row in rows]
    return prices, volumes


async def _persist_bars_to_ohlcv(
    db: AsyncSession,
    instrument_id: int,
    bars: list,
) -> None:
    if not bars:
        return

    for bar in bars:
        ts_raw = getattr(bar, "timestamp", None) or bar.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            ts = ts_raw
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        close = getattr(bar, "close", None) if not isinstance(bar, dict) else bar.get("close")
        if close is None:
            continue

        open_ = getattr(bar, "open", None) if not isinstance(bar, dict) else bar.get("open")
        high = getattr(bar, "high", None) if not isinstance(bar, dict) else bar.get("high")
        low = getattr(bar, "low", None) if not isinstance(bar, dict) else bar.get("low")
        volume = getattr(bar, "volume", None) if not isinstance(bar, dict) else bar.get("volume")

        stmt = (
            insert(MarketOhlcvORM)
            .values(
                time=ts,
                instrument_id=instrument_id,
                timeframe="1d",
                open=Decimal(str(open_)) if open_ is not None else None,
                high=Decimal(str(high)) if high is not None else None,
                low=Decimal(str(low)) if low is not None else None,
                close=Decimal(str(close)),
                volume=Decimal(str(volume or 0)),
            )
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.debug("OHLCV persist skipped", instrument_id=instrument_id, error=str(exc))


async def _fetch_provider_chain_bars(symbol: str, limit: int) -> list[dict]:
    """Equity/crypto bars via platform provider chain (Alpaca→…→yfinance / CoinGecko)."""
    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - 1)
    try:
        from app.services.market_data.client import get_bars_resolved

        bars = await get_bars_resolved(symbol, "1d", start, end)
        return bars[-limit:] if bars else []
    except Exception as exc:
        logger.debug("provider chain bars failed", symbol=symbol, error=str(exc))
        return []


async def _fetch_yfinance_bars(symbol: str, limit: int) -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - 1)
    try:
        bars = await YFinanceClient().get_bars(symbol, "1d", start, end)
        return bars[-limit:] if bars else []
    except Exception as exc:
        logger.debug("yfinance fallback failed", symbol=symbol, error=str(exc))
        return []


async def load_forecast_price_series(
    db: AsyncSession,
    instrument_id: int,
    symbol: str,
    *,
    limit: int = _DEFAULT_LIMIT,
    min_bars: int = MIN_FORECAST_BARS,
    persist: bool = True,
    as_of: datetime | None = None,
) -> tuple[list[float], list[float], str | None]:
    """Return (prices, volumes, data_source). data_source is None when DB-only."""
    prices, volumes = await _load_from_ohlcv_table(db, instrument_id, limit=limit, as_of=as_of)
    if len(prices) >= min_bars:
        return prices, volumes, None

    fetched_bars = None
    source: str | None = None

    for candidate in market_data_fetch_symbols(symbol):
        try:
            if is_crypto_ticker(candidate):
                raw = await get_crypto_bars(candidate, "1d", limit)
                if len(raw) >= min_bars:
                    prices = [float(bar["close"]) for bar in raw if bar.get("close")]
                    volumes = [float(bar.get("volume") or 0) for bar in raw]
                    fetched_bars = raw
                    source = "binance"
                    break

            chart_bars = await get_bars_for_chart(
                db,
                candidate,
                "1d",
                limit,
                force_refresh=len(prices) < min_bars,
            )
            if len(chart_bars) >= min_bars:
                prices = [float(bar.close) for bar in chart_bars if bar.close]
                volumes = [float(bar.volume or 0) for bar in chart_bars]
                fetched_bars = chart_bars
                source = "chart_cache"
                break
        except Exception as exc:
            logger.debug("Bar fetch candidate failed", symbol=candidate, error=str(exc))

    if len(prices) < min_bars:
        for candidate in market_data_fetch_symbols(symbol):
            raw = await _fetch_provider_chain_bars(candidate, limit)
            if len(raw) >= min_bars:
                prices = [float(bar["close"]) for bar in raw if bar.get("close")]
                volumes = [float(bar.get("volume") or 0) for bar in raw]
                fetched_bars = raw
                source = str(raw[-1].get("source") or "provider_chain") if raw else "provider_chain"
                break

    if len(prices) < min_bars:
        for candidate in market_data_fetch_symbols(symbol):
            if is_crypto_ticker(candidate):
                continue
            yf_symbol = candidate
            if normalize_crypto_ticker(candidate):
                yf_symbol = normalize_crypto_ticker(candidate) or candidate
            raw = await _fetch_yfinance_bars(yf_symbol, limit)
            if len(raw) >= min_bars:
                prices = [float(bar["close"]) for bar in raw if bar.get("close")]
                volumes = [float(bar.get("volume") or 0) for bar in raw]
                fetched_bars = raw
                source = "yfinance"
                break

    if persist and fetched_bars and len(prices) >= min_bars:
        await _persist_bars_to_ohlcv(db, instrument_id, fetched_bars)

    return prices, volumes, source
