"""Probe TwelveData / Tiingo quotes for depth fallback (no secret echo)."""
from __future__ import annotations

import asyncio
import json


async def main() -> None:
    from app.services.market_data.http_providers import TwelveDataClient, TiingoClient

    for name, client in [("twelvedata", TwelveDataClient()), ("tiingo", TiingoClient())]:
        try:
            q = await client.get_latest_quote("NVDA")
            print(
                json.dumps(
                    {
                        "provider": name,
                        "ok": True,
                        "bid": q.get("bid"),
                        "ask": q.get("ask"),
                        "price": q.get("price"),
                        "bid_size": q.get("bid_size"),
                        "ask_size": q.get("ask_size"),
                        "keys": sorted(q.keys()),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"provider": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    asyncio.run(main())
