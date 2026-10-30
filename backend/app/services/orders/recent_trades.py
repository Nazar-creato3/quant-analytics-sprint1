"""Recent trades tape — real executions per venue (never synthetic from order book)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.core.logging import get_logger
from app.schemas.orders import RecentTrade

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
BINANCE_SPOT_URL = "https://api.binance.com"
MOEX_TRADES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/trades.json"
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Binance ms epoch
        if value > 1e12:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # MOEX trade time HH:MM:SS on today's date (MSK session)
        try:
            from zoneinfo import ZoneInfo

            msk = ZoneInfo("Europe/Moscow")
            today = datetime.now(msk).date()
            parts = text.split(":")
            if len(parts) >= 2:
                h, m = int(parts[0]), int(parts[1])
                s = int(parts[2]) if len(parts) > 2 else 0
                return datetime(today.year, today.month, today.day, h, m, s, tzinfo=msk).astimezone(
                    timezone.utc
                )
        except Exception:
            raise
    return _now_utc()


async def _fetch_binance_trades(ticker: str, *, limit: int) -> list[RecentTrade]:
    from app.services.market_data.binance_spot import ticker_to_binance_symbol

    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return []

    url = f"{BINANCE_SPOT_URL}/api/v3/trades"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params={"symbol": symbol, "limit": min(limit, 1000)})
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        logger.warning("Binance trades failed", ticker=ticker, error=str(exc))
        return []

    out: list[RecentTrade] = []
    for row in rows:
        try:
            price = float(row["price"])
            size = float(row["qty"])
            is_buyer_maker = bool(row.get("isBuyerMaker"))
            side: Literal["buy", "sell"] = "sell" if is_buyer_maker else "buy"
            out.append(
                RecentTrade(
                    id=str(row.get("id", f"{price}-{row.get('time')}")),
                    price=price,
                    size=size,
                    side=side,
                    ts=_parse_ts(row.get("time")),
                    source="binance_trades",
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda t: t.ts, reverse=True)
    return out[:limit]


async def _fetch_alpaca_trades(ticker: str, *, limit: int) -> list[RecentTrade]:
    from app.core.config import settings
    from app.services.market_data.client import _provider_api_keys_configured
    from app.core.config import MarketDataProvider

    sym = ticker.upper()
    if not _provider_api_keys_configured(MarketDataProvider.ALPACA):
        return []

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"https://data.alpaca.markets/v2/stocks/{sym}/trades",
                headers=headers,
                params={"limit": min(limit, 100), "feed": "iex"},
            )
            if resp.status_code != 200:
                return []
            rows = resp.json().get("trades") or []
    except Exception as exc:
        logger.debug("Alpaca trades failed", ticker=sym, error=str(exc))
        return []

    out: list[RecentTrade] = []
    for row in rows:
        try:
            price = float(row["p"])
            size = float(row["s"])
            out.append(
                RecentTrade(
                    id=str(row.get("i", f"{price}-{row.get('t')}")),
                    price=price,
                    size=size,
                    side=None,
                    ts=_parse_ts(row.get("t")),
                    source="alpaca_trades",
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda t: t.ts, reverse=True)
    return out[:limit]


async def _fetch_polygon_trades(ticker: str, *, limit: int) -> list[RecentTrade]:
    from app.core.config import settings

    if not settings.POLYGON_API_KEY:
        return []
    sym = ticker.upper()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"https://api.polygon.io/v3/trades/{sym}",
                params={
                    "apiKey": settings.POLYGON_API_KEY,
                    "limit": min(limit, 50),
                    "sort": "timestamp",
                    "order": "desc",
                },
            )
            if resp.status_code != 200:
                return []
            rows = resp.json().get("results") or []
    except Exception as exc:
        logger.debug("Polygon trades failed", ticker=sym, error=str(exc))
        return []

    out: list[RecentTrade] = []
    for row in rows:
        try:
            price = float(row["price"])
            size = float(row.get("size") or 0)
            side: Literal["buy", "sell"] | None = None
            conditions = row.get("conditions") or []
            # Polygon participant timestamp — infer side from exchange if absent
            if row.get("exchange") == 4:
                side = "buy"
            side_raw = str(row.get("trf_id") or "")
            out.append(
                RecentTrade(
                    id=str(row.get("id", f"{price}-{row.get('sip_timestamp')}")),
                    price=price,
                    size=size,
                    side=side,
                    ts=_parse_ts(row.get("sip_timestamp") or row.get("participant_timestamp")),
                    source="polygon_trades",
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out[:limit]


async def _fetch_moex_trades(ticker: str, *, limit: int) -> list[RecentTrade]:
    from app.services.market_data.moex_spot import normalize_moex_symbol

    bare = normalize_moex_symbol(ticker)
    url = MOEX_TRADES_URL.format(ticker=bare)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params={"iss.meta": "off", "limit": min(limit, 100)})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("MOEX trades failed", ticker=bare, error=str(exc))
        return []

    trades = payload.get("trades", {})
    columns = trades.get("columns", [])
    rows = trades.get("data", [])
    out: list[RecentTrade] = []
    for row in rows:
        record = dict(zip(columns, row))
        try:
            price = float(record.get("PRICE") or 0)
            size = float(record.get("QUANTITY") or record.get("VALUE") or 0)
            if price <= 0 or size <= 0:
                continue
            side_raw = str(record.get("BUYSELL") or "").upper()
            side: Literal["buy", "sell"] | None = None
            if side_raw == "B":
                side = "buy"
            elif side_raw == "S":
                side = "sell"
            tradeno = record.get("TRADENO") or record.get("TRADETIME")
            ts_raw = record.get("TRADETIME") or record.get("SYSTIME")
            out.append(
                RecentTrade(
                    id=str(tradeno),
                    price=price,
                    size=size,
                    side=side,
                    ts=_parse_ts(ts_raw),
                    source="moex_iss_trades",
                )
            )
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda t: t.ts, reverse=True)
    return out[:limit]


async def fetch_recent_trades(ticker: str, *, limit: int = 50) -> list[RecentTrade]:
    """Route to Binance / MOEX ISS / Alpaca+Polygon based on ticker class."""
    from app.services.market_data.binance_spot import is_crypto_ticker
    from app.services.market_data.moex_spot import is_moex_ticker, resolve_moex_ticker

    raw = ticker.strip().upper()
    if not raw:
        return []

    if is_crypto_ticker(raw):
        return await _fetch_binance_trades(raw, limit=limit)

    if is_moex_ticker(raw) or await resolve_moex_ticker(raw):
        return await _fetch_moex_trades(raw, limit=limit)

    alpaca = await _fetch_alpaca_trades(raw, limit=limit)
    if alpaca:
        return alpaca
    polygon = await _fetch_polygon_trades(raw, limit=limit)
    if polygon:
        return polygon
    return []
