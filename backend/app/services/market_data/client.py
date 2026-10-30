"""
Market data client abstraction layer.

Primary clients: Alpaca, Polygon.io, yfinance.
Extended chain (via http_providers): TwelveData, Tiingo, MarketStack, Finnhub.
Resolvers walk the full keyed chain platform-wide — not Direct Deals only.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

from app.core.config import MarketDataProvider, settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(3.0, connect=2.0)
MAX_RETRIES = 3


def _is_rate_limit_error(exc: BaseException) -> bool:
    """True when a provider rejected the call due to quota / rate limits."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _foreign_client(**extra: Any) -> httpx.AsyncClient:
    """httpx client for US/foreign market APIs (Alpaca/Polygon/…) via selective proxy."""
    kwargs = httpx_client_kwargs(foreign=True, timeout=TIMEOUT)
    kwargs.update(extra)
    return httpx.AsyncClient(**kwargs)


# ── Protocol ──────────────────────────────────────────────────────────────────

class MarketDataClient(ABC):
    """Abstract market data provider."""

    @abstractmethod
    async def get_bars(
        self,
        ticker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return list of OHLCV dicts with keys: timestamp, open, high, low, close, volume."""

    @abstractmethod
    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        """Return latest quote dict."""

    @abstractmethod
    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """Return dict of ticker -> quote."""


# ── Alpaca ────────────────────────────────────────────────────────────────────

class AlpacaClient(MarketDataClient):
    """Alpaca Markets data client (paper and live)."""

    BASE_DATA_URL = "https://data.alpaca.markets/v2"
    TIMEFRAME_MAP = {
        "1m": "1Min", "5m": "5Min", "15m": "15Min",
        "1h": "1Hour", "4h": "4Hour", "1d": "1Day",
    }

    def __init__(self) -> None:
        self._headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.BASE_DATA_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(url, headers=self._headers, params=params)
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Alpaca rate limit, retrying", wait=wait)
                    await asyncio.sleep(wait)
                    continue
                raise
            except httpx.RequestError as exc:
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded")

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        tf = self.TIMEFRAME_MAP.get(timeframe, "1Day")
        data = await self._get(
            f"/stocks/{ticker}/bars",
            params={
                "timeframe": tf,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 1000,
                "adjustment": "all",
                "feed": "iex",
            },
        )
        bars = data.get("bars", [])
        return [
            {
                "timestamp": b["t"],
                "open": b["o"],
                "high": b["h"],
                "low": b["l"],
                "close": b["c"],
                "volume": b["v"],
                "vwap": b.get("vw"),
                "trade_count": b.get("n"),
            }
            for b in bars
        ]

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get(
            "/stocks/snapshots",
            params={"symbols": ticker, "feed": "iex"},
        )
        snap = data.get(ticker, {})
        dp = snap.get("dailyBar", {})
        lq = snap.get("latestQuote", {})
        lt = snap.get("latestTrade", {})
        price = lt.get("p") or dp.get("c")
        return {
            "ticker": ticker,
            "price": price,
            "open": dp.get("o"),
            "high": dp.get("h"),
            "low": dp.get("l"),
            "volume": dp.get("v"),
            "bid": lq.get("bp"),
            "ask": lq.get("ap"),
            "bid_size": lq.get("bs"),
            "ask_size": lq.get("as"),
            "timestamp": lq.get("t") or lt.get("t"),
            "change_pct": (
                (dp.get("c", 0) - dp.get("o", 1)) / dp.get("o", 1) * 100
                if dp.get("o")
                else None
            ),
        }

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """Batch quote fetch via Alpaca snapshots endpoint."""
        data = await self._get(
            "/stocks/snapshots",
            params={"symbols": ",".join(tickers)},
        )
        result: dict[str, dict] = {}
        for ticker, snap in data.items():
            dp = snap.get("dailyBar", {})
            lq = snap.get("latestQuote", {})
            result[ticker] = {
                "ticker": ticker,
                "price": dp.get("c"),
                "open": dp.get("o"),
                "high": dp.get("h"),
                "low": dp.get("l"),
                "volume": dp.get("v"),
                "bid": lq.get("bp"),
                "ask": lq.get("ap"),
                "change_pct": (
                    (dp.get("c", 0) - dp.get("o", 1)) / dp.get("o", 1) * 100
                    if dp.get("o") else None
                ),
            }
        return result


# ── Polygon.io ────────────────────────────────────────────────────────────────

class PolygonClient(MarketDataClient):
    """Polygon.io market data client."""

    BASE_URL = "https://api.polygon.io"
    TIMEFRAME_MAP = {
        "1m": ("minute", 1), "5m": ("minute", 5), "15m": ("minute", 15),
        "1h": ("hour", 1), "4h": ("hour", 4), "1d": ("day", 1),
    }

    def __init__(self) -> None:
        self._api_key = settings.POLYGON_API_KEY

    async def _get(self, path: str, params: dict | None = None) -> dict:
        params = {**(params or {}), "apiKey": self._api_key}
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(f"{self.BASE_URL}{path}", params=params)
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except httpx.RequestError:
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded")

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        span, mult = self.TIMEFRAME_MAP.get(timeframe, ("day", 1))
        data = await self._get(
            f"/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        return [
            {
                "timestamp": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).isoformat(),
                "open": b["o"],
                "high": b["h"],
                "low": b["l"],
                "close": b["c"],
                "volume": b["v"],
                "vwap": b.get("vw"),
                "trade_count": b.get("n"),
            }
            for b in data.get("results", [])
        ]

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get(f"/v2/last/trade/{ticker}")
        trade = data.get("results", {})
        return {
            "ticker": ticker,
            "price": trade.get("p"),
            "timestamp": datetime.fromtimestamp(
                trade.get("t", 0) / 1000, tz=timezone.utc
            ).isoformat() if trade.get("t") else datetime.now(timezone.utc).isoformat(),
        }

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output: dict[str, dict[str, Any]] = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                from app.utils.secret_redact import redact_secrets

                logger.warning(
                    "Polygon quote failed",
                    ticker=ticker,
                    error=redact_secrets(str(result)),
                )
            else:
                output[ticker] = result
        return output

    async def get_news(
        self,
        symbols: list[str] | None = None,
        *,
        limit: int = 20,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Polygon / Massive reference news — GET /v2/reference/news."""
        from app.services.market_data.http_providers import _equity_news_symbols

        clean = _equity_news_symbols(symbols)
        params: dict[str, Any] = {
            "limit": min(max(limit, 1), 50),
            "order": "desc",
            "sort": "published_utc",
        }
        if clean:
            params["ticker"] = clean[0]
        if from_date is not None:
            params["published_utc.gte"] = from_date.strftime("%Y-%m-%d")
        if to_date is not None:
            params["published_utc.lte"] = to_date.strftime("%Y-%m-%d")
        try:
            data = await self._get("/v2/reference/news", params=params)
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            logger.warning("Polygon news failed", error=redact_secrets(str(exc)))
            return []
        rows = data.get("results") or []
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            publisher = row.get("publisher") if isinstance(row.get("publisher"), dict) else {}
            tickers = row.get("tickers") if isinstance(row.get("tickers"), list) else clean
            out.append(
                {
                    "title": title,
                    "summary": row.get("description"),
                    "source": str(publisher.get("name") or "polygon"),
                    "url": str(row.get("article_url") or row.get("amp_url") or ""),
                    "published_at": row.get("published_utc"),
                    "symbols": [str(t).upper() for t in (tickers or []) if t],
                    "provider": "polygon",
                }
            )
        return out


# ── yfinance Fallback ─────────────────────────────────────────────────────────

class YFinanceClient(MarketDataClient):
    """yfinance-based client — no API key required, limited rate limits."""

    # yfinance intervals. It has no native 4h, so approximate with 1h data.
    PERIOD_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d", "1w": "1wk", "1wk": "1wk"}

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        import yfinance as yf

        interval = self.PERIOD_MAP.get(timeframe, "1d")
        loop = asyncio.get_event_loop()

        # yfinance can transiently return an empty frame / raise JSON errors when
        # Yahoo rotates cookies or rate-limits. Retry a few times before giving
        # up so a single hiccup doesn't fail the whole pipeline. (Requires a
        # recent yfinance + curl_cffi; see requirements-pipeline.txt.)
        hist = None
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                hist = await loop.run_in_executor(
                    None,
                    lambda: yf.Ticker(ticker).history(
                        start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        interval=interval,
                        auto_adjust=True,
                    ),
                )
                if hist is not None and not hist.empty:
                    break
                logger.warning("yfinance empty frame, retrying", ticker=ticker, attempt=attempt)
            except Exception as exc:  # noqa: BLE001 - yfinance raises many error types
                last_err = exc
                logger.warning("yfinance fetch error", ticker=ticker, attempt=attempt, error=str(exc))
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))

        if hist is None or hist.empty:
            logger.warning(
                "yfinance returned no data",
                ticker=ticker,
                error=str(last_err) if last_err else "empty",
            )
            return []

        bars = []
        for ts, row in hist.iterrows():
            bars.append({
                "timestamp": ts.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
                "vwap": None,
                "trade_count": None,
            })
        return bars

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        import yfinance as yf

        loop = asyncio.get_event_loop()

        def _fetch() -> dict[str, Any]:
            t = yf.Ticker(ticker)
            price: float | None = None
            bid: float | None = None
            ask: float | None = None
            volume: float | None = None
            day_high: float | None = None
            day_low: float | None = None
            change_pct: float | None = None

            # fast_info is much fresher than the heavy .info document.
            try:
                fi = t.fast_info
                raw_price = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
                if raw_price:
                    price = float(raw_price)
                raw_bid = getattr(fi, "bid", None)
                raw_ask = getattr(fi, "ask", None)
                if raw_bid:
                    bid = float(raw_bid)
                if raw_ask:
                    ask = float(raw_ask)
                raw_vol = getattr(fi, "last_volume", None) or getattr(fi, "lastVolume", None)
                if raw_vol:
                    volume = float(raw_vol)
                raw_high = getattr(fi, "day_high", None) or getattr(fi, "dayHigh", None)
                raw_low = getattr(fi, "day_low", None) or getattr(fi, "dayLow", None)
                if raw_high:
                    day_high = float(raw_high)
                if raw_low:
                    day_low = float(raw_low)
            except Exception as exc:
                logger.warning(
                    "yfinance fast_info unavailable; falling back",
                    ticker=ticker,
                    error=str(exc)[:200],
                )

            # Intraday last trade when fast_info is empty (common off-hours).
            if price is None:
                hist = t.history(period="1d", interval="1m")
                if hist is not None and not hist.empty:
                    last = hist.iloc[-1]
                    price = float(last["Close"])
                    if volume is None:
                        volume = float(last["Volume"])
                    if day_high is None:
                        day_high = float(hist["High"].max())
                    if day_low is None:
                        day_low = float(hist["Low"].min())

            info: dict[str, Any] = {}
            if (
                price is None
                or bid is None
                or ask is None
                or volume is None
                or day_high is None
                or day_low is None
                or change_pct is None
            ):
                info = dict(getattr(t, "info", None) or {})

            if price is None:
                price = info.get("regularMarketPrice") or info.get("currentPrice")
            bid = bid or info.get("bid")
            ask = ask or info.get("ask")
            volume = volume or info.get("regularMarketVolume")
            day_high = day_high or info.get("regularMarketDayHigh") or info.get("dayHigh")
            day_low = day_low or info.get("regularMarketDayLow") or info.get("dayLow")
            if change_pct is None:
                change_pct = info.get("regularMarketChangePercent")

            return {
                "ticker": ticker,
                "price": float(price) if price else None,
                "bid": float(bid) if bid else None,
                "ask": float(ask) if ask else None,
                "high": float(day_high) if day_high else None,
                "low": float(day_low) if day_low else None,
                "volume": float(volume) if volume else None,
                "change_pct": change_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "yfinance",
            }

        return await loop.run_in_executor(None, _fetch)

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.warning("Quote failed", ticker=ticker, error=str(result))
            else:
                output[ticker] = result
        return output


# ── Factory ───────────────────────────────────────────────────────────────────

_client_instance: MarketDataClient | None = None


# Longer than the 15s watchlist poll so N logged-in users share one upstream hit.
_QUOTE_CACHE_TTL_EQUITY = 45
_QUOTE_CACHE_TTL_MARKETSTACK_EOD = 86_400  # EOD data — cache 24h to respect free-tier limits
_QUOTE_CACHE_PREFIX = "quote:equity:"


def build_equity_client_chain(*, include_yfinance: bool = True) -> list[tuple[str, Any]]:
    """
    Ordered equity clients for platform-wide quote/bar resolution.
    Alpaca → Polygon → TwelveData → Tiingo → Finnhub
    → equity EOD local (Tiingo/Yahoo board cache)
    → Stooq local bulk → Stooq HTTP → yfinance
    MarketStack is **not** in this chain — only used for curated/suffixed
    symbols via the dedicated path in _try_chain_quote/_try_chain_bars.
    """
    from app.services.market_data.http_providers import (
        FinnhubMarketClient,
        TiingoClient,
        TwelveDataClient,
        key_configured,
    )

    preferred = settings.MARKET_DATA_PROVIDER.value
    builders: list[tuple[str, Any]] = [
        ("alpaca", AlpacaClient),
        ("polygon", PolygonClient),
        ("twelvedata", TwelveDataClient),
        ("tiingo", TiingoClient),
        ("finnhub", FinnhubMarketClient),
    ]
    builders.sort(key=lambda item: 0 if item[0] == preferred else 1)

    chain: list[tuple[str, Any]] = []
    for name, cls in builders:
        if not key_configured(name):
            continue
        try:
            chain.append((name, cls()))
        except Exception as exc:
            logger.warning("Failed to init market client", provider=name, error=str(exc))

    if include_yfinance:
        from app.services.market_data.equity_eod_store import EquityEodLocalClient
        from app.services.market_data.stooq_bulk_store import StooqLocalClient
        from app.services.market_data.stooq_client import StooqClient

        chain.append(("eod_local", EquityEodLocalClient()))
        chain.append(("stooq_local", StooqLocalClient()))
        chain.append(("stooq", StooqClient()))
        chain.append(("yfinance", YFinanceClient()))
    return chain


async def _try_chain_yfinance_bars(
    ticker: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Public last-resort: EOD board cache → Stooq local → Stooq HTTP → yfinance."""
    for name, client in build_equity_client_chain():
        if name not in {"eod_local", "stooq_local", "stooq", "yfinance"}:
            continue
        try:
            bars = await client.get_bars(ticker, timeframe, start, end)
            if bars:
                for bar in bars:
                    if isinstance(bar, dict):
                        bar.setdefault("source", name)
                return bars
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            logger.warning(
                "public bars fallback failed",
                provider=name,
                ticker=ticker,
                error=redact_secrets(str(exc)),
            )
    return []


async def _try_chain_bars(
    ticker: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    skip_keyed_providers: bool = False,
    rate_limit_seen: list[bool] | None = None,
) -> list[dict[str, Any]]:
    from app.services.market_data.marketstack_catalog import (
        is_marketstack_eligible,
        resolve_marketstack_symbol,
    )

    sym = ticker.strip().upper()
    if is_marketstack_eligible(sym):
        ms_sym = resolve_marketstack_symbol(sym) or sym
        from app.services.market_data.http_providers import MarketStackClient, key_configured

        if key_configured("marketstack"):
            try:
                bars = await MarketStackClient().get_bars(ms_sym, timeframe, start, end)
                if bars:
                    for bar in bars:
                        if isinstance(bar, dict):
                            bar.setdefault("source", "marketstack")
                    return bars
            except Exception as exc:
                from app.utils.secret_redact import redact_secrets

                logger.warning(
                    "Marketstack bars failed, trying equity chain",
                    ticker=ms_sym,
                    error=redact_secrets(str(exc)),
                )

    if skip_keyed_providers:
        return await _try_chain_yfinance_bars(ticker, timeframe, start, end)

    last_error: Exception | None = None
    for name, client in build_equity_client_chain():
        if name == "yfinance":
            continue
        if name == "stooq":
            continue
        try:
            bars = await client.get_bars(ticker, timeframe, start, end)
            if bars:
                for bar in bars:
                    if isinstance(bar, dict):
                        bar.setdefault("source", name)
                return bars
        except Exception as exc:
            last_error = exc
            from app.utils.secret_redact import redact_secrets

            if _is_rate_limit_error(exc):
                if rate_limit_seen is not None:
                    rate_limit_seen[0] = True
                logger.warning(
                    "Equity bars rate-limited, falling back to yfinance",
                    provider=name,
                    ticker=ticker,
                )
                return await _try_chain_yfinance_bars(ticker, timeframe, start, end)

            logger.warning(
                "Equity bars provider failed, trying next",
                provider=name,
                ticker=ticker,
                error=redact_secrets(str(exc)),
            )

    yf_bars = await _try_chain_yfinance_bars(ticker, timeframe, start, end)
    if yf_bars:
        return yf_bars

    if last_error:
        from app.utils.secret_redact import redact_secrets

        logger.warning(
            "All equity bar providers failed",
            ticker=ticker,
            error=redact_secrets(str(last_error)),
        )
    return []


async def _try_chain_quote(ticker: str) -> dict[str, Any]:
    from app.services.market_data.marketstack_catalog import (
        is_marketstack_eligible,
        resolve_marketstack_symbol,
    )

    sym = ticker.strip().upper()
    if is_marketstack_eligible(sym):
        ms_sym = resolve_marketstack_symbol(sym) or sym
        from app.services.market_data.http_providers import MarketStackClient, key_configured

        if key_configured("marketstack"):
            try:
                quote = await MarketStackClient().get_latest_quote(ms_sym)
                quote = dict(quote or {})
                quote.setdefault("source", "marketstack")
                if quote.get("price") is not None:
                    return quote
            except Exception as exc:
                from app.utils.secret_redact import redact_secrets

                logger.warning(
                    "Marketstack quote failed, trying equity chain",
                    ticker=ms_sym,
                    error=redact_secrets(str(exc)),
                )

    last_error: Exception | None = None
    for name, client in build_equity_client_chain():
        try:
            quote = await client.get_latest_quote(ticker)
            quote = dict(quote or {})
            quote.setdefault("source", name)
            if quote.get("price") is not None:
                return quote
        except Exception as exc:
            last_error = exc
            from app.utils.secret_redact import redact_secrets

            logger.warning(
                "Equity quote provider failed, trying next",
                provider=name,
                ticker=ticker,
                error=redact_secrets(str(exc)),
            )
    if last_error:
        from app.utils.secret_redact import redact_secrets

        logger.warning(
            "All equity quote providers failed",
            ticker=ticker,
            error=redact_secrets(str(last_error)),
        )
    return {"ticker": ticker, "price": None, "source": "none"}


async def get_grid_tick_quote(ticker: str) -> dict[str, Any]:
    """Fresh quote for grid bot ticks — Binance/CoinGecko crypto, MOEX, equity chain."""
    from app.services.market_data.binance_spot import get_crypto_quote, is_crypto_ticker
    from app.services.market_data.http_providers import CoinGeckoClient
    from app.services.market_data.moex_currency import get_moex_currency_quote, is_moex_currency_ticker
    from app.services.market_data.moex_spot import get_moex_quote, is_moex_ticker

    ticker = ticker.upper()
    if is_crypto_ticker(ticker):
        quote = await get_crypto_quote(ticker, force_refresh=True)
        if quote and quote.get("price"):
            return quote
        try:
            cg = await CoinGeckoClient().get_latest_quote(ticker)
            if cg and cg.get("price"):
                return cg
        except Exception as exc:
            logger.debug("CoinGecko grid tick fallback failed", ticker=ticker, error=str(exc))
        raise ValueError(f"No crypto quote for {ticker}")

    if is_moex_currency_ticker(ticker):
        quote = await get_moex_currency_quote(ticker, force_refresh=True)
        if quote and quote.get("price"):
            return quote
        raise ValueError(f"No MOEX currency quote for {ticker}")

    if is_moex_ticker(ticker):
        quote = await get_moex_quote(ticker, force_refresh=True)
        if quote and quote.get("price"):
            return quote
        raise ValueError(f"No MOEX quote for {ticker}")

    quote = await _try_chain_quote(ticker)
    if not quote.get("price"):
        raise ValueError(f"No equity quote for {ticker}")
    return quote


async def get_bars_resolved(
    ticker: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    crypto_limit: int = 400,
    moex_limit: int = 400,
    skip_keyed_providers: bool = False,
    rate_limit_seen: list[bool] | None = None,
) -> list[dict[str, Any]]:
    """OHLCV bars — crypto/MOEX routes + full equity provider chain."""
    from app.services.market_data.binance_spot import get_crypto_bars, is_crypto_ticker
    from app.services.market_data.http_providers import CoinGeckoClient
    from app.services.market_data.moex_currency import get_moex_currency_bars, is_moex_currency_ticker
    from app.services.market_data.moex_spot import get_moex_bars, is_moex_ticker

    sym = ticker.strip().upper()
    if is_crypto_ticker(sym):
        bars = await get_crypto_bars(sym, timeframe if timeframe in ("1d", "1h") else "1d", crypto_limit)
        if bars:
            return bars
        try:
            return await CoinGeckoClient().get_bars(sym, timeframe, start, end)
        except Exception as exc:
            logger.debug("CoinGecko bars fallback failed", ticker=sym, error=str(exc))
            return []

    if is_moex_currency_ticker(sym):
        bars = await get_moex_currency_bars(sym, timeframe, moex_limit)
        return bars or []

    if is_moex_ticker(sym):
        bars = await get_moex_bars(sym, timeframe, moex_limit)
        return bars or []

    return await _try_chain_bars(
        sym,
        timeframe,
        start,
        end,
        skip_keyed_providers=skip_keyed_providers,
        rate_limit_seen=rate_limit_seen,
    )


async def get_latest_quote_resolved(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Freshest quote — Binance/CoinGecko crypto, MOEX, then equity provider chain."""
    from app.services.market_data.binance_spot import get_crypto_quote, is_crypto_ticker
    from app.services.market_data.http_providers import CoinGeckoClient
    from app.services.market_data.moex_currency import (
        get_moex_currency_quote,
        is_moex_currency_ticker,
        normalize_moex_currency_symbol,
    )
    from app.services.market_data.moex_spot import get_moex_quote, is_moex_ticker, normalize_moex_symbol
    from app.utils.cache import cache_delete, cache_get, cache_set

    ticker = ticker.upper()

    if is_crypto_ticker(ticker):
        quote = await get_crypto_quote(ticker, force_refresh=force_refresh)
        if quote:
            return quote
        try:
            cg = await CoinGeckoClient().get_latest_quote(ticker)
            if cg and cg.get("price") is not None:
                return cg
        except Exception as exc:
            logger.debug("CoinGecko quote fallback failed", ticker=ticker, error=str(exc))

    if is_moex_currency_ticker(ticker):
        quote = await get_moex_currency_quote(ticker, force_refresh=force_refresh)
        if quote:
            return quote
        raise ValueError(f"No MOEX currency quote for {normalize_moex_currency_symbol(ticker)}")

    if is_moex_ticker(ticker):
        quote = await get_moex_quote(ticker, force_refresh=force_refresh)
        if quote:
            return quote
        raise ValueError(f"No MOEX quote for {normalize_moex_symbol(ticker)}")

    cache_key = f"{_QUOTE_CACHE_PREFIX}{ticker}"
    if force_refresh:
        await cache_delete(cache_key)

    if not force_refresh:
        cached = await cache_get(cache_key)
        if cached and cached.get("price") is not None:
            cached = dict(cached)
            cached.setdefault("source", f"{cached.get('source', 'chain')}_cached")
            return cached

    from app.utils.cache import cache_lock_acquire, cache_lock_release

    lock_key = f"quote:lock:{ticker}"
    won_lock = await cache_lock_acquire(lock_key, ttl=25)
    if not won_lock:
        for _ in range(20):
            await asyncio.sleep(0.15)
            cached = await cache_get(cache_key)
            if cached and cached.get("price") is not None:
                cached = dict(cached)
                cached.setdefault("source", f"{cached.get('source', 'chain')}_cached")
                return cached

    try:
        quote = await _try_chain_quote(ticker)
        if quote.get("price") is not None:
            if force_refresh:
                await cache_delete(cache_key)
            from app.services.market_data.marketstack_catalog import is_marketstack_eligible

            ttl = (
                _QUOTE_CACHE_TTL_MARKETSTACK_EOD
                if is_marketstack_eligible(ticker) or quote.get("source") == "marketstack"
                else _QUOTE_CACHE_TTL_EQUITY
            )
            await cache_set(cache_key, quote, ttl=ttl)
        return quote
    finally:
        if won_lock:
            await cache_lock_release(lock_key)


def _provider_api_keys_configured(provider: MarketDataProvider) -> bool:
    """True when configured keys look like real credentials (not .env placeholders)."""
    from app.services.market_data.http_providers import key_configured

    return key_configured(provider.value)


def get_market_data_client() -> MarketDataClient:
    """Return a singleton primary client; resolvers still walk the full chain."""
    global _client_instance
    if _client_instance is None:
        chain = build_equity_client_chain(include_yfinance=True)
        if chain:
            name, client = chain[0]
            _client_instance = client  # type: ignore[assignment]
            logger.info("Market data client initialized", provider=name)
        else:
            _client_instance = YFinanceClient()
            logger.info("Market data client initialized", provider="yfinance")
    return _client_instance


def reset_market_data_client() -> None:
    """Clear singleton (tests / settings reload)."""
    global _client_instance
    _client_instance = None
