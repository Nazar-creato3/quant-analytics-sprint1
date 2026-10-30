"""Real L2 / NBBO order book fetchers — never synthesize fake depth rows."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.schemas.orders import OrderBookLevel, OrderBookSnapshot

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
# Alpaca via Frankfurt proxy when configured; keep a sane connect budget.
ALPACA_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
BINANCE_SPOT_URL = "https://api.binance.com"
ALPACA_DATA_URL = "https://data.alpaca.markets"


def _exc_reason(exc: BaseException) -> str:
    from app.utils.secret_redact import redact_secrets

    if isinstance(exc, httpx.ConnectTimeout):
        return "таймаут соединения"
    if isinstance(exc, httpx.ReadTimeout):
        return "таймаут чтения"
    if isinstance(exc, httpx.ConnectError):
        return "сеть недоступна"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        detail = ""
        try:
            payload = exc.response.json()
            detail = str(payload.get("message") or payload.get("error") or "")[:80]
        except Exception:
            detail = (exc.response.text or "")[:80]
        detail = redact_secrets(detail) or ""
        return f"HTTP {code}" + (f" ({detail})" if detail else "")
    msg = redact_secrets(str(exc)) or type(exc).__name__
    return msg[:140]


def _is_rate_limited(reason: str | None) -> bool:
    if not reason:
        return False
    low = reason.lower()
    return "429" in low or "too many" in low or "rate limit" in low or "quota" in low


# After a paid US provider 429, skip the cascade cluster-wide (Redis + local).
_US_DEPTH_COOLDOWN_UNTIL: float = 0.0
_US_DEPTH_COOLDOWN_SEC = 180.0
_US_DEPTH_COOLDOWN_KEY = "us:orderbook:depth_cooldown"
_US_NBBO_CACHE_TTL = 45


async def _us_depth_on_cooldown() -> bool:
    import time

    if time.monotonic() < _US_DEPTH_COOLDOWN_UNTIL:
        return True
    try:
        from app.utils.cache import cache_get

        flag = await cache_get(_US_DEPTH_COOLDOWN_KEY)
        return bool(flag)
    except Exception:
        return False


async def _trip_us_depth_cooldown(reason: str | None) -> None:
    global _US_DEPTH_COOLDOWN_UNTIL
    if not _is_rate_limited(reason):
        return
    import time

    _US_DEPTH_COOLDOWN_UNTIL = time.monotonic() + _US_DEPTH_COOLDOWN_SEC
    try:
        from app.utils.cache import cache_set

        await cache_set(
            _US_DEPTH_COOLDOWN_KEY,
            {"until": time.time() + _US_DEPTH_COOLDOWN_SEC, "reason": (reason or "")[:120]},
            ttl=int(_US_DEPTH_COOLDOWN_SEC),
        )
    except Exception:
        raise
    logger.warning(
        "us_orderbook_rate_limit_cooldown",
        seconds=_US_DEPTH_COOLDOWN_SEC,
        reason=(reason or "")[:120],
    )


def _join_reasons(parts: list[str]) -> str:
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in cleaned:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return " · ".join(out)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _levels_from_pairs(pairs: list[list[Any]], *, levels: int, descending: bool) -> list[OrderBookLevel]:
    out: list[OrderBookLevel] = []
    for row in pairs[:levels]:
        if not row or len(row) < 2:
            continue
        try:
            price = float(row[0])
            size = float(row[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        out.append(OrderBookLevel(price=price, size=size))
    if descending:
        out.sort(key=lambda lvl: lvl.price, reverse=True)
    else:
        out.sort(key=lambda lvl: lvl.price)
    return out


def _levels_from_price_size_map(
    side_map: dict[float, float],
    *,
    levels: int,
    descending: bool,
) -> list[OrderBookLevel]:
    items = sorted(side_map.items(), key=lambda x: x[0], reverse=descending)
    out: list[OrderBookLevel] = []
    for price, size in items[:levels]:
        if price <= 0 or size <= 0:
            continue
        out.append(OrderBookLevel(price=price, size=size))
    return out


def _mid_and_spread(bids: list[OrderBookLevel], asks: list[OrderBookLevel]) -> tuple[float | None, float | None]:
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


def _empty_snapshot(ticker: str, *, source: str) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=[],
        asks=[],
        mid_price=None,
        spread_bps=None,
        source=source,
        as_of=_now_utc(),
        depth_available=False,
    )


NBBO_SESSION_LABEL = "глубина ограничена уровнем NBBO"


def _alpaca_nbbo_snapshot(
    ticker: str,
    *,
    bids: list[OrderBookLevel],
    asks: list[OrderBookLevel],
    source: str,
    feed: str,
    sized: bool,
) -> OrderBookSnapshot:
    """Alpaca stocks: exactly one bid + one ask (NBBO). Never mark as full L2."""
    mid, spread_bps = _mid_and_spread(bids, asks)
    if mid is None and bids and asks:
        mid = (bids[0].price + asks[0].price) / 2.0
        spread_bps = round((asks[0].price - bids[0].price) / mid * 10_000, 2) if mid else None
    size_note = "с объёмами NBBO" if sized else "без объёмов"
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=bids[:1],
        asks=asks[:1],
        mid_price=mid,
        spread_bps=spread_bps,
        source=source,
        as_of=_now_utc(),
        depth_available=False,
        session_label=NBBO_SESSION_LABEL,
        depth_unavailable_reason=(
            f"Alpaca {feed}: только 1 bid + 1 ask ({size_note}); "
            "L2 стакан акций у Alpaca не предоставляется"
        ),
    )


def _thin_nbbo_snapshot(
    ticker: str,
    *,
    bids: list[OrderBookLevel],
    asks: list[OrderBookLevel],
    source: str,
    session_label: str,
    depth_unavailable_reason: str | None = None,
) -> OrderBookSnapshot:
    """NBBO prices without real depth — never fabricate ladder sizes."""
    priced_bids = [OrderBookLevel(price=b.price, size=0.0) for b in bids if b.price > 0]
    priced_asks = [OrderBookLevel(price=a.price, size=0.0) for a in asks if a.price > 0]
    mid, spread_bps = _mid_and_spread(priced_bids, priced_asks)
    if mid is None and priced_bids and priced_asks:
        mid = (priced_bids[0].price + priced_asks[0].price) / 2.0
        spread_bps = round((priced_asks[0].price - priced_bids[0].price) / mid * 10_000, 2)
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=priced_bids,
        asks=priced_asks,
        mid_price=mid,
        spread_bps=spread_bps,
        source=source,
        as_of=_now_utc(),
        depth_available=False,
        session_label=session_label,
        depth_unavailable_reason=depth_unavailable_reason or session_label,
    )


def _snapshot_from_levels(
    ticker: str,
    *,
    bids: list[OrderBookLevel],
    asks: list[OrderBookLevel],
    source: str,
) -> OrderBookSnapshot:
    mid, spread_bps = _mid_and_spread(bids, asks)
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=bids,
        asks=asks,
        mid_price=mid,
        spread_bps=spread_bps,
        source=source,
        as_of=_now_utc(),
    )


def _has_sized_depth(book: OrderBookSnapshot) -> bool:
    return any(b.size > 0 for b in book.bids) and any(a.size > 0 for a in book.asks)


def _sized_level_count(book: OrderBookSnapshot) -> int:
    """Min bid/ask levels with non-zero size — depth quality signal."""
    bid_n = sum(1 for b in book.bids if b.size > 0)
    ask_n = sum(1 for a in book.asks if a.size > 0)
    if bid_n > 0 and ask_n > 0:
        return min(bid_n, ask_n)
    return max(bid_n, ask_n, len(book.bids), len(book.asks))


def _pick_deeper_book(
    books: list[OrderBookSnapshot | None],
    *,
    levels: int,
    min_useful: int = 5,
) -> OrderBookSnapshot | None:
    """Choose the snapshot with the most real depth; prefer sized L2 over thin NBBO."""
    candidates = [b for b in books if b is not None and (b.bids or b.asks)]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda b: (
            _sized_level_count(b),
            1 if _has_sized_depth(b) else 0,
            len(b.bids) + len(b.asks),
        ),
        reverse=True,
    )
    best = ranked[0]
    if _sized_level_count(best) >= min_useful or _has_sized_depth(best):
        return best
    # Shallow but non-empty — still return best if nothing deeper exists.
    return best if _sized_level_count(best) > 0 or (best.bids or best.asks) else None


async def _fetch_binance_depth(ticker: str, *, levels: int) -> OrderBookSnapshot:
    from app.services.market_data.binance_spot import ticker_to_binance_symbol

    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return _empty_snapshot(ticker, source="binance_unsupported")

    url = f"{BINANCE_SPOT_URL}/api/v3/depth"
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=TIMEOUT)) as client:
            resp = await client.get(url, params={"symbol": symbol, "limit": min(levels, 100)})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Binance depth failed", ticker=ticker, symbol=symbol, error=str(exc))
        return _empty_snapshot(ticker, source="binance_error")

    bids = _levels_from_pairs(data.get("bids") or [], levels=levels, descending=True)
    asks = _levels_from_pairs(data.get("asks") or [], levels=levels, descending=False)
    book = _snapshot_from_levels(ticker, bids=bids, asks=asks, source="binance_depth")
    logger.info(
        "order_book_fetched",
        ticker=ticker,
        source=book.source,
        bid_levels=len(book.bids),
        ask_levels=len(book.asks),
        spread_bps=book.spread_bps,
    )
    return book


def _parse_moex_iss_orderbook_payload(
    payload: dict[str, Any] | None,
    *,
    bare: str,
    levels: int,
    source: str,
) -> OrderBookSnapshot | None:
    if not payload:
        return None
    book = payload.get("orderbook", {})
    records: list[dict[str, Any]] = []
    if isinstance(book, list):
        records = [row for row in book if isinstance(row, dict)]
    elif isinstance(book, dict):
        columns = book.get("columns", [])
        rows = book.get("data", [])
        if columns:
            records = [dict(zip(columns, row)) for row in rows]
        elif isinstance(book.get("data"), list) and book["data"] and isinstance(book["data"][0], dict):
            records = book["data"]
    bid_pairs: list[list[Any]] = []
    ask_pairs: list[list[Any]] = []
    for record in records:
        side = str(record.get("BUYSELL") or "").upper()
        price = record.get("PRICE")
        qty = record.get("QUANTITY")
        if price is None or qty is None:
            continue
        if side == "B":
            bid_pairs.append([price, qty])
        elif side == "S":
            ask_pairs.append([price, qty])
    bids = _levels_from_pairs(bid_pairs, levels=levels, descending=True)
    asks = _levels_from_pairs(ask_pairs, levels=levels, descending=False)
    if not bids and not asks:
        return None
    return _snapshot_from_levels(bare, bids=bids, asks=asks, source=source)


def _moex_platform_depth_notes() -> list[str]:
    from app.services.market_data.moex_iss_client import moex_platform_orderbook_configured
    from app.services.trading_keys.platform_keys import tinkoff_platform_configured

    notes: list[str] = []
    if not moex_platform_orderbook_configured():
        notes.append("MOEX ISS: platform credentials not configured")
    if not tinkoff_platform_configured():
        notes.append("T-Bank: platform TINKOFF_API_TOKEN not configured")
    return notes


async def _fetch_moex_currency_depth(ticker: str, *, levels: int) -> OrderBookSnapshot:
    from app.services.broker.tinkoff_market_data import fetch_tinkoff_order_book
    from app.services.market_data.moex_currency import (
        get_moex_currency_quote,
        normalize_moex_currency_symbol,
    )
    from app.services.market_data.moex_iss_client import fetch_moex_cets_orderbook_json

    bare = normalize_moex_currency_symbol(ticker)
    tbank = await fetch_tinkoff_order_book(bare, levels=levels)

    iss_book: OrderBookSnapshot | None = None
    try:
        payload = await fetch_moex_cets_orderbook_json(bare)
        iss_book = _parse_moex_iss_orderbook_payload(
            payload,
            bare=bare,
            levels=levels,
            source="moex_cets_orderbook",
        )
    except Exception as exc:
        logger.warning("MOEX CETS orderbook failed", ticker=bare, error=str(exc))

    picked = _pick_deeper_book([tbank, iss_book], levels=levels)
    if picked is not None:
        logger.info(
            "order_book_fetched",
            ticker=bare,
            source=picked.source,
            bid_levels=len(picked.bids),
            ask_levels=len(picked.asks),
            spread_bps=picked.spread_bps,
        )
        return picked

    if tbank is not None and (tbank.bids or tbank.asks):
        return tbank

    quote = await get_moex_currency_quote(bare)
    if not quote:
        return _empty_snapshot(ticker, source="moex_fx_no_data")
    nbbo_bids: list[OrderBookLevel] = []
    nbbo_asks: list[OrderBookLevel] = []
    if quote.get("bid"):
        nbbo_bids.append(OrderBookLevel(price=float(quote["bid"]), size=0.0))
    if quote.get("ask"):
        nbbo_asks.append(OrderBookLevel(price=float(quote["ask"]), size=0.0))
    return _thin_nbbo_snapshot(
        bare,
        bids=nbbo_bids,
        asks=nbbo_asks,
        source="moex_cets_nbbo",
        session_label="NBBO · MOEX валюта",
        depth_unavailable_reason="MOEX CETS: стакан недоступен · только bid/ask",
    )


async def _fetch_moex_depth(ticker: str, *, levels: int) -> OrderBookSnapshot:
    from app.services.broker.tinkoff_market_data import fetch_tinkoff_order_book
    from app.services.market_data.moex_iss_client import fetch_moex_share_orderbook_json
    from app.services.market_data.moex_spot import normalize_moex_symbol

    bare = normalize_moex_symbol(ticker)
    tbank = await fetch_tinkoff_order_book(bare, levels=levels)

    iss_book: OrderBookSnapshot | None = None
    try:
        payload = await fetch_moex_share_orderbook_json(bare)
        iss_book = _parse_moex_iss_orderbook_payload(
            payload,
            bare=bare,
            levels=levels,
            source="moex_iss_orderbook",
        )
    except Exception as exc:
        logger.warning("MOEX orderbook failed", ticker=bare, error=str(exc))
        return await _fetch_moex_nbbo_fallback(ticker, levels=levels, tbank_cached=tbank)

    picked = _pick_deeper_book([tbank, iss_book], levels=levels)
    if picked is not None:
        logger.info(
            "order_book_fetched",
            ticker=bare,
            source=picked.source,
            bid_levels=len(picked.bids),
            ask_levels=len(picked.asks),
            spread_bps=picked.spread_bps,
        )
        return picked

    if not iss_book:
        return await _fetch_moex_nbbo_fallback(ticker, levels=levels, tbank_cached=tbank)

    logger.info(
        "order_book_fetched",
        ticker=bare,
        source=iss_book.source,
        bid_levels=len(iss_book.bids),
        ask_levels=len(iss_book.asks),
        spread_bps=iss_book.spread_bps,
    )
    return iss_book


async def _fetch_moex_nbbo_fallback(
    ticker: str,
    *,
    levels: int,
    tbank_cached: OrderBookSnapshot | None = None,
) -> OrderBookSnapshot:
    """Top-of-book from MOEX marketdata when ISS orderbook is empty (session closed)."""
    from app.services.broker.tinkoff_market_data import fetch_tinkoff_order_book
    from app.services.market_data.moex_spot import get_moex_quote, normalize_moex_symbol

    bare = normalize_moex_symbol(ticker)
    tbank = tbank_cached
    if tbank is None:
        tbank = await fetch_tinkoff_order_book(bare, levels=levels)
    if tbank is not None and _has_sized_depth(tbank):
        return tbank
    if tbank is not None and (tbank.bids or tbank.asks):
        return tbank
    quote = await get_moex_quote(bare)
    if not quote:
        return _empty_snapshot(ticker, source="moex_no_data")

    bids: list[OrderBookLevel] = []
    asks: list[OrderBookLevel] = []
    bid = quote.get("bid")
    ask = quote.get("ask")
    bid_sz = quote.get("bid_size")
    ask_sz = quote.get("ask_size")
    lot = quote.get("lot_size")
    if bid and float(bid) > 0:
        sz = float(bid_sz) if bid_sz and float(bid_sz) > 0 else (float(lot) if lot else 0.0)
        if sz > 0:
            bids.append(OrderBookLevel(price=float(bid), size=sz))
        else:
            bids.append(OrderBookLevel(price=float(bid), size=0.0))
    if ask and float(ask) > 0:
        sz = float(ask_sz) if ask_sz and float(ask_sz) > 0 else (float(lot) if lot else 0.0)
        if sz > 0:
            asks.append(OrderBookLevel(price=float(ask), size=sz))
        else:
            asks.append(OrderBookLevel(price=float(ask), size=0.0))

    has_depth = any(b.size > 0 for b in bids) and any(a.size > 0 for a in asks)
    mid, spread_bps = _mid_and_spread(
        [b for b in bids if b.size > 0],
        [a for a in asks if a.size > 0],
    )
    if mid is None and bids and asks:
        mid = (bids[0].price + asks[0].price) / 2.0
        spread_bps = round((asks[0].price - bids[0].price) / mid * 10_000, 2) if mid else None

    price = quote.get("price")
    if mid is None and price and float(price) > 0:
        mid = float(price)

    if not bids and not asks and mid is not None:
        return OrderBookSnapshot(
            ticker=bare,
            bids=[],
            asks=[],
            mid_price=mid,
            spread_bps=None,
            source="moex_last",
            as_of=_now_utc(),
            depth_available=False,
            session_label="последняя цена · без стакана",
            depth_unavailable_reason="MOEX ISS orderbook пуст · показана последняя цена",
        )

    if not has_depth and (bids or asks):
        platform_notes = _moex_platform_depth_notes()
        admin_tail = f" · {' · '.join(platform_notes)}" if platform_notes else ""
        return _thin_nbbo_snapshot(
            bare,
            bids=bids,
            asks=asks,
            source="moex_nbbo",
            session_label="NBBO без глубины",
            depth_unavailable_reason=(
                "MOEX: стакан ISS пуст или вне сессии · только лучшие bid/ask"
                f"{admin_tail}"
            ),
        )

    return OrderBookSnapshot(
        ticker=bare,
        bids=bids[:levels],
        asks=asks[:levels],
        mid_price=mid,
        spread_bps=spread_bps,
        source="moex_nbbo" if not has_depth else "moex_iss_orderbook",
        as_of=_now_utc(),
        depth_available=has_depth,
        session_label=None if has_depth else "NBBO · ограниченная глубина",
        depth_unavailable_reason=None
        if has_depth
        else "MOEX: ограниченная глубина из marketdata",
    )


async def _fetch_polygon_quote_depth(
    ticker: str, *, levels: int
) -> tuple[OrderBookSnapshot | None, str | None]:
    """Try Polygon aggregated quotes. Returns (snapshot|None, failure_reason|None)."""
    from app.core.config import settings
    from app.utils.secret_redact import redact_secrets

    if not settings.POLYGON_API_KEY:
        return None, "ключ не задан"

    sym = ticker.upper()
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=TIMEOUT)) as client:
            resp = await client.get(
                f"https://api.polygon.io/v3/quotes/{sym}",
                params={
                    "apiKey": settings.POLYGON_API_KEY,
                    "limit": min(max(levels * 12, 50), 200),
                    "sort": "timestamp",
                    "order": "desc",
                },
            )
            if resp.status_code == 403:
                detail = ""
                try:
                    detail = str(resp.json().get("message") or "")[:100]
                except Exception:
                    detail = ""
                detail = redact_secrets(detail) or "NOT_AUTHORIZED"
                return None, f"нет подписки на quotes ({detail})"
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            rows = resp.json().get("results") or []
    except Exception as exc:
        logger.warning(
            "Polygon quotes depth failed",
            ticker=sym,
            error=redact_secrets(_exc_reason(exc)),
        )
        return None, _exc_reason(exc)

    bid_map: dict[float, float] = defaultdict(float)
    ask_map: dict[float, float] = defaultdict(float)
    for row in rows:
        bid_px = row.get("bid_price")
        bid_sz = row.get("bid_size")
        ask_px = row.get("ask_price")
        ask_sz = row.get("ask_size")
        if bid_px and bid_sz:
            bid_map[float(bid_px)] += float(bid_sz)
        if ask_px and ask_sz:
            ask_map[float(ask_px)] += float(ask_sz)

    bids = _levels_from_price_size_map(bid_map, levels=levels, descending=True)
    asks = _levels_from_price_size_map(ask_map, levels=levels, descending=False)
    if not bids and not asks:
        return None, "пустой ответ quotes"
    snap = _snapshot_from_levels(sym, bids=bids, asks=asks, source="polygon_quotes")
    logger.info(
        "order_book_fetched",
        ticker=sym,
        source=snap.source,
        bid_levels=len(snap.bids),
        ask_levels=len(snap.asks),
        spread_bps=snap.spread_bps,
    )
    return snap, None


def _levels_from_quote_dict(quote: dict[str, Any]) -> tuple[list[OrderBookLevel], list[OrderBookLevel], bool]:
    bids: list[OrderBookLevel] = []
    asks: list[OrderBookLevel] = []
    bid_px = quote.get("bid")
    ask_px = quote.get("ask")
    bid_sz = quote.get("bid_size")
    ask_sz = quote.get("ask_size")
    if bid_px and float(bid_px) > 0 and bid_sz and float(bid_sz) > 0:
        bids.append(OrderBookLevel(price=float(bid_px), size=float(bid_sz)))
    elif bid_px and float(bid_px) > 0:
        bids.append(OrderBookLevel(price=float(bid_px), size=0.0))
    if ask_px and float(ask_px) > 0 and ask_sz and float(ask_sz) > 0:
        asks.append(OrderBookLevel(price=float(ask_px), size=float(ask_sz)))
    elif ask_px and float(ask_px) > 0:
        asks.append(OrderBookLevel(price=float(ask_px), size=0.0))
    has_sized = any(b.size > 0 for b in bids) and any(a.size > 0 for a in asks)
    return bids, asks, has_sized


async def _try_alpaca_equity_book(
    sym: str, *, levels: int
) -> tuple[OrderBookSnapshot | None, str]:
    """Alpaca stocks: NBBO / latest quote (IEX). Stock L2 orderbook is not offered by Alpaca."""
    from app.core.config import settings
    from app.utils.secret_redact import redact_secrets

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
    }
    reasons: list[str] = []

    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=ALPACA_TIMEOUT)) as http:
        # Prefer documented latest quote with free IEX feed (not trading paper-api host).
        for feed in ("iex", "sip"):
            try:
                resp = await http.get(
                    f"{ALPACA_DATA_URL}/v2/stocks/{sym}/quotes/latest",
                    headers=headers,
                    params={"feed": feed},
                )
                if resp.status_code == 200:
                    q = (resp.json() or {}).get("quote") or resp.json() or {}
                    bid_px, ask_px = q.get("bp"), q.get("ap")
                    bid_sz, ask_sz = q.get("bs"), q.get("as")
                    bids, asks, has_sized = _levels_from_quote_dict(
                        {
                            "bid": bid_px,
                            "ask": ask_px,
                            "bid_size": bid_sz,
                            "ask_size": ask_sz,
                        }
                    )
                    if bids or asks:
                        snap = _alpaca_nbbo_snapshot(
                            sym,
                            bids=bids,
                            asks=asks,
                            source=f"alpaca_nbbo_{feed}",
                            feed=feed,
                            sized=has_sized,
                        )
                        logger.info(
                            "order_book_fetched",
                            ticker=sym,
                            source=snap.source,
                            bid_levels=len(snap.bids),
                            ask_levels=len(snap.asks),
                            spread_bps=snap.spread_bps,
                            depth_available=snap.depth_available,
                        )
                        return snap, ""
                if resp.status_code in {401, 403, 404, 422}:
                    body = redact_secrets((resp.text or "")[:120]) or ""
                    reasons.append(f"quotes/{feed} HTTP {resp.status_code} {body}".strip())
                    if resp.status_code in {401, 403} and feed == "iex":
                        # Auth failure — no point trying SIP with same keys immediately.
                        break
                    continue
                if resp.status_code == 429:
                    reasons.append(f"quotes/{feed}: 429 Too Many Requests")
                    break
                reasons.append(f"quotes/{feed} HTTP {resp.status_code}")
            except Exception as exc:
                reasons.append(f"quotes/{feed}: {_exc_reason(exc)}")
                # Connect timeout to data.alpaca.markets — skip further Alpaca attempts.
                if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError)):
                    break

        # Snapshots fallback (same data host).
        try:
            resp = await http.get(
                f"{ALPACA_DATA_URL}/v2/stocks/snapshots",
                headers=headers,
                params={"symbols": sym, "feed": "iex"},
            )
            if resp.status_code == 200:
                snap_raw = (resp.json() or {}).get(sym) or {}
                lq = snap_raw.get("latestQuote") or {}
                bids, asks, has_sized = _levels_from_quote_dict(
                    {
                        "bid": lq.get("bp"),
                        "ask": lq.get("ap"),
                        "bid_size": lq.get("bs"),
                        "ask_size": lq.get("as"),
                    }
                )
                if bids or asks:
                    return (
                        _alpaca_nbbo_snapshot(
                            sym,
                            bids=bids,
                            asks=asks,
                            source="alpaca_nbbo_iex",
                            feed="iex",
                            sized=has_sized,
                        ),
                        "",
                    )
            reasons.append(f"snapshots HTTP {resp.status_code}")
        except Exception as exc:
            reasons.append(f"snapshots: {_exc_reason(exc)}")

    return None, _join_reasons(reasons) or "нет данных"


async def _try_provider_nbbo(
    provider: str, sym: str
) -> tuple[OrderBookSnapshot | None, str | None]:
    """TwelveData / Tiingo NBBO before Yahoo when Alpaca/Polygon fail."""
    from app.services.market_data.http_providers import (
        TiingoClient,
        TwelveDataClient,
        key_configured,
    )
    from app.utils.secret_redact import redact_secrets

    if provider == "twelvedata":
        if not key_configured("twelvedata"):
            return None, "ключ не задан"
        client: Any = TwelveDataClient()
        source = "twelvedata_nbbo"
    elif provider == "tiingo":
        if not key_configured("tiingo"):
            return None, "ключ не задан"
        client = TiingoClient()
        source = "tiingo_nbbo"
    else:
        return None, "unknown provider"

    try:
        quote = await client.get_latest_quote(sym)
    except Exception as exc:
        logger.warning(
            "order_book provider NBBO failed",
            provider=provider,
            ticker=sym,
            error=redact_secrets(_exc_reason(exc)),
        )
        return None, _exc_reason(exc)

    bids, asks, has_sized = _levels_from_quote_dict(quote)
    if not bids and not asks:
        price = quote.get("price")
        if price and float(price) > 0:
            return (
                OrderBookSnapshot(
                    ticker=sym,
                    bids=[],
                    asks=[],
                    mid_price=float(price),
                    spread_bps=None,
                    source=f"{provider}_last",
                    as_of=_now_utc(),
                    depth_available=False,
                    session_label="последняя цена · без стакана",
                    depth_unavailable_reason=f"{provider}: только last price, без bid/ask",
                ),
                None,
            )
        return None, "нет bid/ask"

    if has_sized:
        snap = _snapshot_from_levels(sym, bids=bids, asks=asks, source=source)
        return snap, None

    return (
        _thin_nbbo_snapshot(
            sym,
            bids=bids,
            asks=asks,
            source=source,
            session_label=f"глубина недоступна · {provider} NBBO",
            depth_unavailable_reason=f"{provider}: NBBO без объёмов (L2 нет)",
        ),
        None,
    )


def _replay_book(ticker: str, *, levels: int) -> OrderBookSnapshot | None:
    """Real Nasdaq TotalView book replayed from a public ITCH 5.0 day file, moving second by second."""
    from app.services.us_book_replay import store as replay

    try:
        f = replay.frame(ticker)
    except Exception as exc:  # noqa: BLE001 — a broken file must not break the deal screen
        logger.warning("us_book_replay_failed", ticker=ticker, error=str(exc)[:200])
        return None
    if not f:
        return None
    bids = [OrderBookLevel(price=p, size=q) for p, q in f["b"][:levels]]
    asks = [OrderBookLevel(price=p, size=q) for p, q in f["a"][:levels]]
    if not bids and not asks:
        return None
    mid = (bids[0].price + asks[0].price) / 2 if bids and asks else None
    spread = ((asks[0].price - bids[0].price) / mid * 10_000) if mid else None
    day = datetime.fromisoformat(str(f["session"])).strftime("%d.%m.%Y")
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=bids,
        asks=asks,
        mid_price=mid,
        spread_bps=spread,
        source="Nasdaq TotalView",
        as_of=_now_utc(),
        depth_available=True,
        session_label=(
            f"Запись торгов Nasdaq {day} · {replay.clock_text(int(f['t']))} по Нью-Йорку "
            "(демонстрация: трансляция в реальном времени — после подключения лицензии биржи)"
        ),
        depth_unavailable_reason=(
            "Настоящий стакан Nasdaq, восстановленный по полной записи торгового дня, "
            "которую биржа публикует открыто. Живой стакан США показывается клиентам только по биржевой лицензии."
        ),
        exchange_id="XNAS",
        exchange_name_ru="Nasdaq",
    )


async def _fetch_databento_close_book(ticker: str, *, levels: int) -> OrderBookSnapshot | None:
    """Real Nasdaq 10-level book at the close of the latest session older than 24 h (Databento)."""
    from app.services.market_data import databento_book

    if not databento_book.configured():
        return None
    snap = await databento_book.close_book(ticker)
    if not snap:
        return None
    bids = [OrderBookLevel(price=p, size=q) for p, q in snap["bids"][:levels]]
    asks = [OrderBookLevel(price=p, size=q) for p, q in snap["asks"][:levels]]
    mid = (bids[0].price + asks[0].price) / 2 if bids and asks else None
    spread = ((asks[0].price - bids[0].price) / mid * 10_000) if mid else None
    day = datetime.fromisoformat(snap["session"]).strftime("%d.%m.%Y")
    return OrderBookSnapshot(
        ticker=ticker.upper(),
        bids=bids,
        asks=asks,
        mid_price=mid,
        spread_bps=spread,
        source="Nasdaq TotalView · Databento",
        as_of=_now_utc(),
        depth_available=True,
        session_label=f"Запись стакана Nasdaq на закрытии торгов {day}",
        depth_unavailable_reason=(
            "Живой стакан США можно показывать клиентам только по биржевой лицензии; "
            "здесь — настоящий стакан Nasdaq на закрытии прошлой сессии."
        ),
        exchange_id="XNAS",
        exchange_name_ru="Nasdaq",
    )


async def _fetch_alpaca_depth(ticker: str, *, levels: int) -> OrderBookSnapshot:
    """US equities: try paid depth once; on 429 skip cascade and use Yahoo NBBO."""
    from app.core.config import MarketDataProvider
    from app.services.market_data.client import _provider_api_keys_configured
    from app.utils.secret_redact import redact_secrets

    sym = ticker.upper()
    attempt_notes: list[str] = []
    candidates: list[OrderBookSnapshot] = []
    alpaca_configured = _provider_api_keys_configured(MarketDataProvider.ALPACA)

    replayed = _replay_book(sym, levels=levels)
    if replayed is not None:
        return replayed

    recorded = await _fetch_databento_close_book(sym, levels=levels)
    if recorded is not None:
        return recorded

    if await _us_depth_on_cooldown():
        attempt_notes.append("paid L2: cooldown после 429")
        return await _fetch_yfinance_nbbo(sym, prior_reasons=attempt_notes)

    polygon, poly_reason = await _fetch_polygon_quote_depth(sym, levels=levels)
    if polygon is not None:
        candidates.append(polygon)
        if _sized_level_count(polygon) >= 5:
            return polygon
    if poly_reason:
        attempt_notes.append(f"Polygon: {poly_reason}")
        if _is_rate_limited(poly_reason):
            await _trip_us_depth_cooldown(poly_reason)
            return await _fetch_yfinance_nbbo(sym, prior_reasons=attempt_notes)

    if alpaca_configured:
        snap, alpaca_reason = await _try_alpaca_equity_book(sym, levels=levels)
        if snap is not None:
            if _sized_level_count(snap) >= 5:
                if attempt_notes and snap.depth_unavailable_reason:
                    snap = snap.model_copy(
                        update={
                            "depth_unavailable_reason": _join_reasons(
                                [*attempt_notes, snap.depth_unavailable_reason or ""]
                            )
                        }
                    )
                return snap
            candidates.append(snap)
        note = f"Alpaca: {alpaca_reason}" if alpaca_reason else "Alpaca: ошибка"
        attempt_notes.append(note)
        if _is_rate_limited(alpaca_reason):
            await _trip_us_depth_cooldown(alpaca_reason)
            logger.warning(
                "Alpaca order book rate-limited — skipping Twelve/Tiingo",
                ticker=sym,
                error=redact_secrets(alpaca_reason),
            )
            return await _fetch_yfinance_nbbo(sym, prior_reasons=attempt_notes)
        logger.warning(
            "Alpaca order book unavailable or shallow",
            ticker=sym,
            error=redact_secrets(alpaca_reason),
        )
    else:
        attempt_notes.append("Alpaca: ключи не заданы")

    best = _pick_deeper_book(candidates, levels=levels)
    if best is not None and _sized_level_count(best) >= 3:
        if attempt_notes and best.depth_unavailable_reason:
            best = best.model_copy(
                update={
                    "depth_unavailable_reason": _join_reasons(
                        [*attempt_notes, best.depth_unavailable_reason or ""]
                    )
                }
            )
        return best

    for provider in ("twelvedata", "tiingo"):
        alt, alt_reason = await _try_provider_nbbo(provider, sym)
        if alt is not None:
            if attempt_notes:
                reason = _join_reasons(
                    [
                        *attempt_notes,
                        alt.depth_unavailable_reason or f"{provider}: NBBO",
                    ]
                )
                alt = alt.model_copy(
                    update={
                        "depth_unavailable_reason": reason,
                        "session_label": alt.session_label
                        or "глубина недоступна · fallback NBBO",
                    }
                )
            return alt
        if alt_reason:
            attempt_notes.append(f"{provider}: {alt_reason}")
            if _is_rate_limited(alt_reason):
                await _trip_us_depth_cooldown(alt_reason)
                break

    yf_book = await _fetch_yfinance_nbbo(sym, prior_reasons=attempt_notes)
    if yf_book.bids or yf_book.asks or yf_book.mid_price is not None:
        return yf_book

    return OrderBookSnapshot(
        ticker=sym,
        bids=[],
        asks=[],
        mid_price=None,
        spread_bps=None,
        source="us_equity_no_data",
        as_of=_now_utc(),
        depth_available=False,
        session_label="глубина недоступна",
        depth_unavailable_reason=_join_reasons([*attempt_notes, "Yahoo: нет данных"]),
    )


async def _fetch_yfinance_nbbo(
    ticker: str, *, prior_reasons: list[str] | None = None
) -> OrderBookSnapshot:
    """Last-resort NBBO — prices only, never fake ladder sizes."""
    from app.services.market_data.client import YFinanceClient
    from app.utils.cache import cache_get, cache_set
    from app.utils.secret_redact import redact_secrets

    sym = ticker.upper()
    prior = list(prior_reasons or [])
    cache_key = f"us:orderbook:nbbo:{sym}"
    cached = await cache_get(cache_key)
    if isinstance(cached, dict) and (cached.get("bids") or cached.get("asks") or cached.get("mid_price") is not None):
        try:
            snap = OrderBookSnapshot.model_validate(cached)
            if prior:
                snap = snap.model_copy(
                    update={
                        "depth_unavailable_reason": _join_reasons(
                            [*prior, snap.depth_unavailable_reason or "Yahoo NBBO cache"]
                        )
                    }
                )
            return snap
        except Exception:
            raise
    try:
        quote = await YFinanceClient().get_latest_quote(sym)
    except Exception as exc:
        logger.debug(
            "yfinance NBBO failed",
            ticker=sym,
            error=redact_secrets(_exc_reason(exc)),
        )
        return OrderBookSnapshot(
            ticker=sym,
            bids=[],
            asks=[],
            mid_price=None,
            spread_bps=None,
            source="no_data",
            as_of=_now_utc(),
            depth_available=False,
            session_label="глубина недоступна",
            depth_unavailable_reason=_join_reasons([*prior, f"Yahoo: {_exc_reason(exc)}"]),
        )

    bids: list[OrderBookLevel] = []
    asks: list[OrderBookLevel] = []
    bid = quote.get("bid")
    ask = quote.get("ask")
    if bid and float(bid) > 0:
        bids.append(OrderBookLevel(price=float(bid), size=0.0))
    if ask and float(ask) > 0:
        asks.append(OrderBookLevel(price=float(ask), size=0.0))
    if not bids and not asks:
        return OrderBookSnapshot(
            ticker=sym,
            bids=[],
            asks=[],
            mid_price=None,
            spread_bps=None,
            source="no_data",
            as_of=_now_utc(),
            depth_available=False,
            session_label="глубина недоступна",
            depth_unavailable_reason=_join_reasons([*prior, "Yahoo: нет bid/ask"]),
        )

    reason = _join_reasons(
        [
            *prior,
            "Yahoo NBBO без объёмов (fallback; L2 недоступен)",
        ]
    )
    # If keyed US providers were configured/tried, do not pretend Yahoo is the only story.
    label = (
        "глубина недоступна · fallback после Alpaca/Polygon"
        if prior
        else "глубина недоступна · Yahoo NBBO"
    )
    snap = _thin_nbbo_snapshot(
        sym,
        bids=bids,
        asks=asks,
        source="yfinance_nbbo_thin",
        session_label=label,
        depth_unavailable_reason=reason,
    )
    try:
        await cache_set(cache_key, snap.model_dump(mode="json"), ttl=_US_NBBO_CACHE_TTL)
    except Exception:
        raise
    return snap


async def fetch_order_book(ticker: str, *, levels: int = 20) -> OrderBookSnapshot:
    """Route to Binance / MOEX ISS / Alpaca+Polygon based on ticker class."""
    from app.services.market_data.binance_spot import is_crypto_ticker
    from app.services.market_data.moex_currency import is_moex_currency_ticker
    from app.services.market_data.moex_spot import is_moex_ticker, resolve_moex_ticker
    from app.services.orders.order_book_session import enrich_order_book_session

    raw = ticker.strip().upper()
    if not raw:
        return enrich_order_book_session(_empty_snapshot(ticker, source="no_data"), raw)

    if is_crypto_ticker(raw):
        book = await _fetch_binance_depth(raw, levels=levels)
    elif is_moex_currency_ticker(raw):
        book = await _fetch_moex_currency_depth(raw, levels=levels)
    elif is_moex_ticker(raw) or await resolve_moex_ticker(raw):
        book = await _fetch_moex_depth(raw, levels=levels)
    else:
        book = await _fetch_alpaca_depth(raw, levels=levels)

    return enrich_order_book_session(book, raw)
