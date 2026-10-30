"""
Additional HTTP market-data clients for the platform-wide equity/crypto chain.

Used by market_data.client resolvers and terminal ProviderRouter wrappers.
Keys come only from Settings / env — never hardcode secrets.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(3.0, connect=2.0)
MAX_RETRIES = 3


def _foreign_client(**extra: Any) -> httpx.AsyncClient:
    kwargs = httpx_client_kwargs(foreign=True, timeout=TIMEOUT)
    kwargs.update(extra)
    return httpx.AsyncClient(**kwargs)

_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "BTC-USD": "bitcoin",
    "BTCUSDT": "bitcoin",
    "ETH": "ethereum",
    "ETH-USD": "ethereum",
    "ETHUSDT": "ethereum",
    "SOL": "solana",
    "SOL-USD": "solana",
    "SOLUSDT": "solana",
    "BNB": "binancecoin",
    "BNB-USD": "binancecoin",
    "XRP": "ripple",
    "XRP-USD": "ripple",
    "DOGE": "dogecoin",
    "DOGE-USD": "dogecoin",
    "ADA": "cardano",
    "ADA-USD": "cardano",
    "AVAX": "avalanche-2",
    "AVAX-USD": "avalanche-2",
    "DOT": "polkadot",
    "DOT-USD": "polkadot",
    "LINK": "chainlink",
    "LINK-USD": "chainlink",
}


def _usable(value: str | None) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    lowered = v.lower()
    if lowered.startswith("your-") or lowered in {"changeme", "placeholder", "xxx"}:
        return False
    return True


def twelve_data_api_key() -> str:
    return (settings.TWELVEDATA_API_KEY or settings.TWELVE_DATA_API_KEY or "").strip()


def key_configured(provider: str) -> bool:
    """Whether a named provider has usable credentials."""
    name = provider.lower().strip()
    if name == "alpaca":
        return _usable(settings.ALPACA_API_KEY) and _usable(settings.ALPACA_SECRET_KEY)
    if name == "polygon":
        return _usable(settings.POLYGON_API_KEY)
    if name in {"twelvedata", "twelve_data"}:
        return _usable(twelve_data_api_key())
    if name == "tiingo":
        return _usable(settings.TIINGO_API_KEY)
    if name == "marketstack":
        return _usable(settings.MARKETSTACK_API_KEY)
    if name == "finnhub":
        return _usable(settings.FINNHUB_API_KEY)
    if name == "coingecko":
        return True  # public tier works; key raises limits
    if name == "stooq":
        return True
    if name == "yfinance":
        return True
    return False


def configured_provider_flags() -> dict[str, bool]:
    """Names-only configured flags for data-health (never echo secrets)."""
    return {
        "alpaca": key_configured("alpaca"),
        "polygon": key_configured("polygon"),
        "twelvedata": key_configured("twelvedata"),
        "tiingo": key_configured("tiingo"),
        "marketstack": key_configured("marketstack"),
        "finnhub": key_configured("finnhub"),
        "coingecko": _usable(settings.COINGECKO_API_KEY),
        "stooq": True,
        "yfinance": True,
    }


def _equity_news_symbols(symbols: list[str] | None) -> list[str]:
    """US equity tickers suitable for Finnhub/Tiingo/Polygon company news."""
    out: list[str] = []
    for raw in symbols or []:
        s = str(raw or "").strip().upper()
        if not s or s.startswith("^") or "-" in s or "/" in s:
            continue
        # Drop MOEX-style .ME suffixes for US news APIs.
        if s.endswith(".ME"):
            continue
        bare = s.split(".")[0]
        if bare.replace(".", "").isalnum() and bare.isascii():
            out.append(bare)
    return list(dict.fromkeys(out))


# ── Twelve Data ───────────────────────────────────────────────────────────────

class TwelveDataClient:
    BASE_URL = "https://api.twelvedata.com"
    INTERVAL_MAP = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    def __init__(self) -> None:
        self._api_key = twelve_data_api_key()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        query = {**(params or {}), "apikey": self._api_key}
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(f"{self.BASE_URL}{path}", params=query)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, dict) and data.get("status") == "error":
                        raise RuntimeError(str(data.get("message") or data))
                    return data if isinstance(data, dict) else {}
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
        interval = self.INTERVAL_MAP.get(timeframe, "1day")
        data = await self._get(
            "/time_series",
            params={
                "symbol": ticker.upper(),
                "interval": interval,
                "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
                "order": "ASC",
                "timezone": "UTC",
            },
        )
        values = data.get("values") or []
        out: list[dict[str, Any]] = []
        for row in values:
            out.append(
                {
                    "timestamp": row.get("datetime"),
                    "open": float(row["open"]) if row.get("open") is not None else None,
                    "high": float(row["high"]) if row.get("high") is not None else None,
                    "low": float(row["low"]) if row.get("low") is not None else None,
                    "close": float(row["close"]) if row.get("close") is not None else None,
                    "volume": float(row["volume"]) if row.get("volume") not in (None, "") else None,
                    "source": "twelvedata",
                }
            )
        return out

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get("/quote", params={"symbol": ticker.upper()})
        price = data.get("close") or data.get("price") or data.get("previous_close")
        change_pct = data.get("percent_change")
        try:
            change_pct_f = float(change_pct) if change_pct is not None else None
        except (TypeError, ValueError):
            change_pct_f = None
        return {
            "ticker": ticker.upper(),
            "price": float(price) if price is not None else None,
            "open": float(data["open"]) if data.get("open") is not None else None,
            "high": float(data["high"]) if data.get("high") is not None else None,
            "low": float(data["low"]) if data.get("low") is not None else None,
            "volume": float(data["volume"]) if data.get("volume") not in (None, "") else None,
            "bid": float(data["bid"]) if data.get("bid") is not None else None,
            "ask": float(data["ask"]) if data.get("ask") is not None else None,
            "change_pct": change_pct_f,
            "currency": (data.get("currency") or "").upper() or None,
            "exchange": data.get("exchange"),
            "timestamp": data.get("datetime") or datetime.now(timezone.utc).isoformat(),
            "source": "twelvedata",
        }

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                from app.utils.secret_redact import redact_secrets

                logger.warning(
                    "TwelveData quote failed",
                    ticker=ticker,
                    error=redact_secrets(str(result)),
                )
            else:
                out[ticker] = result
        return out

    async def get_news(
        self,
        symbols: list[str] | None = None,
        *,
        limit: int = 20,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """TwelveData has no general news endpoint on free tier — empty."""
        return []


# ── Tiingo ────────────────────────────────────────────────────────────────────

class TiingoClient:
    BASE_URL = "https://api.tiingo.com"

    def __init__(self) -> None:
        self._api_key = (settings.TIINGO_API_KEY or "").strip()
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {self._api_key}",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(
                        f"{self.BASE_URL}{path}",
                        headers=self._headers,
                        params=params,
                    )
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
        data = await self._get(
            f"/tiingo/daily/{quote(ticker.upper(), safe='')}/prices",
            params={
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
                "format": "json",
            },
        )
        rows = data if isinstance(data, list) else []
        return [
            {
                "timestamp": row.get("date"),
                "open": row.get("open") or row.get("adjOpen"),
                "high": row.get("high") or row.get("adjHigh"),
                "low": row.get("low") or row.get("adjLow"),
                "close": row.get("close") or row.get("adjClose"),
                "volume": row.get("volume") or row.get("adjVolume"),
                "source": "tiingo",
            }
            for row in rows
        ]

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        sym = ticker.upper()
        try:
            iex = await self._get("/iex/", params={"tickers": sym})
            row = iex[0] if isinstance(iex, list) and iex else {}
            if row.get("tngoLast") or row.get("last"):
                price = row.get("tngoLast") or row.get("last")
                return {
                    "ticker": sym,
                    "price": float(price) if price is not None else None,
                    "bid": float(row["bidPrice"]) if row.get("bidPrice") is not None else None,
                    "ask": float(row["askPrice"]) if row.get("askPrice") is not None else None,
                    "high": float(row["high"]) if row.get("high") is not None else None,
                    "low": float(row["low"]) if row.get("low") is not None else None,
                    "volume": float(row["volume"]) if row.get("volume") is not None else None,
                    "timestamp": row.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                    "source": "tiingo",
                }
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            logger.debug(
                "Tiingo IEX quote failed, trying daily",
                ticker=sym,
                error=redact_secrets(str(exc)),
            )

        end = datetime.now(timezone.utc)
        start = end.replace(year=max(2000, end.year - 1))
        bars = await self.get_bars(sym, "1d", start, end)
        if not bars:
            return {"ticker": sym, "price": None, "source": "tiingo"}
        last = bars[-1]
        return {
            "ticker": sym,
            "price": last.get("close"),
            "open": last.get("open"),
            "high": last.get("high"),
            "low": last.get("low"),
            "volume": last.get("volume"),
            "timestamp": last.get("timestamp"),
            "source": "tiingo",
        }

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for ticker, result in zip(tickers, results):
            if not isinstance(result, Exception):
                out[ticker] = result
        return out

    async def get_news(
        self,
        symbols: list[str] | None = None,
        *,
        limit: int = 20,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Tiingo curated news — https://api.tiingo.com/tiingo/news"""
        params: dict[str, Any] = {
            "limit": min(max(limit, 1), 100),
            "sortBy": "publishedDate",
        }
        clean = _equity_news_symbols(symbols)
        if clean:
            params["tickers"] = ",".join(s.lower() for s in clean[:8])
        if from_date is not None:
            params["startDate"] = from_date.strftime("%Y-%m-%d")
        if to_date is not None:
            params["endDate"] = to_date.strftime("%Y-%m-%d")
        try:
            data = await self._get("/tiingo/news", params=params)
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            logger.warning("Tiingo news failed", error=redact_secrets(str(exc)))
            return []
        rows = data if isinstance(data, list) else []
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            tickers = row.get("tickers") if isinstance(row.get("tickers"), list) else clean
            out.append(
                {
                    "title": title,
                    "summary": row.get("description") or row.get("snippet"),
                    "source": str(row.get("source") or "tiingo"),
                    "url": str(row.get("url") or row.get("articleUrl") or ""),
                    "published_at": row.get("publishedDate") or row.get("crawlDate"),
                    "symbols": [str(t).upper() for t in (tickers or []) if t],
                    "provider": "tiingo",
                }
            )
        return out


# ── MarketStack ───────────────────────────────────────────────────────────────

class MarketStackClient:
    BASE_URL = "https://api.marketstack.com/v1"

    def __init__(self) -> None:
        self._api_key = (settings.MARKETSTACK_API_KEY or "").strip()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        query = {**(params or {}), "access_key": self._api_key}
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(f"{self.BASE_URL}{path}", params=query)
                    resp.raise_for_status()
                    data = resp.json()
                    return data if isinstance(data, dict) else {}
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
        data = await self._get(
            "/eod",
            params={
                "symbols": ticker.upper(),
                "date_from": start.strftime("%Y-%m-%d"),
                "date_to": end.strftime("%Y-%m-%d"),
                "limit": 1000,
                "sort": "ASC",
            },
        )
        rows = data.get("data") or []
        return [
            {
                "timestamp": row.get("date"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "source": "marketstack",
            }
            for row in rows
        ]

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        sym = ticker.upper()
        data = await self._get("/eod/latest", params={"symbols": sym})
        rows = data.get("data") or []
        row = rows[0] if rows else {}
        return {
            "ticker": sym,
            "price": row.get("close"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "volume": row.get("volume"),
            "timestamp": row.get("date") or datetime.now(timezone.utc).isoformat(),
            "source": "marketstack",
            "currency": (row.get("currency") or "").upper() or None,
            "exchange": row.get("exchange"),
        }

    async def search_tickers(self, query: str, *, limit: int = 15) -> list[dict[str, Any]]:
        """Live search against Marketstack's full ticker directory (not a local subset)."""
        q = (query or "").strip()
        if not q:
            return []
        cap = max(1, min(int(limit), 100))
        data = await self._get(
            "/tickerslist",
            params={"search": q, "limit": cap, "offset": 0},
        )
        rows = data.get("data") or []
        return [row for row in rows if isinstance(row, dict)]

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        if not tickers:
            return {}
        data = await self._get(
            "/eod/latest",
            params={"symbols": ",".join(t.upper() for t in tickers)},
        )
        out: dict[str, dict[str, Any]] = {}
        for row in data.get("data") or []:
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            out[sym] = {
                "ticker": sym,
                "price": row.get("close"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": row.get("volume"),
                "timestamp": row.get("date"),
                "source": "marketstack",
            }
        return out


# ── Finnhub quotes / candles ──────────────────────────────────────────────────

class FinnhubMarketClient:
    BASE_URL = "https://finnhub.io/api/v1"
    RESOLUTION_MAP = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "60",
        "1d": "D",
    }

    def __init__(self) -> None:
        self._api_key = (settings.FINNHUB_API_KEY or "").strip()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        data = await self._get_any(path, params)
        return data if isinstance(data, dict) else {}

    async def _get_any(self, path: str, params: dict | None = None) -> Any:
        query = {**(params or {}), "token": self._api_key}
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    resp = await client.get(f"{self.BASE_URL}{path}", params=query)
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
        data = await self._get(
            "/stock/candle",
            params={
                "symbol": ticker.upper(),
                "resolution": self.RESOLUTION_MAP.get(timeframe, "D"),
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
            },
        )
        if data.get("s") != "ok":
            return []
        ts = data.get("t") or []
        opens = data.get("o") or []
        highs = data.get("h") or []
        lows = data.get("l") or []
        closes = data.get("c") or []
        vols = data.get("v") or []
        out: list[dict[str, Any]] = []
        for i, t in enumerate(ts):
            out.append(
                {
                    "timestamp": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(),
                    "open": opens[i] if i < len(opens) else None,
                    "high": highs[i] if i < len(highs) else None,
                    "low": lows[i] if i < len(lows) else None,
                    "close": closes[i] if i < len(closes) else None,
                    "volume": vols[i] if i < len(vols) else None,
                    "source": "finnhub",
                }
            )
        return out

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get("/quote", params={"symbol": ticker.upper()})
        price = data.get("c")
        prev = data.get("pc")
        change_pct = None
        if price is not None and prev:
            try:
                change_pct = (float(price) - float(prev)) / float(prev) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                change_pct = None
        return {
            "ticker": ticker.upper(),
            "price": float(price) if price is not None else None,
            "open": float(data["o"]) if data.get("o") is not None else None,
            "high": float(data["h"]) if data.get("h") is not None else None,
            "low": float(data["l"]) if data.get("l") is not None else None,
            "change_pct": change_pct,
            "timestamp": datetime.fromtimestamp(data["t"], tz=timezone.utc).isoformat()
            if data.get("t")
            else datetime.now(timezone.utc).isoformat(),
            "source": "finnhub",
        }

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for ticker, result in zip(tickers, results):
            if not isinstance(result, Exception):
                out[ticker] = result
        return out

    async def get_company_news(
        self,
        symbol: str,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Finnhub company-news (requires symbol + from/to dates)."""
        from datetime import timedelta

        end = to_date or datetime.now(timezone.utc)
        start = from_date or (end - timedelta(days=7))
        try:
            data = await self._get_any(
                "/company-news",
                params={
                    "symbol": symbol.upper(),
                    "from": start.strftime("%Y-%m-%d"),
                    "to": end.strftime("%Y-%m-%d"),
                },
            )
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            logger.warning(
                "Finnhub company-news failed",
                symbol=symbol,
                error=redact_secrets(str(exc)),
            )
            return []
        rows = data if isinstance(data, list) else []
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("headline") or row.get("title") or "").strip()
            if not title:
                continue
            ts = row.get("datetime")
            if isinstance(ts, (int, float)) and ts > 0:
                published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            else:
                published = datetime.now(timezone.utc).isoformat()
            related = str(row.get("related") or symbol).upper()
            symbols = [s.strip() for s in related.split(",") if s.strip()] or [symbol.upper()]
            out.append(
                {
                    "title": title,
                    "summary": row.get("summary"),
                    "source": str(row.get("source") or "finnhub"),
                    "url": str(row.get("url") or ""),
                    "published_at": published,
                    "symbols": symbols,
                    "provider": "finnhub",
                }
            )
        return out

    async def get_news(
        self,
        symbols: list[str] | None = None,
        *,
        limit: int = 20,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate Finnhub company-news across symbols (newest first)."""
        clean = _equity_news_symbols(symbols) or ["AAPL", "MSFT", "NVDA", "SPY"]
        per = max(3, limit // max(len(clean[:4]), 1))
        collected: list[dict[str, Any]] = []
        for sym in clean[:4]:
            rows = await self.get_company_news(
                sym, from_date=from_date, to_date=to_date, limit=per
            )
            collected.extend(rows)
            if len(collected) >= limit:
                break
        collected.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
        return collected[:limit]


# ── CoinGecko (crypto supplement) ─────────────────────────────────────────────

class CoinGeckoClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self) -> None:
        self._api_key = (settings.COINGECKO_API_KEY or "").strip()

    def _auth_query(self) -> dict[str, str]:
        """Dashboard Demo keys: query only. Do not send x-cg-*-api-key headers (ignored)."""
        if not self._api_key:
            return {}
        if self._api_key.lower().startswith("cg-"):
            return {"x_cg_demo_api_key": self._api_key}
        return {"x_cg_pro_api_key": self._api_key}

    @property
    def _base(self) -> str:
        if self._api_key.lower().startswith("cg-") or not self._api_key:
            return "https://api.coingecko.com/api/v3"
        return "https://pro-api.coingecko.com/api/v3"

    def _coin_id(self, ticker: str) -> str | None:
        raw = ticker.strip().upper().replace("/", "-")
        return _COINGECKO_IDS.get(raw) or _COINGECKO_IDS.get(raw.split("-")[0])

    async def _get(self, path: str, params: dict | None = None) -> Any:
        for attempt in range(MAX_RETRIES):
            try:
                async with _foreign_client() as client:
                    query = dict(params or {})
                    query.update(self._auth_query())
                    resp = await client.get(
                        f"{self._base}{path}",
                        params=query,
                    )
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

    async def _resolve_coin_id(self, ticker: str) -> str | None:
        mapped = self._coin_id(ticker)
        if mapped:
            return mapped
        q = ticker.split("-")[0].split("/")[0].strip()
        if not q:
            return None
        try:
            data = await self._get("/search", params={"query": q})
        except Exception as exc:
            logger.warning("coingecko search failed", query=q, error=str(exc)[:200])
            return None
        coins = data.get("coins") if isinstance(data, dict) else None
        if not coins:
            return None
        want = q.upper()
        for row in coins:
            if str(row.get("symbol") or "").upper() == want:
                return str(row.get("id") or "") or None
        return str(coins[0].get("id") or "") or None

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        coin_id = await self._resolve_coin_id(ticker)
        if not coin_id:
            return []
        days = max(1, int((end - start).total_seconds() / 86400) or 1)
        days = min(days, 180)
        try:
            rows = await self._get(
                f"/coins/{coin_id}/ohlc",
                params={"vs_currency": "usd", "days": days},
            )
        except Exception as exc:
            logger.warning("coingecko ohlc failed", coin_id=coin_id, error=str(exc)[:200])
            return []
        out: list[dict[str, Any]] = []
        if isinstance(rows, list) and rows and isinstance(rows[0], list) and len(rows[0]) >= 5:
            for row in rows:
                ts_ms, o, h, low, c = row[0], row[1], row[2], row[3], row[4]
                out.append(
                    {
                        "timestamp": datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).isoformat(),
                        "open": float(o),
                        "high": float(h),
                        "low": float(low),
                        "close": float(c),
                        "volume": None,
                        "source": "coingecko",
                    }
                )
            return out
        data = await self._get(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": min(days, 365)},
        )
        prices = data.get("prices") or []
        for row in prices:
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts_ms, price = int(row[0]), float(row[1])
            out.append(
                {
                    "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": None,
                    "source": "coingecko",
                }
            )
        return out

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        coin_id = await self._resolve_coin_id(ticker)
        if not coin_id:
            return {"ticker": ticker.upper(), "price": None, "source": "coingecko"}
        data = await self._get(
            "/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
            },
        )
        row = (data or {}).get(coin_id) or {}
        price = row.get("usd")
        return {
            "ticker": ticker.upper(),
            "price": float(price) if price is not None else None,
            "volume": float(row["usd_24h_vol"]) if row.get("usd_24h_vol") is not None else None,
            "change_pct": float(row["usd_24h_change"])
            if row.get("usd_24h_change") is not None
            else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "coingecko",
        }

    async def trending(self) -> dict[str, Any]:
        try:
            return await self._get("/search/trending") or {}
        except Exception as exc:
            logger.warning("coingecko trending failed", error=str(exc)[:200])
            return {}

    async def onchain_trending_pools(self) -> list[dict[str, Any]]:
        try:
            data = await self._get("/onchain/networks/trending_pools")
        except Exception as exc:
            logger.warning("coingecko onchain pools failed", error=str(exc)[:200])
            data = None
        if not data:
            try:
                kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(8.0, connect=3.0))
                async with httpx.AsyncClient(**kwargs) as client:
                    resp = await client.get(
                        "https://api.geckoterminal.com/api/v2/networks/trending_pools",
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                logger.warning("geckoterminal trending pools failed", error=str(exc)[:200])
                return []
        if isinstance(data, dict):
            return list(data.get("data") or [])[:20]
        return []

    async def get_multiple_quotes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        tasks = [self.get_latest_quote(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for ticker, result in zip(tickers, results):
            if not isinstance(result, Exception):
                out[ticker] = result
        return out
