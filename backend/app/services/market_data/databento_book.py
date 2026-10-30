"""US order book from Databento: Nasdaq TotalView depth (10 levels) at the close of a past session.

Live US depth for display to clients needs an exchange distribution licence
(Databento Plus, $1,750/month). Historical data is pay-as-you-go and most
datasets may be shown after 24 hours, so we show the real Nasdaq book as it
stood at the close of the latest session that ended more than 24 hours ago,
clearly labelled as a recording. One snapshot per symbol per session, cached on
disk, costs a fraction of a cent.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import get_logger
from app.services.trading_keys.platform_keys import platform_env

logger = get_logger(__name__)

HIST_URL = "https://hist.databento.com/v0/timeseries.get_range"
DATASET = "XNAS.ITCH"
NY = ZoneInfo("America/New_York")
_NEG_CACHE: dict[str, datetime] = {}


def configured() -> bool:
    return bool(platform_env("DATABENTO_API_KEY"))


def session_for(now: datetime | None = None) -> date:
    """Latest weekday session whose 16:00 New York close is at least 24 hours old."""
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    day = now.date()
    for _ in range(10):
        close = datetime.combine(day, time(16, 0), tzinfo=NY)
        if day.weekday() < 5 and now - close >= timedelta(hours=24):
            return day
        day -= timedelta(days=1)
    return day


def _px(v: Any) -> float | None:
    if v in (None, "", "null"):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if abs(f) > 1e7:  # fixed-point 1e-9 when pretty_px is off
        f = f / 1e9
    return f if f > 0 else None


def parse_mbp10(text: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]], str | None]:
    """First MBP-10 JSON record → (bids, asks, ts)."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        bids: list[tuple[float, float]] = []
        asks: list[tuple[float, float]] = []
        for lvl in rec.get("levels") or []:
            bp, ap = _px(lvl.get("bid_px")), _px(lvl.get("ask_px"))
            if bp and lvl.get("bid_sz"):
                bids.append((bp, float(lvl["bid_sz"])))
            if ap and lvl.get("ask_sz"):
                asks.append((ap, float(lvl["ask_sz"])))
        ts = (rec.get("hd") or {}).get("ts_event") or rec.get("ts_recv")
        return bids, asks, str(ts) if ts is not None else None
    return [], [], None


async def close_book(symbol: str) -> dict[str, Any] | None:
    """{"bids","asks","session","ts"} or None. Cached per symbol and session."""
    key = platform_env("DATABENTO_API_KEY")
    if not key:
        return None
    from app.services.price_history import store

    sym = symbol.upper()
    session = session_for()
    cache_key = f"L2_{sym}"
    cached = store.read(cache_key) or {}
    if cached.get("session") == session.isoformat() and cached.get("bids"):
        return cached
    miss = _NEG_CACHE.get(sym)
    if miss and datetime.now(timezone.utc) - miss < timedelta(hours=6):
        return None
    start = datetime.combine(session, time(15, 59, 50), tzinfo=NY).astimezone(timezone.utc)
    params = {
        "dataset": DATASET,
        "symbols": sym,
        "schema": "mbp-10",
        "stype_in": "raw_symbol",
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": (start + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        "encoding": "json",
        "pretty_px": "true",
        "pretty_ts": "true",
        "limit": "1",
    }
    try:
        from app.core.http_proxy import httpx_client_kwargs

        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(20.0, connect=5.0))) as client:
            resp = await client.get(HIST_URL, params=params, auth=(key, ""))
        if resp.status_code != 200:
            logger.info("databento_book_skip", symbol=sym, status=resp.status_code, body=resp.text[:200])
            _NEG_CACHE[sym] = datetime.now(timezone.utc)
            return None
        bids, asks, ts = parse_mbp10(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("databento_book_failed", symbol=sym, error=str(exc)[:200])
        _NEG_CACHE[sym] = datetime.now(timezone.utc)
        return None
    if not bids or not asks:
        _NEG_CACHE[sym] = datetime.now(timezone.utc)
        return None
    out = {"bids": bids, "asks": asks, "session": session.isoformat(), "ts": ts, "dataset": DATASET}
    store.write(cache_key, out)
    return out
