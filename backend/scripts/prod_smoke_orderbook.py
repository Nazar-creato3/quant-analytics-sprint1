"""One-shot prod smoke test for order book + recent trades."""
from __future__ import annotations

import asyncio
import json

from app.services.orders.order_book import fetch_order_book
from app.services.orders.recent_trades import fetch_recent_trades


async def main() -> None:
    tickers = ["GOOGL", "AMZN", "TSLA", "SBER", "GAZP", "BTCUSDT", "ADAUSDT"]
    for t in tickers:
        book = await fetch_order_book(t, levels=10)
        trades = await fetch_recent_trades(t, limit=3)
        payload = {
            "ticker": t,
            "book": {
                "source": book.source,
                "depth_available": book.depth_available,
                "session_label": book.session_label,
                "depth_unavailable_reason": book.depth_unavailable_reason,
                "exchange_id": book.exchange_id,
                "session_status": book.session_status,
                "session_message_ru": book.session_message_ru,
                "bid_levels": len(book.bids),
                "ask_levels": len(book.asks),
                "bid_sizes": [b.size for b in book.bids[:3]],
                "ask_sizes": [a.size for a in book.asks[:3]],
                "mid": book.mid_price,
                "spread_bps": book.spread_bps,
            },
            "trades_count": len(trades),
            "trades_source": trades[0].source if trades else None,
            "first_trade_price": trades[0].price if trades else None,
        }
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
