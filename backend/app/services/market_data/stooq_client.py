"""Stooq daily bars — optional cookie/apikey from env; soft-fail without auth."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

STOOQ_DAILY = "https://stooq.com/q/d/l/"

_BROWSER_HEADERS = {
    "Accept": "text/csv,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stooq.com/q/d/",
}


def stooq_symbol(ticker: str) -> str:
    raw = ticker.strip().lower().replace("-", ".")
    if raw.endswith(".us") or raw.endswith(".uk") or raw.endswith(".de") or raw.endswith(".jp"):
        return raw
    if "." in raw:
        return raw
    return f"{raw}.us"


def _stooq_request_params(symbol: str) -> dict[str, str]:
    params = {"s": symbol, "i": "d"}
    key = (settings.STOOQ_API_KEY or "").strip()
    if key:
        params["apikey"] = key
    return params


def _stooq_headers() -> dict[str, str]:
    headers = dict(_BROWSER_HEADERS)
    cookie = (settings.STOOQ_COOKIE or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    return headers


class StooqClient:
    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        if timeframe not in {"1d", "1w", "1wk"}:
            return []
        symbol = stooq_symbol(ticker)
        kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(12.0, connect=4.0))
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.get(
                    STOOQ_DAILY,
                    params=_stooq_request_params(symbol),
                    headers=_stooq_headers(),
                )
                # Stooq often returns 404 without apikey/session — soft-fail.
                if resp.status_code in {401, 403, 404}:
                    logger.debug("stooq_unavailable", ticker=ticker, status=resp.status_code)
                    return []
                resp.raise_for_status()
                text = resp.text.strip()
        except Exception as exc:
            logger.debug("stooq_bars_failed", ticker=ticker, error=str(exc)[:160])
            return []
        if "Exceeded the daily hits limit" in text:
            return []
        if "JavaScript to verify your browser" in text or "cf-browser-verification" in text.lower():
            logger.debug("stooq_cloudflare_block", ticker=ticker)
            return []
        lines = text.splitlines()
        if len(lines) < 2 or "Date" not in lines[0]:
            return []
        out: list[dict[str, Any]] = []
        start_d = start.date()
        end_d = end.date()
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                day = datetime.strptime(parts[0], "%Y-%m-%d").date()
                if day < start_d or day > end_d:
                    continue
                ts = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
                out.append(
                    {
                        "timestamp": ts.isoformat(),
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": float(parts[5]) if parts[5] not in {"", "0"} else 0.0,
                        "source": "stooq",
                    }
                )
            except ValueError:
                continue
        return out

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end.replace(year=end.year - 1)
        bars = await self.get_bars(ticker, "1d", start, end)
        if not bars:
            return {"ticker": ticker.upper(), "price": None, "source": "stooq"}
        last = bars[-1]
        prev = bars[-2]["close"] if len(bars) > 1 else last["close"]
        close = float(last["close"])
        change = ((close - prev) / prev * 100.0) if prev else None
        return {
            "ticker": ticker.upper(),
            "price": close,
            "change_pct": change,
            "volume": last.get("volume"),
            "source": "stooq",
        }
