"""
Investing.com market-intelligence provider via RapidAPI.

Uses the "Investing.Com Ultimate API" (host
``investing-com-ultimate-api.p.rapidapi.com``) to pull:

* economic-calendar events (rate decisions, CPI, GDP, payrolls…)
* financial quotes for a symbol
* earnings-calendar entries where available

All results are normalized into the same event/quote dict shape the rest of
the intelligence pipeline consumes (compatible with ``app.services.macro`` and
``app.services.news``). Every network call is defensive: a missing key,
non-200 response, or transport error returns an empty result instead of
raising, so the pipeline degrades gracefully when the provider is unavailable
or rate-limited.

No credentials are hard-coded — the RapidAPI key is read from settings /
environment (``RAPIDAPI_KEY``) and never logged.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Impact string -> signed market-effect magnitude used by the scoring blend.
_IMPACT_WEIGHT: dict[str, float] = {
    "high": 0.6,
    "3": 0.6,
    "medium": 0.3,
    "2": 0.3,
    "low": 0.1,
    "1": 0.1,
}


def is_configured() -> bool:
    """True when the provider has a key and is enabled."""
    return bool(settings.RAPIDAPI_KEY) and settings.INVESTING_RAPIDAPI_ENABLED


def _headers() -> dict[str, str]:
    return {
        "x-rapidapi-key": settings.RAPIDAPI_KEY,
        "x-rapidapi-host": settings.INVESTING_RAPIDAPI_HOST,
    }


def _base_url() -> str:
    return f"https://{settings.INVESTING_RAPIDAPI_HOST}"


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(float(settings.INVESTING_RAPIDAPI_TIMEOUT_SECONDS), connect=5.0)


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Single GET against the RapidAPI host with retry/backoff on 429.

    Returns the decoded JSON payload, or ``None`` on any failure.
    """
    if not is_configured():
        logger.debug("Investing RapidAPI not configured, skipping", path=path)
        return None

    url = f"{_base_url()}{path}"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=_timeout()) as client:
                resp = await client.get(url, params=params or {}, headers=_headers())
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429 and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.warning("Investing RapidAPI error", path=path, status=status_code)
            return None
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning("Investing RapidAPI request failed", path=path, attempt=attempt, error=str(exc))
            if attempt == 2:
                return None
            await asyncio.sleep(2 ** attempt)
    return None


# ── Normalization helpers ────────────────────────────────────────────────────

def _as_list(payload: Any, *keys: str) -> list[dict[str, Any]]:
    """Extract a list of dict rows from a variety of RapidAPI envelope shapes."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        # Fall back to the first list-valued field.
        for value in payload.values():
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _first(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _impact_to_effect(impact: Any, forecast: Any = None, previous: Any = None) -> float:
    """Signed market effect in [-1, 1] from impact + forecast/previous delta."""
    magnitude = _IMPACT_WEIGHT.get(str(impact).strip().lower(), 0.25)
    direction = 0.0
    try:
        if forecast is not None and previous is not None:
            f = float(str(forecast).replace("%", "").replace(",", ""))
            p = float(str(previous).replace("%", "").replace(",", ""))
            if f > p:
                direction = 1.0
            elif f < p:
                direction = -1.0
    except (TypeError, ValueError):
        direction = 0.0
    # Even without a delta, high-impact events carry a small positive prior of
    # "something is happening" -> we keep magnitude but neutral direction.
    return round(magnitude * direction, 4)


def _normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    name = _first(row, "event", "event_name", "title", "name", default="economic event")
    impact = _first(row, "importance", "impact", "volatility", default="medium")
    forecast = _first(row, "forecast", "estimate", "consensus", "fcst", "expected")
    previous = _first(row, "previous", "prev", "prior")
    actual = _first(row, "actual", "actual_value", "actualValue", "act")
    country = _first(row, "country", "zone", "currency", default="GLOBAL")
    event_date = _first(row, "date", "event_date", "time", "timestamp", default=None)
    impact_str = str(impact).strip().lower()
    impact_label = "high" if impact_str in ("high", "3") else ("medium" if impact_str in ("medium", "2") else "low")
    return {
        "event_name": str(name),
        "event_date": event_date,
        "country": str(country),
        "impact": impact_label,
        "actual": actual,
        "estimate": forecast,
        "previous": previous,
        "source": "investing_rapidapi",
        "market_effect": _impact_to_effect(impact, forecast, previous),
        "confidence": 0.8 if impact_label == "high" else (0.6 if impact_label == "medium" else 0.4),
        "tickers_affected": [],
    }


# ── Public fetchers ──────────────────────────────────────────────────────────

async def fetch_economic_events(days_ahead: int | None = None) -> list[dict[str, Any]]:
    """Fetch upcoming economic-calendar events (US + RU + EU), normalized."""
    lookahead = days_ahead or settings.INVESTING_EVENTS_LOOKAHEAD_DAYS
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=lookahead)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for country in ("US", "RU", "EU"):
        params = {"from": today.isoformat(), "to": end.isoformat(), "country": country}
        payload = await _get("/economic-calendar/", params=params)
        rows = _as_list(payload, "data", "events", "economicCalendar", "result")
        for row in rows:
            event = _normalize_event(row)
            key = f"{event.get('event_name')}|{event.get('event_date')}|{event.get('country')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(event)
    if merged:
        logger.debug("Investing economic events fetched", count=len(merged))
    return merged


async def fetch_quote(symbol: str) -> dict[str, Any] | None:
    """Fetch a single financial quote for ``symbol`` (best-effort)."""
    if not symbol:
        return None
    payload = await _get("/quotes/", params={"symbol": symbol})
    rows = _as_list(payload, "data", "quotes", "result")
    row = rows[0] if rows else (payload if isinstance(payload, dict) else None)
    if not isinstance(row, dict):
        return None
    price = _first(row, "last", "price", "close", "value")
    change_pct = _first(row, "change_percent", "changePercent", "pct_change", "chg_pct")
    try:
        price_f = float(str(price).replace(",", "")) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    try:
        change_f = float(str(change_pct).replace("%", "").replace(",", "")) if change_pct is not None else None
    except (TypeError, ValueError):
        change_f = None
    return {
        "symbol": symbol,
        "price": price_f,
        "change_percent": change_f,
        "source": "investing_rapidapi",
    }


async def fetch_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch quotes for several symbols. Returns ``{symbol: quote}``."""
    quotes: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        quote = await fetch_quote(symbol)
        if quote is not None:
            quotes[symbol] = quote
    return quotes


async def fetch_earnings(days_ahead: int | None = None) -> list[dict[str, Any]]:
    """Fetch upcoming earnings-calendar entries (best-effort; may be empty)."""
    lookahead = days_ahead or settings.INVESTING_EVENTS_LOOKAHEAD_DAYS
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=lookahead)
    payload = await _get(
        "/earnings-calendar/",
        params={"from": today.isoformat(), "to": end.isoformat()},
    )
    rows = _as_list(payload, "data", "earnings", "earningsCalendar", "result")
    events: list[dict[str, Any]] = []
    for row in rows:
        symbol = _first(row, "symbol", "ticker", default="")
        name = _first(row, "company", "name", "event", default=symbol or "earnings")
        events.append({
            "event_name": f"Earnings: {name}",
            "event_date": _first(row, "date", "event_date", "time", default=None),
            "country": _first(row, "country", default="US"),
            "impact": "high",
            "source": "investing_rapidapi",
            "event_type": "earnings",
            "market_effect": 0.0,
            "confidence": 0.6,
            "tickers_affected": [str(symbol).upper()] if symbol else [],
            "eps_estimate": _first(row, "eps_estimate", "epsEstimate", "eps_forecast"),
        })
    return events


async def fetch_market_intelligence(
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate economic events + earnings + quotes into one payload.

    Returns ``{"events": [...], "earnings": [...], "quotes": {...},
    "configured": bool}``. Safe to call unconditionally — returns empty
    collections when the provider is not configured.
    """
    if not is_configured():
        return {"events": [], "earnings": [], "quotes": {}, "configured": False}

    events, earnings = await asyncio.gather(
        fetch_economic_events(),
        fetch_earnings(),
    )
    quotes = await fetch_quotes(symbols or []) if symbols else {}
    return {
        "events": events,
        "earnings": earnings,
        "quotes": quotes,
        "configured": True,
    }
