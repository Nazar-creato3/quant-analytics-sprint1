"""Top-of-book quotes from the same Terminal order-book fetchers.

Does not invent depth. Missing book → empty dict (desk_overlay keeps ATR% path).
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.core.logging import get_logger

logger = get_logger(__name__)


def top_of_book(snapshot: Any | None) -> dict[str, Any]:
    """Best bid/ask + sizes from an OrderBookSnapshot. Size 0 is treated as missing."""
    if snapshot is None:
        return {}
    bids = list(getattr(snapshot, "bids", None) or [])
    asks = list(getattr(snapshot, "asks", None) or [])
    if not bids or not asks:
        return {}
    try:
        best_bid = max(bids, key=lambda lvl: float(lvl.price))
        best_ask = min(asks, key=lambda lvl: float(lvl.price))
        bid = float(best_bid.price)
        ask = float(best_ask.price)
        bid_sz = float(getattr(best_bid, "size", 0.0) or 0.0)
        ask_sz = float(getattr(best_ask, "size", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        return {}
    if bid <= 0 or ask <= 0:
        return {}
    return {
        "bid": bid,
        "ask": ask,
        "bid_sz": bid_sz if bid_sz > 0 else None,
        "ask_sz": ask_sz if ask_sz > 0 else None,
        "source": getattr(snapshot, "source", None),
        "have_quoted_spread": True,
    }


def quotes_for_desk(quotes: Mapping[str, Any] | None) -> dict[str, float | None]:
    if not quotes:
        return {"bid": None, "ask": None, "bid_sz": None, "ask_sz": None}
    return {
        "bid": quotes.get("bid"),
        "ask": quotes.get("ask"),
        "bid_sz": quotes.get("bid_sz"),
        "ask_sz": quotes.get("ask_sz"),
    }


async def prefetch_book_quotes(
    tickers: list[str],
    *,
    limit: int = 15,
    timeout_sec: float = 4.0,
) -> dict[str, dict[str, Any]]:
    """Fetch live books via fetch_order_book (Binance / MOEX / Alpaca+Yahoo NBBO)."""
    from app.services.orders.order_book import fetch_order_book

    out: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tickers:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        ordered.append(sym)
        if len(ordered) >= max(1, int(limit)):
            break

    sem = asyncio.Semaphore(4)

    async def _one(sym: str) -> None:
        async with sem:
            try:
                snap = await asyncio.wait_for(fetch_order_book(sym), timeout=timeout_sec)
            except Exception as exc:
                logger.info("book_quote_prefetch_failed", ticker=sym, error=str(exc)[:160])
                return
            q = top_of_book(snap)
            if not q:
                logger.info("book_quote_prefetch_empty", ticker=sym, source=getattr(snap, "source", None))
                return
            out[sym] = q
            logger.info(
                "book_quote_prefetch_ok",
                ticker=sym,
                bid=q["bid"],
                ask=q["ask"],
                have_quoted_spread=True,
                source=q.get("source"),
            )

    await asyncio.gather(*(_one(s) for s in ordered))
    return out
