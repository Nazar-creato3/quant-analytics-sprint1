"""Probe Polygon quotes for order-book fallback (no secret echo)."""
from __future__ import annotations

import asyncio
import json

import httpx


async def main() -> None:
    from app.core.config import settings
    from app.services.orders.order_book import _fetch_polygon_quote_depth, fetch_order_book

    key_set = bool(settings.POLYGON_API_KEY)
    print(json.dumps({"polygon_key_set": key_set, "len": len(settings.POLYGON_API_KEY or "")}))

    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0)) as client:
        for path, params in [
            ("/v3/quotes/NVDA", {"limit": 5, "sort": "timestamp", "order": "desc"}),
            ("/v2/snapshot/locale/us/markets/stocks/tickers/NVDA", {}),
            ("/v2/last/nbbo/NVDA", {}),
            ("/v3/quotes/QQQ", {"limit": 5, "sort": "timestamp", "order": "desc"}),
        ]:
            p = dict(params)
            p["apiKey"] = settings.POLYGON_API_KEY
            try:
                r = await client.get(f"https://api.polygon.io{path}", params=p)
                body = r.text[:350].replace("\n", " ")
                # scrub key if echoed
                body = body.replace(settings.POLYGON_API_KEY, "REDACTED")
                print(json.dumps({"path": path, "status": r.status_code, "body": body}, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"path": path, "error": f"{type(exc).__name__}: {exc}"}))

    poly = await _fetch_polygon_quote_depth("NVDA", levels=10)
    print(
        json.dumps(
            {
                "polygon_fetch": None
                if poly is None
                else {
                    "source": poly.source,
                    "bids": len(poly.bids),
                    "asks": len(poly.asks),
                    "bid0": [poly.bids[0].price, poly.bids[0].size] if poly.bids else None,
                    "ask0": [poly.asks[0].price, poly.asks[0].size] if poly.asks else None,
                    "depth_available": poly.depth_available,
                }
            },
            ensure_ascii=False,
        )
    )

    book = await fetch_order_book("NVDA", levels=10)
    print(
        json.dumps(
            {
                "fetch_order_book_NVDA": {
                    "source": book.source,
                    "session_label": book.session_label,
                    "depth_available": book.depth_available,
                    "bids": len(book.bids),
                    "asks": len(book.asks),
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
