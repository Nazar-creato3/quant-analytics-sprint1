"""Slippage estimation using real order book depth (spec B.3)."""
from __future__ import annotations

from app.core.logging import get_logger
from app.schemas.orders import SlippageEstimate
from app.services.orders.order_book import fetch_order_book

logger = get_logger(__name__)

SLIPPAGE_WARN_BPS = 25.0


async def estimate_slippage(ticker: str, order_notional_usd: float) -> SlippageEstimate:
    book = await fetch_order_book(ticker)
    visible_asks = sum(level.price * level.size for level in book.asks[:5])
    visible_bids = sum(level.price * level.size for level in book.bids[:5])
    visible = max(visible_asks, visible_bids)
    if visible <= 0 or not book.mid_price:
        return SlippageEstimate(
            estimated_slippage_bps=0.0,
            estimated_avg_fill=book.mid_price,
            warning=None,
            visible_liquidity_usd=0.0,
        )

    participation = order_notional_usd / visible if visible > 0 else 0
    est_bps = min(participation * 15.0, 150.0)
    warning = None
    if est_bps >= SLIPPAGE_WARN_BPS:
        warning = (
            f"Размер ордера ~{order_notional_usd:,.0f} USD может вызвать проскальзывание "
            f"~{est_bps:.0f} bps относительно видимой ликвидности."
        )

    return SlippageEstimate(
        estimated_slippage_bps=round(est_bps, 2),
        estimated_avg_fill=book.mid_price,
        warning=warning,
        visible_liquidity_usd=round(visible, 2),
    )
