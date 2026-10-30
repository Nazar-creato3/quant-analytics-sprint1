"""VPS diag: Alpaca order-book chain (no secret echo)."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx


def _mask(v: str | None) -> dict[str, Any]:
    if not v:
        return {"set": False, "len": 0}
    s = str(v)
    low = s.lower()
    ph = any(x in low for x in ("your-", "changeme", "placeholder", "xxx", "example", "replace"))
    return {
        "set": True,
        "len": len(s),
        "prefix4": s[:4],
        "suffix3": s[-3:],
        "placeholderish": ph,
        "starts_PK": s.upper().startswith("PK"),
    }


async def probe_alpaca(sym: str = "NVDA") -> list[dict[str, Any]]:
    from app.core.config import settings

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
    }
    urls = [
        ("orderbook_beta", f"https://data.alpaca.markets/v1beta1/orderbooks/{sym}", {"limit": 10}),
        ("latest_quote_iex", f"https://data.alpaca.markets/v2/stocks/{sym}/quotes/latest", {"feed": "iex"}),
        ("latest_quote_sip", f"https://data.alpaca.markets/v2/stocks/{sym}/quotes/latest", {"feed": "sip"}),
        ("snapshots", "https://data.alpaca.markets/v2/stocks/snapshots", {"symbols": sym}),
        ("snapshots_iex", "https://data.alpaca.markets/v2/stocks/snapshots", {"symbols": sym, "feed": "iex"}),
        ("snapshots_sip", "https://data.alpaca.markets/v2/stocks/snapshots", {"symbols": sym, "feed": "sip"}),
    ]
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        for name, url, params in urls:
            try:
                r = await client.get(url, headers=headers, params=params)
                body = r.text[:400].replace("\n", " ")
                body = re.sub(r"(apiKey|secret|APCA-[A-Z-]+)=[^&\s\"]+", r"\1=REDACTED", body, flags=re.I)
                out.append({"name": name, "status": r.status_code, "body": body})
            except Exception as exc:  # noqa: BLE001
                out.append({"name": name, "status": None, "error": f"{type(exc).__name__}: {exc}"})
    return out


async def main() -> None:
    from app.core.config import MarketDataProvider, settings
    from app.services.market_data.client import _provider_api_keys_configured
    from app.services.market_data.http_providers import key_configured
    from app.services.orders.order_book import fetch_order_book

    print(
        json.dumps(
            {
                "ALPACA_API_KEY": _mask(settings.ALPACA_API_KEY),
                "ALPACA_SECRET_KEY": _mask(settings.ALPACA_SECRET_KEY),
                "POLYGON_API_KEY": _mask(getattr(settings, "POLYGON_API_KEY", None)),
                "ALPACA_BASE_URL": str(settings.ALPACA_BASE_URL),
                "alpaca_provider_configured": _provider_api_keys_configured(MarketDataProvider.ALPACA),
                "alpaca_key_configured": key_configured("alpaca"),
                "polygon_key_configured": key_configured("polygon"),
            },
            ensure_ascii=False,
        )
    )
    print("---ALPACA_HTTP---")
    for row in await probe_alpaca("NVDA"):
        print(json.dumps(row, ensure_ascii=False))
    print("---ORDER_BOOKS---")
    for t in ["NVDA", "QQQ", "SBER", "BTCUSDT"]:
        book = await fetch_order_book(t, levels=10)
        print(
            json.dumps(
                {
                    "ticker": t,
                    "source": book.source,
                    "depth_available": book.depth_available,
                    "session_label": book.session_label,
                    "session_status": book.session_status,
                    "session_message_ru": book.session_message_ru,
                    "exchange_id": book.exchange_id,
                    "bids": len(book.bids),
                    "asks": len(book.asks),
                    "bid0": [book.bids[0].price, book.bids[0].size] if book.bids else None,
                    "ask0": [book.asks[0].price, book.asks[0].size] if book.asks else None,
                    "mid": book.mid_price,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
