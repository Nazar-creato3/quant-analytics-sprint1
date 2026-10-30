"""
Binance Spot public API helpers for crypto tickers (BTC-USD → BTCUSDT).

Live price resolution order:
  1. Redis `live:binance:{symbol}` — fed by binance-ws connector (sub-second)
  2. Short-lived quote cache (5s max)
  3. Binance REST `/api/v3/ticker/price` (+ 24hr stats for change_pct)

Chart bars are patched with the resolved live price so headers match spot.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
BINANCE_SPOT_URL = "https://api.binance.com"

# Max REST quote cache — crypto must never feel stale.
CRYPTO_QUOTE_CACHE_TTL = 5
LIVE_WS_KEY_PREFIX = "live:binance:"
LIVE_WS_TTL = 60  # refreshed on every trade by binance-ws

# Bare crypto bases (watchlist may use SOL instead of SOL-USD).
_KNOWN_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK"}
)

# Explicit mappings for watchlist symbols that do not follow BASE-USD → BASEUSDT.
_EXPLICIT_BINANCE: dict[str, str] = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT",
    "BNB-USD": "BNBUSDT",
    "XRP-USD": "XRPUSDT",
    "DOGE-USD": "DOGEUSDT",
    "ADA-USD": "ADAUSDT",
    "AVAX-USD": "AVAXUSDT",
    "DOT-USD": "DOTUSDT",
    "LINK-USD": "LINKUSDT",
}


def normalize_crypto_ticker(ticker: str) -> str | None:
    """Deprecated wrapper: Prompt 03 catalog.resolve. Kept for call-site migration."""
    from app.services.catalog import resolve
    from app.services.market_data.forex_catalog import is_forex_pair

    if is_forex_pair(ticker):
        return None
    try:
        hit = resolve(ticker)
    except (KeyError, ValueError):
        return None
    if hit.instrument_kind != "crypto":
        return None
    return hit.symbol


def live_ws_cache_key(symbol: str) -> str:
    return f"{LIVE_WS_KEY_PREFIX}{symbol.lower()}"


def quote_cache_key(ticker: str) -> str:
    return f"quote:crypto:{ticker.upper()}"


def ticker_to_binance_symbol(ticker: str) -> str | None:
    """Map app ticker (e.g. BTC-USD or SOL) to Binance spot symbol (BTCUSDT)."""
    canonical = normalize_crypto_ticker(ticker)
    if not canonical:
        return None
    if canonical in _EXPLICIT_BINANCE:
        return _EXPLICIT_BINANCE[canonical]
    base = canonical[:-4]
    if base.isalpha() and 2 <= len(base) <= 10:
        return f"{base}USDT"
    return None


def is_crypto_ticker(ticker: str) -> bool:
    return normalize_crypto_ticker(ticker) is not None


async def _binance_get(path: str, params: dict | None = None) -> Any:
    url = f"{BINANCE_SPOT_URL}{path}"
    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def get_ws_live_price(symbol: str) -> dict[str, Any] | None:
    """Read the latest trade price pushed by binance-ws into Redis."""
    try:
        raw = await cache_get(live_ws_cache_key(symbol))
        if not raw or not raw.get("price"):
            return None
        price = float(raw["price"])
        if price <= 0:
            return None
        ts = raw.get("event_time")
        if isinstance(ts, (int, float)) and ts > 1e12:
            ts = int(ts) / 1000.0
        timestamp = (
            datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            if ts is not None
            else datetime.now(timezone.utc).isoformat()
        )
        return {
            "price": price,
            "timestamp": timestamp,
            "source": raw.get("source", "binance_ws"),
        }
    except Exception as exc:
        logger.debug("WS live price read failed", symbol=symbol, error=str(exc))
        return None


async def get_live_crypto_price(ticker: str, *, force_refresh: bool = False) -> float | None:
    """Return the freshest crypto spot price (WS → cache → REST)."""
    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return None

    if not force_refresh:
        ws = await get_ws_live_price(symbol)
        if ws:
            return float(ws["price"])

        cached = await cache_get(quote_cache_key(ticker))
        if cached and cached.get("price"):
            return float(cached["price"])

    quote = await get_crypto_quote(ticker, force_refresh=True)
    return float(quote["price"]) if quote and quote.get("price") else None


async def get_crypto_quote(ticker: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
    """Return a normalized live quote dict for a crypto ticker, or None on failure."""
    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return None

    cache_key = quote_cache_key(ticker)

    if not force_refresh:
        ws = await get_ws_live_price(symbol)
        if ws:
            # Merge WS price with cached 24hr stats when available.
            cached = await cache_get(cache_key)
            out = {
                "ticker": ticker.upper(),
                "price": ws["price"],
                "bid": cached.get("bid") if cached else None,
                "ask": cached.get("ask") if cached else None,
                "volume": cached.get("volume") if cached else None,
                "change_pct": cached.get("change_pct") if cached else None,
                "timestamp": ws["timestamp"],
                "source": ws["source"],
            }
            return out

        cached = await cache_get(cache_key)
        if cached and cached.get("price"):
            cached = dict(cached)
            cached.setdefault("source", "binance_rest_cached")
            return cached

    try:
        book_data, stats_data = await asyncio.gather(
            _binance_get("/api/v3/ticker/bookTicker", {"symbol": symbol}),
            _binance_get("/api/v3/ticker/24hr", {"symbol": symbol}),
            return_exceptions=True,
        )

        def _finite_px(raw: Any) -> float | None:
            if raw in (None, ""):
                return None
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return None
            if v <= 0 or v != v:
                return None
            return v

        bid = ask = price = None
        if isinstance(book_data, dict):
            bid = _finite_px(book_data.get("bidPrice"))
            ask = _finite_px(book_data.get("askPrice"))
            if bid is not None and ask is not None:
                price = (bid + ask) / 2.0

        stats: dict[str, Any] = stats_data if isinstance(stats_data, dict) else {}
        if price is None:
            price = _finite_px(stats.get("lastPrice"))
        if price is None:
            price = _finite_px(stats.get("weightedAvgPrice"))
        if price is None and isinstance(book_data, dict):
            price = _finite_px(book_data.get("bidPrice"))
            if price is None:
                price = _finite_px(book_data.get("askPrice"))
        if price is None:
            return None

        change_raw = stats.get("priceChangePercent")
        if change_raw in (None, ""):
            change_pct = None
        else:
            try:
                change_pct = float(change_raw)
            except (TypeError, ValueError):
                change_pct = None

        out = {
            "ticker": ticker.upper(),
            "price": price,
            "bid": bid if bid is not None else _finite_px(stats.get("bidPrice")),
            "ask": ask if ask is not None else _finite_px(stats.get("askPrice")),
            "volume": float(stats["volume"]) if stats.get("volume") not in (None, "") else None,
            "change_pct": change_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "binance_book",
        }
        await cache_set(cache_key, out, ttl=CRYPTO_QUOTE_CACHE_TTL)
        return out
    except Exception as exc:
        logger.warning("Binance quote failed", ticker=ticker, symbol=symbol, error=str(exc))
        return None


async def get_crypto_quotes_batch(tickers: list[str]) -> dict[str, float]:
    """Fetch live prices for multiple crypto tickers concurrently."""
    uniq = sorted({t.upper() for t in tickers if t and is_crypto_ticker(t)})
    if not uniq:
        return {}

    results = await asyncio.gather(
        *(get_live_crypto_price(t) for t in uniq),
        return_exceptions=True,
    )
    prices: dict[str, float] = {}
    for ticker, result in zip(uniq, results):
        if isinstance(result, (int, float)) and result > 0:
            prices[ticker] = float(result)
    return prices


async def get_crypto_bars(
    ticker: str,
    interval: str = "1d",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch OHLCV klines from Binance for crypto tickers."""
    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return []

    interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    binance_interval = interval_map.get(interval, "1d")

    try:
        raw = await _binance_get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": binance_interval, "limit": min(limit, 1000)},
        )
    except Exception as exc:
        logger.warning("Binance klines failed", ticker=ticker, error=str(exc))
        fallback = await _ccxt_crypto_bars(ticker, binance_interval, limit)
        if fallback:
            logger.info("Crypto bars served via CCXT fallback", ticker=ticker, bars=len(fallback))
        return fallback

    bars: list[dict[str, Any]] = []
    for row in raw:
        ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
        bars.append(
            {
                "timestamp": ts.isoformat(),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "vwap": None,
                "trade_count": int(row[8]) if len(row) > 8 else None,
            }
        )
    if not bars:
        return await _ccxt_crypto_bars(ticker, binance_interval, limit)
    return bars


async def _ccxt_crypto_bars(ticker: str, interval: str, limit: int) -> list[dict[str, Any]]:
    """Public OHLCV via CCXT when Binance REST is unavailable."""
    symbol = ticker_to_binance_symbol(ticker)
    if not symbol or not symbol.endswith("USDT"):
        return []
    pair = f"{symbol[:-4]}/USDT"
    try:
        import ccxt
    except Exception as exc:  # noqa: BLE001
        logger.warning("CCXT crypto bars skipped", ticker=ticker, error=str(exc))
        return []

    def _fetch() -> list[list[Any]]:
        ex = ccxt.binance({"enableRateLimit": True})
        return ex.fetch_ohlcv(pair, interval, limit=min(limit, 500)) or []

    try:
        rows = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CCXT crypto bars failed", ticker=ticker, error=str(exc))
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
        out.append(
            {
                "timestamp": ts.isoformat(),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else None,
                "vwap": None,
                "trade_count": None,
                "source": "ccxt",
            }
        )
    return out
