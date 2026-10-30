"""Post-deploy proof for order book reasons (no secrets)."""
from __future__ import annotations

import asyncio
import json

from app.services.orders.order_book import fetch_order_book


async def main() -> None:
    for t in ["NVDA", "QQQ", "SBER", "BTCUSDT"]:
        book = await fetch_order_book(t, levels=10)
        print(
            json.dumps(
                {
                    "ticker": t,
                    "source": book.source,
                    "depth_available": book.depth_available,
                    "session_label": book.session_label,
                    "depth_unavailable_reason": book.depth_unavailable_reason,
                    "session_status": book.session_status,
                    "session_message_ru": book.session_message_ru,
                    "exchange_id": book.exchange_id,
                    "bids": len(book.bids),
                    "asks": len(book.asks),
                    "mid": book.mid_price,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
