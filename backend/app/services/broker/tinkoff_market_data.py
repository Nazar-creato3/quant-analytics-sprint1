"""T-Bank (Tinkoff Invest) market data — GetOrderBook depth for MOEX instruments."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.schemas.orders import OrderBookLevel, OrderBookSnapshot
from app.services.integration.historical_data import (
    _resolve_tinkoff_figi,
    _tinkoff_token,
    tinkoff_rpc,
)
from app.services.market_data.moex_currency import (
    is_moex_currency_ticker,
    normalize_moex_currency_symbol,
    tinkoff_figi_for_currency,
)
from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(10.0, connect=4.0)


def _quotation_to_float(value: dict[str, Any] | None) -> float:
    if not value:
        return 0.0
    units = int(value.get("units") or 0)
    nano = int(value.get("nano") or 0)
    return units + nano / 1_000_000_000.0


def _resolve_figi(symbol: str, token: str) -> str | None:
    raw = symbol.strip().upper()
    if is_moex_currency_ticker(raw):
        figi = tinkoff_figi_for_currency(normalize_moex_currency_symbol(raw))
        if figi:
            return figi
    if is_moex_ticker(raw):
        bare = normalize_moex_symbol(raw)
        return _resolve_tinkoff_figi(bare, token)
    bare = normalize_moex_symbol(raw)
    return _resolve_tinkoff_figi(bare, token)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _mid_and_spread(
    bids: list[OrderBookLevel], asks: list[OrderBookLevel]
) -> tuple[float | None, float | None]:
    if not bids or not asks:
        return None, None
    best_bid = max(b.price for b in bids)
    best_ask = min(a.price for a in asks)
    if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
        mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else None
        return mid, None
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000
    return mid, round(spread_bps, 2)


def _levels_from_tinkoff_side(
    rows: list[dict[str, Any]] | None,
    *,
    levels: int,
    descending: bool,
) -> list[OrderBookLevel]:
    out: list[OrderBookLevel] = []
    for row in rows or []:
        price = _quotation_to_float(row.get("price"))
        qty_raw = row.get("quantity")
        try:
            size = float(qty_raw) if qty_raw is not None else 0.0
        except (TypeError, ValueError):
            size = 0.0
        if price <= 0:
            continue
        out.append(OrderBookLevel(price=price, size=max(size, 0.0)))
    out.sort(key=lambda lvl: lvl.price, reverse=descending)
    return out[:levels]


async def fetch_tinkoff_order_book(
    symbol: str,
    *,
    levels: int = 20,
) -> OrderBookSnapshot | None:
    """
    Fetch L2 order book from T-Bank Invest API (GetOrderBook by FIGI).
    Uses platform TINKOFF_API_TOKEN only — never user trading vault keys.
    Returns None when token/FIGI missing or API error.
    """
    token = _tinkoff_token()
    if not token:
        return None

    bare = symbol.strip().upper()
    if is_moex_currency_ticker(bare):
        bare = normalize_moex_currency_symbol(bare)
    elif is_moex_ticker(bare):
        bare = normalize_moex_symbol(bare)

    figi = await asyncio.to_thread(_resolve_figi, bare, token)
    if not figi:
        logger.debug("tinkoff_order_book_no_figi", symbol=bare)
        return None

    depth = max(1, min(int(levels), 50))
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"figi": figi, "depth": depth}

    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=_TIMEOUT)) as client:
            resp = await client.post(
                tinkoff_rpc("MarketDataService/GetOrderBook"),
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "tinkoff_get_order_book_http",
            symbol=bare,
            figi=figi,
            status=exc.response.status_code,
        )
        return None
    except Exception as exc:
        logger.warning("tinkoff_get_order_book_failed", symbol=bare, figi=figi, error=str(exc))
        return None

    bids = _levels_from_tinkoff_side(payload.get("bids"), levels=depth, descending=True)
    asks = _levels_from_tinkoff_side(payload.get("asks"), levels=depth, descending=False)
    if not bids and not asks:
        return None

    sized_bids = [b for b in bids if b.size > 0]
    sized_asks = [a for a in asks if a.size > 0]
    has_depth = bool(sized_bids and sized_asks)
    mid, spread_bps = _mid_and_spread(sized_bids or bids, sized_asks or asks)

    snap = OrderBookSnapshot(
        ticker=bare,
        bids=bids,
        asks=asks,
        mid_price=mid,
        spread_bps=spread_bps,
        source="tbank_orderbook",
        as_of=_now_utc(),
        depth_available=has_depth,
        session_label=None if has_depth else "T-Bank · NBBO",
        depth_unavailable_reason=None
        if has_depth
        else "T-Bank: стакан без объёмов на всех уровнях",
    )
    logger.info(
        "order_book_fetched",
        ticker=bare,
        source=snap.source,
        bid_levels=len(snap.bids),
        ask_levels=len(snap.asks),
        spread_bps=snap.spread_bps,
        depth_available=has_depth,
    )
    return snap
