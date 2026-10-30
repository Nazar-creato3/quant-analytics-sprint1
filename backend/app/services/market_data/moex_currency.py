"""
MOEX currency section (CETS board) — USD/RUB, EUR/RUB, CNY/RUB and other RUB pairs.

Data via MOEX ISS engine=currency/markets=selt/boards=CETS.
Trading routes through the existing T-Bank (Tinkoff Invest) broker gateway.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_QUOTE_CACHE_PREFIX = "quote:moex_fx:"
_QUOTE_CACHE_TTL = 15

MOEX_CETS_SECURITIES_URL = (
    "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/{ticker}.json"
)
MOEX_CETS_ORDERBOOK_URL = (
    "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/{ticker}/orderbook.json"
)
MOEX_CETS_CANDLES_URL = (
    "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/{ticker}/candles.json"
)

# SECID -> display name (Finam-style «Валюты» tab)
_MOEX_CURRENCY_UNIVERSE: dict[str, dict[str, str]] = {
    "USD000UTSTOM": {"name": "USD/RUB TOM", "pair": "USD/RUB", "base": "USD", "quote": "RUB"},
    "USD000000TOD": {"name": "USD/RUB TOD", "pair": "USD/RUB", "base": "USD", "quote": "RUB"},
    "EUR000UTSTOM": {"name": "EUR/RUB TOM", "pair": "EUR/RUB", "base": "EUR", "quote": "RUB"},
    "EUR000000TOD": {"name": "EUR/RUB TOD", "pair": "EUR/RUB", "base": "EUR", "quote": "RUB"},
    "CNY000000TOD": {"name": "CNY/RUB TOD", "pair": "CNY/RUB", "base": "CNY", "quote": "RUB"},
    "CNY000UTSTOM": {"name": "CNY/RUB TOM", "pair": "CNY/RUB", "base": "CNY", "quote": "RUB"},
    "GBP000UTSTOM": {"name": "GBP/RUB TOM", "pair": "GBP/RUB", "base": "GBP", "quote": "RUB"},
    "HKD000UTSTOM": {"name": "HKD/RUB TOM", "pair": "HKD/RUB", "base": "HKD", "quote": "RUB"},
    "TRY000UTSTOM": {"name": "TRY/RUB TOM", "pair": "TRY/RUB", "base": "TRY", "quote": "RUB"},
    "KZT000UTSTOM": {"name": "KZT/RUB TOM", "pair": "KZT/RUB", "base": "KZT", "quote": "RUB"},
    "CHF000UTSTOM": {"name": "CHF/RUB TOM", "pair": "CHF/RUB", "base": "CHF", "quote": "RUB"},
}

# User-facing aliases -> canonical MOEX SECID
_CURRENCY_ALIASES: dict[str, str] = {
    "USDRUB": "USD000UTSTOM",
    "USD/RUB": "USD000UTSTOM",
    "USD-RUB": "USD000UTSTOM",
    "EURRUB": "EUR000UTSTOM",
    "EUR/RUB": "EUR000UTSTOM",
    "EUR-RUB": "EUR000UTSTOM",
    "CNYRUB": "CNY000UTSTOM",
    "CNY/RUB": "CNY000UTSTOM",
    "CNY-RUB": "CNY000UTSTOM",
    "GBPRUB": "GBP000UTSTOM",
    "GBP/RUB": "GBP000UTSTOM",
    "HKDRUB": "HKD000UTSTOM",
    "HKD/RUB": "HKD000UTSTOM",
    "TRYRUB": "TRY000UTSTOM",
    "TRY/RUB": "TRY000UTSTOM",
    "KZTRUB": "KZT000UTSTOM",
    "KZT/RUB": "KZT000UTSTOM",
    "CHFRUB": "CHF000UTSTOM",
    "CHF/RUB": "CHF000UTSTOM",
}

_MOEX_CURRENCY_SECIDS = frozenset(_MOEX_CURRENCY_UNIVERSE.keys())

# T-Bank FIGI cache (same channel as MOEX equities historical_data)
_TINKOFF_FIGI_BY_SECID: dict[str, str] = {
    "USD000UTSTOM": "BBG0013HGFT4",
    "EUR000UTSTOM": "BBG0013HJJ31",
    "CNY000000TOD": "BBG0013HRTL7",
    "CNY000UTSTOM": "BBG0013HRTL7",
    "GBP000UTSTOM": "BBG0013HGT09",
    "HKD000UTSTOM": "BBG0013HKC36",
}

# Default trading constraints for MOEX CETS (overridden by ISS metadata when available)
_DEFAULT_CURRENCY_RULES: dict[str, float] = {
    "tick_size": 0.0025,
    "lot_size": 1000.0,
    "min_qty": 1000.0,
}


def list_moex_currency_instruments() -> list[dict[str, str]]:
    """Return seed rows for direct-deals symbol universe."""
    rows: list[dict[str, str]] = []
    for secid, meta in _MOEX_CURRENCY_UNIVERSE.items():
        rows.append(
            {
                "symbol": secid,
                "name": meta["name"],
                "exchange": "MOEX",
                "pair": meta["pair"],
            }
        )
    return rows


def normalize_moex_currency_symbol(ticker: str) -> str:
    """Map alias (USD/RUB, USDRUB) or SECID to canonical MOEX currency SECID."""
    raw = ticker.strip().upper()
    if not raw:
        return raw
    if raw in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[raw]
    if raw in _MOEX_CURRENCY_SECIDS:
        return raw
    # Compact pair without separator: USDRUB, EURRUB
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    if compact in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[compact]
    return raw


def is_moex_currency_ticker(ticker: str) -> bool:
    """True for known MOEX CETS currency SECIDs and common pair aliases."""
    bare = normalize_moex_currency_symbol(ticker)
    if bare in _MOEX_CURRENCY_SECIDS:
        return True
    raw = ticker.strip().upper()
    return raw in _CURRENCY_ALIASES or re.sub(r"[^A-Z0-9]", "", raw) in _CURRENCY_ALIASES


def currency_display_name(secid: str) -> str | None:
    meta = _MOEX_CURRENCY_UNIVERSE.get(normalize_moex_currency_symbol(secid))
    return meta["name"] if meta else None


def currency_pair_label(secid: str) -> str | None:
    meta = _MOEX_CURRENCY_UNIVERSE.get(normalize_moex_currency_symbol(secid))
    return meta.get("pair") if meta else None


def tinkoff_figi_for_currency(secid: str) -> str | None:
    bare = normalize_moex_currency_symbol(secid)
    return _TINKOFF_FIGI_BY_SECID.get(bare)


def quote_cache_key(ticker: str) -> str:
    return f"{_QUOTE_CACHE_PREFIX}{normalize_moex_currency_symbol(ticker)}"


async def _fetch_cets_quote(secid: str) -> dict[str, Any] | None:
    bare = normalize_moex_currency_symbol(secid)
    url = MOEX_CETS_SECURITIES_URL.format(ticker=bare)
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
            resp = await client.get(url, params={"iss.meta": "off"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("MOEX CETS quote failed", ticker=bare, error=str(exc))
        return None

    marketdata = data.get("marketdata", {})
    columns = marketdata.get("columns", [])
    rows = marketdata.get("data", [])
    if not rows:
        return None

    record = dict(zip(columns, rows[0]))
    last = record.get("LAST") or record.get("LCURRENTPRICE") or record.get("MARKETPRICE")
    if last is None:
        securities = data.get("securities", {})
        sec_cols = securities.get("columns", [])
        for sec_row in securities.get("data", []):
            sec = dict(zip(sec_cols, sec_row))
            prev = sec.get("PREVPRICE") or sec.get("PREVLEGALCLOSEPRICE")
            if prev is not None:
                last = prev
                break
    if last is None:
        return None

    price = float(last)
    if price <= 0:
        return None

    bid = record.get("BID")
    ask = record.get("OFFER")
    change_pct = record.get("LASTTOPREVPRICE")
    lot = record.get("LOTSIZE") or record.get("LOT_SIZE")
    min_step = record.get("MINSTEP") or record.get("MIN_STEP")

    meta = _MOEX_CURRENCY_UNIVERSE.get(bare, {})
    return {
        "ticker": bare,
        "price": price,
        "bid": float(bid) if bid else None,
        "ask": float(ask) if ask else None,
        "volume": float(record.get("VOLTODAY") or 0),
        "change_pct": float(change_pct) if change_pct is not None else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "moex_cets",
        "exchange": "MOEX",
        "board": "CETS",
        "instrument_class": "currency",
        "currency": "RUB",
        "pair": meta.get("pair"),
        "lot_size": float(lot) if lot else _DEFAULT_CURRENCY_RULES["lot_size"],
        "min_step": float(min_step) if min_step else _DEFAULT_CURRENCY_RULES["tick_size"],
        "name": meta.get("name"),
    }


async def get_moex_currency_quote(ticker: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
    if not is_moex_currency_ticker(ticker):
        return None
    bare = normalize_moex_currency_symbol(ticker)
    cache_key = quote_cache_key(bare)

    if not force_refresh:
        cached = await cache_get(cache_key)
        if cached and cached.get("price") is not None:
            out = dict(cached)
            out.setdefault("source", "moex_fx_cached")
            return out

    quote = await _fetch_cets_quote(bare)
    if quote and quote.get("price") is not None:
        await cache_set(cache_key, quote, ttl=_QUOTE_CACHE_TTL)
    return quote


async def get_moex_currency_bars(
    ticker: str,
    timeframe: str = "1d",
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not is_moex_currency_ticker(ticker):
        return []
    bare = normalize_moex_currency_symbol(ticker)
    end = datetime.now(timezone.utc).date()
    days_back = max(365, limit * 2) if timeframe == "1d" else 60
    start = end - timedelta(days=days_back)
    interval = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "60", "1d": "24"}.get(timeframe, "24")

    url = MOEX_CETS_CANDLES_URL.format(ticker=bare)
    params = {
        "from": start.isoformat(),
        "till": end.isoformat(),
        "interval": interval,
        "iss.meta": "off",
    }
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("MOEX CETS bars failed", ticker=bare, error=str(exc))
        return []

    candles = payload.get("candles", {})
    columns = candles.get("columns", [])
    rows = candles.get("data", [])
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
    return bars[-limit:]


async def fetch_moex_currency_rules(secid: str) -> dict[str, float]:
    """Lot/tick from ISS or sensible CETS defaults."""
    quote = await _fetch_cets_quote(secid)
    if quote:
        return {
            "tick_size": float(quote.get("min_step") or _DEFAULT_CURRENCY_RULES["tick_size"]),
            "lot_size": float(quote.get("lot_size") or _DEFAULT_CURRENCY_RULES["lot_size"]),
            "min_qty": float(quote.get("lot_size") or _DEFAULT_CURRENCY_RULES["min_qty"]),
        }
    return dict(_DEFAULT_CURRENCY_RULES)
