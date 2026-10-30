"""
MOEX / Russian equities market data helpers.

Symbol normalization:
  SBER, SBER.ME  -> bare MOEX ticker SBER
  Data sources (paper mode, no live keys):
    1. MOEX ISS public API with TQBR board (primary)
    2. yfinance with .ME suffix (fallback)
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# Board-scoped candles — bare /securities/{t}/candles often returns empty.
MOEX_CANDLES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
)
MOEX_CANDLES_URL_FALLBACK = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
)
MOEX_SECURITIES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
)

MOEX_QUOTE_CACHE_TTL = 15
_QUOTE_CACHE_PREFIX = "quote:moex:"
_MOEX_RESOLVE_CACHE_PREFIX = "moex:resolve:"

# Known MOEX equities + liquid ETFs / exchange names + indices.
_MOEX_SYMBOLS = frozenset(
    {
        "SBER", "GAZP", "LKOH", "GMKN", "YNDX", "ROSN", "NVTK", "MTSS", "MGNT", "PLZL",
        "TCSG", "MOEX", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "TATN", "SNGS", "SNGSP",
        "IRAO", "HYDR", "FEES", "RTKM", "AFKS", "PHOR", "PIKK", "FIVE", "OZON", "VKCO",
        "SBERP", "TRNFP", "MSNG", "UPRO", "AFLT", "RUAL", "POLY", "FIXP", "HHRU", "GLTR",
        # Popular TQBR ETFs / funds
        "SBMX", "FXUS", "FXGD", "FXCN", "FXDE", "FXRU", "FXRB", "TMOS", "EQMX", "SBSP",
        "AKME", "AKSP", "AKMB", "DIVD", "GROD", "TECH", "BOND", "TBRU", "TRUR",
        # MOEX indices (ISS index market)
        "IMOEX", "RTSI",
        # Current tickers after 2024–2025 renames (YNDX→YDEX, FIVE→X5, HHRU→HEAD) and liquid names.
        "YDEX", "X5", "HEAD", "LQDT", "SBMM", "SVCB", "ASTR", "MTLR", "SMLT", "SFIN", "POSI", "WUSH", "MDMG", "LENT", "BSPB", "CBOM", "ENPG", "UGLD", "SELG", "RENI", "DELI", "MSRS", "CNRU", "IVAT", "SOFL", "DIAS", "DATA", "GECO", "OZPH", "KZOS", "TRMK", "RASP", "FLOT", "NMTP", "LSRG", "BELU", "AQUA", "MVID", "SGZH",
    }
)

# US mega-caps that must never be treated as MOEX SECID collisions.
_US_BLOCKLIST = frozenset(
    {
        "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ",
        "IVV", "VOO", "IWM", "DIA", "AMD", "INTC", "NFLX", "DIS", "JPM", "BAC", "XOM",
        "CVX", "WMT", "V", "MA", "UNH", "HD", "COST", "AVGO", "ORCL", "CRM", "ADBE",
        "PYPL", "UBER", "COIN", "SQ", "SHOP", "BABA", "NIO", "PLTR", "SOFI", "HOOD",
    }
)


def normalize_moex_symbol(ticker: str) -> str:
    """Deprecated wrapper: Prompt 03 catalog.resolve (bare MOEX / strip .ME)."""
    from app.services.catalog import resolve

    try:
        hit = resolve(ticker)
        if hit.venue == "MOEX" and hit.instrument_kind == "equity":
            return hit.symbol
    except (KeyError, ValueError):
        pass
    t = ticker.strip().upper()
    if t.endswith(".ME"):
        return t[:-3]
    return t


_CRYPTO_ALIASES = {"ETHEREUM": "ETH-USD", "BITCOIN": "BTC-USD"}


def normalize_watchlist_ticker(ticker: str) -> str:
    """Normalize user-entered tickers for watchlist/registry (SBER.ME -> SBER)."""
    t = ticker.strip().upper()
    if not t:
        return t
    t = _CRYPTO_ALIASES.get(t, t)
    from app.services.market_data.moex_currency import (
        is_moex_currency_ticker,
        normalize_moex_currency_symbol,
    )

    if is_moex_currency_ticker(t):
        return normalize_moex_currency_symbol(t)
    if is_moex_ticker(t):
        return normalize_moex_symbol(t)
    return t


def is_moex_ticker(ticker: str) -> bool:
    """True for known MOEX symbols or explicit .ME suffix."""
    t = ticker.strip().upper()
    if t.endswith(".ME"):
        return True
    bare = normalize_moex_symbol(t)
    if bare in _US_BLOCKLIST:
        return False
    return bare in _MOEX_SYMBOLS


async def resolve_moex_ticker(ticker: str) -> bool:
    """True if ticker is MOEX (whitelist) or ISS returns a TQBR board row."""
    if is_moex_ticker(ticker):
        return True
    bare = normalize_moex_symbol(ticker)
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,11}", bare) or bare in _US_BLOCKLIST:
        return False

    cache_key = f"{_MOEX_RESOLVE_CACHE_PREFIX}{bare}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return bool(cached.get("is_moex"))

    quote = await _fetch_moex_iss_quote(bare)
    is_moex = quote is not None and quote.get("price") is not None
    await cache_set(cache_key, {"is_moex": is_moex}, ttl=3600)
    return is_moex


def to_yfinance_symbol(ticker: str) -> str:
    """Map MOEX ticker to Yahoo Finance symbol."""
    return f"{normalize_moex_symbol(ticker)}.ME"


def quote_cache_key(ticker: str) -> str:
    return f"{_QUOTE_CACHE_PREFIX}{normalize_moex_symbol(ticker)}"


async def _fetch_moex_iss_quote(ticker: str) -> dict[str, Any] | None:
    """Fetch latest quote from MOEX ISS marketdata endpoint."""
    bare = normalize_moex_symbol(ticker)
    url = MOEX_SECURITIES_URL.format(ticker=bare)
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
            resp = await client.get(url, params={"iss.meta": "off"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("MOEX ISS quote failed", ticker=bare, error=str(exc))
        return None

    marketdata = data.get("marketdata", {})
    columns = marketdata.get("columns", [])
    rows = marketdata.get("data", [])
    if not rows:
        return None

    def _row_price(row: list[Any]) -> float | None:
        record = dict(zip(columns, row))
        last = record.get("LAST") or record.get("LCURRENTPRICE") or record.get("MARKETPRICE")
        if last is None:
            return None
        price = float(last)
        return price if price > 0 else None

    # Prefer TQBR (main MOEX equity board); ISS returns multiple boards per ticker.
    selected: dict[str, Any] | None = None
    selected_price: float | None = None
    for row in rows:
        record = dict(zip(columns, row))
        if record.get("BOARDID") == "TQBR":
            price = _row_price(row)
            if price is not None:
                selected = record
                selected_price = price
                break

    if selected is None:
        for row in rows:
            price = _row_price(row)
            if price is not None:
                selected = dict(zip(columns, row))
                selected_price = price
                break

    if selected is None or selected_price is None:
        securities = data.get("securities", {})
        sec_columns = securities.get("columns", [])
        for sec_row in securities.get("data", []):
            sec = dict(zip(sec_columns, sec_row))
            if sec.get("BOARDID") not in {None, "TQBR"}:
                continue
            prev = sec.get("PREVPRICE") or sec.get("PREVLEGALCLOSEPRICE")
            if prev is None:
                continue
            price = float(prev)
            if price <= 0:
                continue
            selected = {"BOARDID": sec.get("BOARDID"), "VOLTODAY": 0, "LASTTOPREVPRICE": None}
            selected_price = price
            break

    if selected is None or selected_price is None:
        return None

    bid = selected.get("BID")
    ask = selected.get("OFFER")
    change_pct = selected.get("LASTTOPREVPRICE")

    return {
        "ticker": bare,
        "price": selected_price,
        "bid": float(bid) if bid else None,
        "ask": float(ask) if ask else None,
        "volume": float(selected.get("VOLTODAY") or 0),
        "change_pct": float(change_pct) if change_pct is not None else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "moex_iss",
        "exchange": "MOEX",
        "board": selected.get("BOARDID"),
    }


async def _fetch_yfinance_quote(ticker: str) -> dict[str, Any] | None:
    """Fetch quote via yfinance .ME suffix."""
    from app.services.market_data.client import YFinanceClient

    yf_symbol = to_yfinance_symbol(ticker)
    client = YFinanceClient()
    try:
        quote = await client.get_latest_quote(yf_symbol)
    except Exception as exc:
        logger.debug("yfinance MOEX quote failed", ticker=yf_symbol, error=str(exc))
        return None

    if not quote or quote.get("price") is None:
        return None

    # fast_info alone is often stale/wrong for MOEX .ME tickers; require recent bars.
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=10)
    try:
        bars = await client.get_bars(yf_symbol, "1d", start, end)
    except Exception as exc:
        logger.debug("yfinance MOEX quote validation failed", ticker=yf_symbol, error=str(exc))
        return None

    if not bars:
        logger.debug("yfinance MOEX quote rejected — no recent bars", ticker=yf_symbol)
        return None

    price = float(quote["price"])
    last_close = float(bars[-1]["close"])
    if last_close > 0 and abs(price - last_close) / last_close > 0.25:
        logger.debug(
            "yfinance MOEX quote rejected — price diverges from last bar",
            ticker=yf_symbol,
            price=price,
            last_close=last_close,
        )
        return None

    bare = normalize_moex_symbol(ticker)
    out = dict(quote)
    out["ticker"] = bare
    out["price"] = price
    out["source"] = "yfinance"
    out["exchange"] = "MOEX"
    out["yfinance_symbol"] = yf_symbol
    return out


async def get_moex_quote(ticker: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
    """Return normalized live quote for a MOEX ticker (ISS index / equity → yfinance)."""
    bare = normalize_moex_symbol(ticker)
    from app.services.market_data.moex_iss_provider import fetch_moex_index_quote, is_moex_index

    if is_moex_index(bare):
        index_q = await fetch_moex_index_quote(bare)
        if index_q:
            return index_q

    if not await resolve_moex_ticker(ticker):
        return None
    cache_key = quote_cache_key(bare)

    if not force_refresh:
        cached = await cache_get(cache_key)
        if cached and cached.get("price") is not None:
            cached = dict(cached)
            cached.setdefault("source", "moex_cached")
            return cached

    quote = await _fetch_moex_iss_quote(ticker)
    if quote is None:
        quote = await _fetch_yfinance_quote(ticker)

    if quote and quote.get("price") is not None:
        await cache_set(cache_key, quote, ttl=MOEX_QUOTE_CACHE_TTL)
    return quote


async def get_live_moex_price(ticker: str, *, force_refresh: bool = False) -> float | None:
    quote = await get_moex_quote(ticker, force_refresh=force_refresh)
    if quote and quote.get("price"):
        return float(quote["price"])
    return None


def _moex_interval_param(timeframe: str) -> str:
    """MOEX ISS candle interval codes."""
    return {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "60",
        "1d": "24",
    }.get(timeframe, "24")


_ISS_PAGE_SIZE = 500
_ISS_MAX_PAGES = 12


async def _fetch_moex_iss_bars(
    ticker: str,
    timeframe: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candles from MOEX ISS (TQBR board first)."""
    bare = normalize_moex_symbol(ticker)
    end = datetime.now(timezone.utc).date()
    days_back = max(365, limit * 2) if timeframe == "1d" else 60
    start = end - timedelta(days=days_back)

    params = {
        "from": start.isoformat(),
        "till": end.isoformat(),
        "interval": _moex_interval_param(timeframe),
        "iss.meta": "off",
    }

    for url_template in (MOEX_CANDLES_URL, MOEX_CANDLES_URL_FALLBACK):
        url = url_template.format(ticker=bare)
        # ISS returns at most 500 candles per page, oldest first: without paging a long
        # window silently loses its most recent part (e.g. SBER ending in 2020).
        columns: list[str] = []
        rows: list[list[Any]] = []
        failed = False
        try:
            async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
                for _page in range(_ISS_MAX_PAGES):
                    resp = await client.get(url, params={**params, "start": len(rows)})
                    resp.raise_for_status()
                    candles = resp.json().get("candles", {})
                    page_rows = candles.get("data", []) or []
                    columns = candles.get("columns", []) or columns
                    rows.extend(page_rows)
                    if len(page_rows) < _ISS_PAGE_SIZE:
                        break
        except Exception as exc:
            logger.warning("MOEX ISS bars failed", ticker=bare, url=url, error=str(exc))
            failed = not rows
        if failed or not rows:
            continue

        bars: list[dict[str, Any]] = []
        for row in rows:
            record = dict(zip(columns, row))
            begin = record.get("begin")
            if not begin:
                continue
            ts = datetime.fromisoformat(str(begin).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            close_raw = record.get("close")
            if close_raw in (None, ""):
                continue
            try:
                close = float(close_raw)
                open_ = float(record["open"]) if record.get("open") not in (None, "") else close
                high = float(record["high"]) if record.get("high") not in (None, "") else close
                low = float(record["low"]) if record.get("low") not in (None, "") else close
                volume = float(record["volume"]) if record.get("volume") not in (None, "") else 0.0
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            bars.append(
                {
                    "timestamp": ts.isoformat(),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "vwap": None,
                    "trade_count": None,
                }
            )
        if bars:
            return bars[-limit:]
    return []


async def _fetch_yfinance_bars(
    ticker: str,
    timeframe: str,
    limit: int,
) -> list[dict[str, Any]]:
    from app.services.market_data.client import YFinanceClient

    yf_symbol = to_yfinance_symbol(ticker)
    end = datetime.now(timezone.utc)
    if timeframe == "1d":
        days_back = max(365, limit * 2)
    else:
        days_back = 60
    start = end - timedelta(days=days_back)

    try:
        bars = await YFinanceClient().get_bars(yf_symbol, timeframe, start, end)
    except Exception as exc:
        logger.debug("yfinance MOEX bars failed", ticker=yf_symbol, error=str(exc))
        return []
    return bars[-limit:] if bars else []


async def get_moex_bars(
    ticker: str,
    timeframe: str = "1d",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch OHLCV bars for MOEX ticker (ISS TQBR -> yfinance)."""
    if not await resolve_moex_ticker(ticker):
        return []

    bars = await _fetch_moex_iss_bars(ticker, timeframe, limit)
    if bars:
        return bars
    return await _fetch_yfinance_bars(ticker, timeframe, limit)


async def get_moex_quotes_batch(tickers: list[str]) -> dict[str, float]:
    """Fetch live prices for multiple MOEX tickers concurrently."""
    resolved: list[str] = []
    for t in tickers:
        if not t:
            continue
        bare = normalize_moex_symbol(t)
        if is_moex_ticker(bare) or await resolve_moex_ticker(bare):
            resolved.append(bare)
    uniq = sorted(set(resolved))
    if not uniq:
        return {}

    results = await asyncio.gather(
        *(get_live_moex_price(t) for t in uniq),
        return_exceptions=True,
    )
    prices: dict[str, float] = {}
    for ticker, result in zip(uniq, results):
        if isinstance(result, (int, float)) and result > 0:
            prices[ticker] = float(result)
    return prices
