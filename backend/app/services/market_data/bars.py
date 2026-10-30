"""



OHLCV bar retrieval with DB persistence, on-demand provider fetch, and Redis cache.



"""



from __future__ import annotations







from datetime import datetime, timedelta, timezone







from sqlalchemy import desc, select



from sqlalchemy.dialects.postgresql import insert



from sqlalchemy.ext.asyncio import AsyncSession







from app.core.config import settings



from app.core.logging import get_logger



from app.db.models import OHLCVBar



from app.schemas.schemas import OHLCVBarOut



from app.services.market_data.client import get_bars_resolved, get_market_data_client



from app.services.market_data.binance_spot import (

    CRYPTO_QUOTE_CACHE_TTL,

    get_crypto_bars,

    get_live_crypto_price,

    is_crypto_ticker,

)

from app.services.market_data.moex_spot import (

    get_live_moex_price,

    get_moex_bars,

    is_moex_ticker,

    normalize_moex_symbol,

    resolve_moex_ticker,

)



from app.utils.cache import cache_delete, cache_get, cache_set







logger = get_logger(__name__)


_DAILY_TIMEFRAMES = frozenset({"1d", "1D", "day", "1w", "1wk", "1W"})


def _one_bar_per_day(rows: list) -> list:
    """Keep one daily bar per calendar date (the later-stamped one). Input oldest first.

    Duplicate dates made every other daily return 0%: volatility halved, VaR understated
    and the chart change computed over half the intended window.
    """
    by_day: dict = {}
    for r in rows:
        ts = getattr(r, "timestamp", None)
        key = ts.date() if hasattr(ts, "date") else ts
        by_day[key] = r
    return [by_day[k] for k in sorted(by_day)]


def _chart_bars(out: list[OHLCVBarOut]) -> list[OHLCVBarOut]:
    """Drop missing/zero/NaN closes from chart payloads (bad DB rows); keep series if all bad."""
    good: list[OHLCVBarOut] = []
    for b in out:
        close = b.close
        if close is None:
            continue
        try:
            c = float(close)
        except (TypeError, ValueError):
            continue
        if c > 0 and c == c:  # NaN-safe
            good.append(b)
    res = good if good else out
    if res and getattr(res[0], "timeframe", "") in _DAILY_TIMEFRAMES:
        res = _one_bar_per_day(res)
    return res





_BARS_CACHE_TTL = 120         # equities daily — refresh every 2 min



_BARS_CACHE_TTL_CRYPTO = 5    # crypto bars cache max 5s; live price patched every request



_BARS_CACHE_TTL_INTRADAY = 30 # equities intraday







_MIN_BARS_BEFORE_FETCH = 20







# How far back to pull when fetching from the provider on demand. yfinance caps



# intraday history (1m ≤ 7d, 5m/15m/1h ≤ 60d), so keep windows within limits.



_LOOKBACK_DAYS = {



    "1m": 7,



    "5m": 55,



    "15m": 55,



    "1h": 55,



    "4h": 90,



    "1w": 400,



    "1wk": 400,



}











def _is_intraday(timeframe: str) -> bool:



    return timeframe not in {"1d", "1w", "1wk"}











def _cache_ttl(timeframe: str, ticker: str = "") -> int:



    if is_crypto_ticker(ticker):



        return _BARS_CACHE_TTL_CRYPTO



    return _BARS_CACHE_TTL_INTRADAY if _is_intraday(timeframe) else _BARS_CACHE_TTL











def _bars_cache_key(ticker: str, timeframe: str, limit: int) -> str:



    return f"bars:{ticker.upper()}:{timeframe}:{limit}"











async def _load_bars_from_db(



    db: AsyncSession,



    ticker: str,



    timeframe: str,



    limit: int,



) -> list[OHLCVBar]:



    daily = timeframe in _DAILY_TIMEFRAMES
    result = await db.execute(
        select(OHLCVBar)
        .where(OHLCVBar.ticker == ticker.upper(), OHLCVBar.timeframe == timeframe)
        .order_by(desc(OHLCVBar.timestamp))
        # Daily rows can be stored twice (00:00 UTC from one provider, 04:00 UTC from another).
        .limit(limit * 2 if daily else limit)
    )
    rows = list(reversed(result.scalars().all()))
    if daily:
        rows = _one_bar_per_day(rows)[-limit:]
    return rows











async def _persist_bars(



    db: AsyncSession,



    ticker: str,



    timeframe: str,



    bars: list[dict],



) -> None:



    if not bars:



        return







    if is_crypto_ticker(ticker):

        source = "binance"

    elif is_moex_ticker(ticker):

        source = "moex"

    else:

        source = settings.MARKET_DATA_PROVIDER.value







    for bar in bars:



        ts_raw = bar.get("timestamp")



        ts = (



            datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))



            if isinstance(ts_raw, str)



            else ts_raw



        )



        if ts.tzinfo is None:



            ts = ts.replace(tzinfo=timezone.utc)
        if timeframe in _DAILY_TIMEFRAMES:
            # One key per session: providers stamp the same day at 00:00 or 04:00 UTC.
            ts = ts.replace(hour=0, minute=0, second=0, microsecond=0)







        stmt = (



            insert(OHLCVBar)



            .values(



                ticker=ticker.upper(),



                timestamp=ts,



                timeframe=timeframe,



                open=bar["open"],



                high=bar["high"],



                low=bar["low"],



                close=bar["close"],



                volume=bar["volume"],



                vwap=bar.get("vwap"),



                trade_count=bar.get("trade_count"),



                source=source,



            )



            .on_conflict_do_nothing(constraint="uq_ohlcv_bar")



        )



        await db.execute(stmt)



    await db.commit()











async def _fetch_provider_bars(



    ticker: str,



    timeframe: str,



    limit: int,



) -> list[dict]:






    ticker = ticker.upper()







    if is_crypto_ticker(ticker):



        bars = await get_crypto_bars(ticker, timeframe, limit)



        if bars:



            return bars[-limit:]



    if await resolve_moex_ticker(ticker):

        bare = normalize_moex_symbol(ticker)

        bars = await get_moex_bars(bare, timeframe, limit)

        if bars:

            return bars[-limit:]



    end = datetime.now(timezone.utc)

    if timeframe == "1d":
        days_back = max(365, limit * 2)
    else:
        days_back = _LOOKBACK_DAYS.get(timeframe, 30)

    start = end - timedelta(days=days_back)

    from app.services.market_data.client import get_bars_resolved

    bars = await get_bars_resolved(ticker, timeframe, start, end)
    if not bars:
        return []

    return bars[-limit:]











async def _patch_live_moex_close(ticker: str, bars: list[OHLCVBarOut]) -> list[OHLCVBarOut]:

    """Sync the latest bar close with live MOEX spot so chart header matches quote."""

    if not bars or not is_moex_ticker(ticker):

        return bars



    live = await get_live_moex_price(ticker)

    if live is None or live <= 0:

        return bars



    last = bars[-1].model_copy(deep=True)

    last.close = live

    last.high = max(last.high, live)

    last.low = min(last.low, live)

    return [*bars[:-1], last]





async def _patch_live_crypto_close(ticker: str, bars: list[OHLCVBarOut]) -> list[OHLCVBarOut]:



    """Sync the latest bar close with Binance spot so chart header matches live price."""



    if not bars or not is_crypto_ticker(ticker):



        return bars







    live = await get_live_crypto_price(ticker)



    if live is None or live <= 0:



        return bars







    last = bars[-1].model_copy(deep=True)



    last.close = live



    last.high = max(last.high, live)



    last.low = min(last.low, live)



    return [*bars[:-1], last]











async def get_bars_for_chart(



    db: AsyncSession,



    ticker: str,



    timeframe: str = "1d",



    limit: int = 100,



    *,



    force_refresh: bool = False,



) -> list[OHLCVBarOut]:



    """Return OHLCV bars for charts — DB first, then provider with cache."""

    from app.services.market_data.binance_spot import normalize_crypto_ticker

    ticker = ticker.strip().upper()
    crypto_canonical = normalize_crypto_ticker(ticker)
    if crypto_canonical:
        ticker = crypto_canonical
    elif await resolve_moex_ticker(ticker):
        ticker = normalize_moex_symbol(ticker)



    cache_key = _bars_cache_key(ticker, timeframe, limit)







    if force_refresh:



        await cache_delete(cache_key)







    cached = await cache_get(cache_key)



    if cached:



        out = [OHLCVBarOut.model_validate(row) for row in cached]



        out = await _patch_live_crypto_close(ticker, out)

        return _chart_bars(await _patch_live_moex_close(ticker, out))







    ttl = _cache_ttl(timeframe, ticker)



    crypto = is_crypto_ticker(ticker)

    moex = await resolve_moex_ticker(ticker)







    # Intraday and crypto must feel live — always try to top up from provider.



    # Equities daily can serve straight from DB when sufficiently populated.



    db_bars = await _load_bars_from_db(db, ticker, timeframe, limit)



    if (



        not force_refresh



        and not _is_intraday(timeframe)



        and not crypto



        and not moex



        and len(db_bars) >= min(limit, _MIN_BARS_BEFORE_FETCH)



    ):



        out = [OHLCVBarOut.model_validate(b) for b in db_bars]



        await cache_set(cache_key, [row.model_dump() for row in out], ttl=ttl)



        return _chart_bars(out)







    if (



        force_refresh



        or _is_intraday(timeframe)



        or crypto



        or moex



        or len(db_bars) < min(limit, _MIN_BARS_BEFORE_FETCH)



    ):



        try:



            provider_bars = await _fetch_provider_bars(ticker, timeframe, limit)



            if provider_bars:



                await _persist_bars(db, ticker, timeframe, provider_bars)



                db_bars = await _load_bars_from_db(db, ticker, timeframe, limit)



        except Exception as exc:



            logger.warning("On-demand bar fetch failed", ticker=ticker, error=str(exc))







    out = [OHLCVBarOut.model_validate(b) for b in db_bars]



    out = await _patch_live_crypto_close(ticker, out)

    out = await _patch_live_moex_close(ticker, out)



    if out:



        await cache_set(cache_key, [row.model_dump() for row in out], ttl=ttl)



    return _chart_bars(out)









# Re-export for tests / callers that reference the crypto quote TTL.

CRYPTO_BARS_MAX_CACHE_TTL = CRYPTO_QUOTE_CACHE_TTL


