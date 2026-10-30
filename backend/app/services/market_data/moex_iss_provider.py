"""MOEX ISS fundamentals and history via apimoex."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import apimoex
import requests

from app.core.logging import get_logger
from app.services.market_data.moex_spot import (
    get_moex_quote,
    is_moex_ticker,
    normalize_moex_symbol,
)

logger = get_logger(__name__)

MOEX_BOARD = "TQBR"
MOEX_INDEX_SYMBOLS = frozenset({"IMOEX", "RTSI", "MOEXBC", "MOEXOG", "MOEXFN"})
MOEX_INDEX_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/index/securities/{ticker}.json"
)
MOEX_INDEX_HISTORY_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{ticker}.json"
)
TQBR_SECURITIES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
)
SECURITY_DETAIL_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
)

# apimoex.ISSClient always merges BASE_QUERY (iss.json, iss.meta). Duplicating those keys
# raises TypeError on Python 3.14+ and breaks all ISSClient calls silently in prod.
_APMOEX_BASE_KEYS = frozenset({"iss.json", "iss.meta"})


def _iss_client_args(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """ISSClient query args without keys already supplied by apimoex BASE_QUERY."""
    args = dict(extra or {})
    for key in _APMOEX_BASE_KEYS:
        args.pop(key, None)
    return args


def _parse_iss_extended_table(block: Any) -> list[dict[str, Any]]:
    """Normalize ISS extended-json table to list[dict] (apimoex-style or raw ISS)."""
    if isinstance(block, list):
        return [row for row in block if isinstance(row, dict)]
    if not isinstance(block, dict):
        return []
    rows = block.get("data") or []
    columns = block.get("columns") or []
    if not rows or not columns:
        return []
    return [dict(zip(columns, row)) for row in rows]


def _parse_iss_extended_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """Parse ISS extended json into {table_name: [row_dict, ...]}."""
    if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], dict):
        raw = payload[1]
    elif isinstance(payload, dict):
        raw = payload
    else:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key, block in raw.items():
        parsed = _parse_iss_extended_table(block)
        if parsed:
            out[key] = parsed
    return out


def _build_session() -> requests.Session:
    """Build requests session with platform MOEX credentials."""
    from app.services.market_data.moex_iss_client import build_requests_session

    return build_requests_session()


def is_moex_index(ticker: str) -> bool:
    bare = normalize_moex_symbol(ticker)
    return bare in MOEX_INDEX_SYMBOLS


def _fetch_index_marketdata_sync(session: requests.Session, ticker: str) -> list[dict[str, Any]]:
    """Fetch index marketdata rows — apimoex first, direct ISS GET as fallback."""
    bare = normalize_moex_symbol(ticker)
    url = MOEX_INDEX_URL.format(ticker=bare)
    query = _iss_client_args(
        {
            "iss.only": "marketdata",
            "marketdata.columns": "SECID,LAST,CURRENTVALUE,LASTTOPREVPRICE,TIME",
        }
    )
    try:
        iss = apimoex.ISSClient(session, url, query)
        payload = iss.get()
        rows = payload.get("marketdata") or []
        if rows:
            return rows
    except Exception as exc:
        logger.debug("apimoex index marketdata failed", ticker=bare, error=str(exc))

    params = {
        "iss.json": "extended",
        "iss.meta": "off",
        "iss.only": "marketdata",
        "marketdata.columns": "SECID,LAST,CURRENTVALUE,LASTTOPREVPRICE,TIME",
    }
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    tables = _parse_iss_extended_payload(resp.json())
    return tables.get("marketdata") or []


def _index_change_pct_from_history_sync(session: requests.Session, ticker: str, current: float) -> float | None:
    """Derive daily % change from last two index history closes when live field is absent."""
    if current <= 0:
        return None
    bare = normalize_moex_symbol(ticker)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=14)
    url = MOEX_INDEX_HISTORY_URL.format(ticker=bare)
    params = {
        "iss.json": "extended",
        "iss.meta": "off",
        "from": start.isoformat(),
        "till": end.isoformat(),
        "history.columns": "TRADEDATE,CLOSE",
    }
    try:
        resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        rows = _parse_iss_extended_payload(resp.json()).get("history") or []
    except Exception as exc:
        logger.debug("MOEX index history for change_pct failed", ticker=ticker, error=str(exc))
        return None

    closes: list[float] = []
    for row in rows:
        close = row.get("CLOSE")
        if close is None:
            continue
        try:
            val = float(close)
        except (TypeError, ValueError):
            continue
        if val > 0:
            closes.append(val)
    if len(closes) < 2:
        return None
    prev, last = closes[-2], current
    if prev <= 0:
        return None
    return round((last / prev - 1.0) * 100.0, 4)


def _fetch_index_quote_sync(ticker: str) -> dict[str, Any] | None:
    """Live MOEX index level (IMOEX, RTSI, …) via ISS index market + apimoex."""
    bare = normalize_moex_symbol(ticker)
    if bare not in MOEX_INDEX_SYMBOLS:
        return None
    with _build_session() as session:
        rows = _fetch_index_marketdata_sync(session, bare)
        if not rows:
            return None
        row = rows[0]
        price = row.get("LAST") or row.get("CURRENTVALUE")
        if price is None:
            return None
        price_f = float(price)
        if price_f <= 0:
            return None
        chg_pct = row.get("LASTTOPREVPRICE")
        change_pct = float(chg_pct) if chg_pct is not None else None
        if change_pct is None:
            change_pct = _index_change_pct_from_history_sync(session, bare, price_f)
    return {
        "ticker": bare,
        "symbol": bare,
        "price": price_f,
        "change_pct": change_pct,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "moex_iss_index",
        "exchange": "MOEX",
        "currency": "RUB",
    }


async def fetch_moex_index_quote(symbol: str) -> dict[str, Any] | None:
    """Public async wrapper for MOEX index quotes (no API key)."""
    if not is_moex_index(symbol):
        return None
    try:
        return await asyncio.to_thread(_fetch_index_quote_sync, symbol)
    except Exception as exc:
        logger.warning("MOEX index quote failed", symbol=symbol, error=str(exc))
        return None


def _fetch_security_detail_sync(ticker: str) -> dict[str, Any]:
    """Fetch TQBR security row with capitalization and reference fields."""
    bare = normalize_moex_symbol(ticker)
    url = SECURITY_DETAIL_URL.format(ticker=bare)
    arguments = _iss_client_args(
        {
            "securities.columns": (
                "SECID,SHORTNAME,LOTSIZE,ISSUESIZE,ISSUECAPITALIZATION,"
                "PREVPRICE,PREVADMITTEDQUOTE,CURRENCYID,LISTLEVEL"
            ),
            "marketdata.columns": (
                "SECID,LAST,LCURRENTPRICE,LASTTOPREVPRICE,VOLTODAY,BID,OFFER"
            ),
        }
    )
    with _build_session() as session:
        iss = apimoex.ISSClient(session, url, arguments)
        payload = iss.get()

    securities = payload.get("securities") or []
    marketdata = payload.get("marketdata") or []
    sec = securities[0] if securities else {}
    md = marketdata[0] if marketdata else {}

    price = md.get("LAST") or md.get("LCURRENTPRICE") or sec.get("PREVPRICE") or sec.get("PREVADMITTEDQUOTE")
    market_cap = sec.get("ISSUECAPITALIZATION")
    if market_cap is None and price and sec.get("ISSUESIZE"):
        try:
            market_cap = float(price) * float(sec["ISSUESIZE"])
        except (TypeError, ValueError):
            market_cap = None

    return {
        "symbol": bare,
        "short_name": sec.get("SHORTNAME"),
        "price": float(price) if price is not None else None,
        "market_cap": float(market_cap) if market_cap is not None else None,
        "issuesize": sec.get("ISSUESIZE"),
        "lot_size": sec.get("LOTSIZE"),
        "volume": md.get("VOLTODAY"),
        "change_pct": md.get("LASTTOPREVPRICE"),
        "bid": md.get("BID"),
        "ask": md.get("OFFER"),
        "currency": sec.get("CURRENCYID") or "RUB",
        "list_level": sec.get("LISTLEVEL"),
    }


def _fetch_board_history_sync(
    ticker: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Daily OHLCV history on TQBR board via apimoex."""
    bare = normalize_moex_symbol(ticker)
    end = end or datetime.now(timezone.utc).date()
    start = start or (end - timedelta(days=max(365, limit * 2)))

    with _build_session() as session:
        rows = apimoex.get_board_history(
            session,
            bare,
            start=start,
            end=end,
            board=MOEX_BOARD,
        )

    bars: list[dict[str, Any]] = []
    for row in rows or []:
        tradedate = row.get("TRADEDATE")
        if not tradedate:
            continue
        ts = datetime.fromisoformat(str(tradedate)).replace(tzinfo=timezone.utc)
        close_raw = row.get("CLOSE")
        if close_raw in (None, ""):
            continue
        try:
            close = float(close_raw)
            open_ = float(row["OPEN"]) if row.get("OPEN") not in (None, "") else close
            high = float(row["HIGH"]) if row.get("HIGH") not in (None, "") else close
            low = float(row["LOW"]) if row.get("LOW") not in (None, "") else close
            volume = float(row["VOLUME"]) if row.get("VOLUME") not in (None, "") else 0.0
            vwap = float(row["WAPRICE"]) if row.get("WAPRICE") not in (None, "") else None
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
                "vwap": vwap,
                "trade_count": row.get("NUMTRADES"),
            }
        )
    return bars[-limit:]


def _fetch_board_securities_sync() -> list[dict[str, Any]]:
    """List all TQBR board securities."""
    arguments = _iss_client_args(
        {
            "securities.columns": (
                "SECID,SHORTNAME,SECNAME,LOTSIZE,ISSUESIZE,ISSUECAPITALIZATION,PREVPRICE,CURRENCYID"
            ),
        }
    )
    with _build_session() as session:
        iss = apimoex.ISSClient(session, TQBR_SECURITIES_URL, arguments)
        payload = iss.get()
    return list(payload.get("securities") or [])


def _normalize_fundamentals(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "symbol": raw.get("symbol"),
        "exchange": "MOEX",
        "currency": raw.get("currency") or "RUB",
        "source": "moex_iss",
    }
    if raw.get("short_name"):
        out["short_name"] = raw["short_name"]
    if raw.get("market_cap") is not None:
        out["market_cap"] = raw["market_cap"]
    if raw.get("price") is not None:
        out["price"] = raw["price"]
    if raw.get("issuesize") is not None:
        out["shares_outstanding"] = raw["issuesize"]
    if raw.get("volume") is not None:
        out["averageVolume"] = raw["volume"]
    if raw.get("change_pct") is not None:
        out["change_pct"] = raw["change_pct"]
    if raw.get("list_level") is not None:
        out["list_level"] = raw["list_level"]
    return {k: v for k, v in out.items() if v is not None}


async def fetch_moex_fundamentals(symbol: str) -> dict[str, Any]:
    """Load MOEX ISS fundamentals for a Russian equity ticker."""
    if not is_moex_ticker(symbol):
        return {}
    try:
        raw = await asyncio.to_thread(_fetch_security_detail_sync, symbol)
    except Exception as exc:
        logger.debug("MOEX ISS fundamentals failed", symbol=symbol, error=str(exc))
        return {}
    return _normalize_fundamentals(raw)


async def fetch_moex_history(
    symbol: str,
    *,
    timeframe: str = "1d",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Historical daily bars via apimoex board history."""
    if timeframe != "1d" or not is_moex_ticker(symbol):
        return []
    try:
        return await asyncio.to_thread(_fetch_board_history_sync, symbol, limit=limit)
    except Exception as exc:
        logger.debug("MOEX ISS history failed", symbol=symbol, error=str(exc))
        return []


async def list_moex_securities() -> list[dict[str, Any]]:
    """Return TQBR securities list from MOEX ISS."""
    try:
        return await asyncio.to_thread(_fetch_board_securities_sync)
    except Exception as exc:
        logger.debug("MOEX ISS securities list failed", error=str(exc))
        return []


def _fetch_dividends_sync(ticker: str) -> list[dict[str, Any]]:
    """Dividend history from MOEX ISS corporate actions."""
    bare = normalize_moex_symbol(ticker)
    url = f"https://iss.moex.com/iss/securities/{bare}/dividends.json"
    arguments = _iss_client_args(
        {
            "iss.only": "dividends",
            "dividends.columns": "secid,registryclosedate,value,currencyid",
        }
    )
    with _build_session() as session:
        iss = apimoex.ISSClient(session, url, arguments)
        payload = iss.get()
    rows = payload.get("dividends") or []
    dividends: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("registryclosedate") or row.get("value") is None:
            continue
        dividends.append(
            {
                "registry_close_date": str(row["registryclosedate"]),
                "value": float(row["value"]),
                "currency": row.get("currencyid") or "RUB",
            }
        )
    return dividends


def _compute_trailing_dividend_yield(
    dividends: list[dict[str, Any]],
    *,
    price: float | None,
    months: int = 12,
) -> float | None:
    """Trailing dividend yield from MOEX payouts over the last N months."""
    if not dividends or price is None or price <= 0:
        return None
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=months * 31)
    total = 0.0
    for item in dividends:
        try:
            pay_date = date.fromisoformat(str(item["registry_close_date"]))
        except ValueError:
            continue
        if pay_date >= cutoff:
            total += float(item["value"])
    if total <= 0:
        return None
    return total / float(price)


async def fetch_moex_dividends(symbol: str) -> dict[str, Any]:
    """MOEX ISS dividend history and trailing yield estimate."""
    if not is_moex_ticker(symbol):
        return {}
    try:
        dividends = await asyncio.to_thread(_fetch_dividends_sync, symbol)
    except Exception as exc:
        logger.debug("MOEX ISS dividends failed", symbol=symbol, error=str(exc))
        return {}
    if not dividends:
        return {"symbol": normalize_moex_symbol(symbol), "dividends": [], "source": "moex_iss"}

    detail = await fetch_moex_fundamentals(symbol)
    price = detail.get("price")
    trailing_yield = _compute_trailing_dividend_yield(dividends, price=price)
    recent = sorted(dividends, key=lambda x: x["registry_close_date"], reverse=True)[:6]
    return {
        "symbol": normalize_moex_symbol(symbol),
        "source": "moex_iss",
        "dividends": recent,
        "dividend_yield": trailing_yield,
        "currency": recent[0].get("currency") if recent else "RUB",
    }


async def fetch_moex_quote_enriched(symbol: str) -> dict[str, Any] | None:
    """Quote with ISS detail; index market for IMOEX; equity TQBR otherwise."""
    bare = normalize_moex_symbol(symbol)
    if is_moex_index(bare):
        index_q = await fetch_moex_index_quote(bare)
        if index_q:
            return index_q
    detail = await fetch_moex_fundamentals(symbol)
    quote = await get_moex_quote(symbol)
    if not quote and not detail:
        return None
    merged = dict(quote or {})
    if detail.get("market_cap") is not None:
        merged["market_cap"] = detail["market_cap"]
    if detail.get("short_name"):
        merged["short_name"] = detail["short_name"]
    merged.setdefault("exchange", "MOEX")
    merged.setdefault("source", "moex_iss")
    return merged
