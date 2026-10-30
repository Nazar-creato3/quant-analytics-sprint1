"""Parallel I/O helpers for the market-intelligence pipeline."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)

# Lower concurrency avoids tripping shared API quotas on VPS.
_BAR_FETCH_CONCURRENCY = 6
# One slow provider must not hold the whole analysis: a ticker gets this long, then is skipped.
_BAR_FETCH_TICKER_TIMEOUT_SEC = 20.0
_MIN_DB_BARS = 60


def daily_bar_is_stale(last_ts: Any, *, now: datetime | None = None) -> bool:
    """True when the last daily bar is more than one weekday behind the expected session."""
    from datetime import timezone as tz

    if last_ts is None:
        return False
    now_dt = now or datetime.now(tz.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=tz.utc)

    last_date: date | None = None
    if isinstance(last_ts, datetime):
        last_date = last_ts.date()
    elif isinstance(last_ts, date):
        last_date = last_ts
    else:
        aware = last_ts
        tzinfo = getattr(aware, "tzinfo", None)
        if tzinfo is None and hasattr(aware, "replace"):
            try:
                aware = aware.replace(tzinfo=tz.utc)
            except TypeError:
                aware = last_ts
        if hasattr(aware, "date") and callable(aware.date):
            try:
                maybe = aware.date()
                if isinstance(maybe, date):
                    last_date = maybe
            except TypeError:
                last_date = None
    if last_date is None:
        return True

    def _prev_weekday(d: date) -> date:
        step = d
        while step.weekday() >= 5:
            step -= timedelta(days=1)
        return step

    expected = _prev_weekday(now_dt.date())
    # Before US cash close, yesterday's session is still the latest complete bar.
    if now_dt.hour < 21:
        expected = _prev_weekday(expected - timedelta(days=1))
    lag_days = (expected - last_date).days
    return lag_days > 1


def _bars_to_dataframe(bars: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


async def _load_bars_from_db(ticker: str, bar_limit: int) -> tuple[list[dict[str, Any]] | None, bool]:
    """Cached OHLCV from Postgres when enough history is stored. Returns (bars, stale)."""
    from app.db.session import AsyncSessionLocal
    from app.services.market_data.bars import get_bars_for_chart

    async with AsyncSessionLocal() as db:
        try:
            chart_bars = await get_bars_for_chart(
                db,
                ticker,
                "1d",
                bar_limit,
                force_refresh=False,
            )
        except Exception as exc:
            logger.debug("Pipeline DB bars load failed", ticker=ticker, error=str(exc))
            return None, False

    if len(chart_bars) < _MIN_DB_BARS:
        return None, False

    stale = False
    last_ts = getattr(chart_bars[-1], "timestamp", None)
    if last_ts is not None:
        try:
            if daily_bar_is_stale(last_ts):
                logger.info("Pipeline DB bars stale, refetch", ticker=ticker, last=str(last_ts)[:19])
                stale = True
        except Exception:
            pass

    out: list[dict[str, Any]] = []
    for bar in chart_bars:
        row = bar.model_dump()
        ts = row.get("timestamp")
        if hasattr(ts, "isoformat"):
            row["timestamp"] = ts.isoformat()
        out.append(row)
    if not stale:
        logger.debug("Pipeline bars from DB", ticker=ticker, bars=len(out))
    return out, stale


async def fetch_watchlist_bars_parallel(
    watchlist: list[str],
    start: datetime,
    end: datetime,
    *,
    bar_limit: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, list[dict]]]:
    """Fetch OHLCV for all tickers concurrently. Returns (dataframes, raw bars)."""
    from app.services.market_data.client import get_bars_resolved

    market_data: dict[str, pd.DataFrame] = {}
    raw_bars_by_ticker: dict[str, list[dict]] = {}
    sem = asyncio.Semaphore(_BAR_FETCH_CONCURRENCY)
    skip_keyed_providers = False
    rate_limit_seen: list[bool] = [False]

    async def _remote(ticker: str) -> list[dict] | None:
        nonlocal skip_keyed_providers
        bars = await get_bars_resolved(
            ticker,
            "1d",
            start,
            end,
            crypto_limit=bar_limit,
            moex_limit=bar_limit,
            skip_keyed_providers=skip_keyed_providers,
            rate_limit_seen=rate_limit_seen,
        )
        if rate_limit_seen[0]:
            skip_keyed_providers = True
        return bars

    async def _work(ticker: str) -> None:
        db_bars, stale = await _load_bars_from_db(ticker, bar_limit)
        if db_bars and not stale:
            raw_bars_by_ticker[ticker] = db_bars
            market_data[ticker] = _bars_to_dataframe(db_bars)
            return
        bars: list[dict] | None = None
        try:
            bars = await asyncio.wait_for(_remote(ticker), timeout=_BAR_FETCH_TICKER_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning("Pipeline bars fetch timed out", ticker=ticker, timeout_sec=_BAR_FETCH_TICKER_TIMEOUT_SEC)
        except Exception as exc:
            logger.warning("Pipeline bars fetch failed", ticker=ticker, error=str(exc)[:200])
        if not bars and db_bars:
            # A provider outage must not drop the ticker: older history is still valid for scoring.
            logger.info("Pipeline using stale DB bars", ticker=ticker, bars=len(db_bars))
            bars = db_bars
        if not bars:
            return
        raw_bars_by_ticker[ticker] = bars
        market_data[ticker] = _bars_to_dataframe(bars)

    async def _one(ticker: str) -> None:
        async with sem:
            try:
                # Hard cap per ticker, DB read included: one stuck call must not hold the analysis.
                await asyncio.wait_for(_work(ticker), timeout=_BAR_FETCH_TICKER_TIMEOUT_SEC + 10)
            except asyncio.TimeoutError:
                logger.warning("Pipeline ticker skipped: over time budget", ticker=ticker)
            except Exception as exc:
                logger.warning("Pipeline ticker skipped", ticker=ticker, error=str(exc)[:200])

    await asyncio.gather(*[_one(t) for t in watchlist])
    return market_data, raw_bars_by_ticker
