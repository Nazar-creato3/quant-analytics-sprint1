"""
Apex Intel — MOEX ISS connector.
Official MOEX API for reference quotes; short polling interval.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import redis.asyncio as redis

from settings import MOEX_POLL_INTERVAL_SEC, MOEX_TICKERS, REDIS_URL, STREAM_MOEX_QUOTES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("moex_iss")

BASE_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"


async def fetch_quote(client: httpx.AsyncClient, ticker: str) -> dict | None:
    url = BASE_URL.format(ticker=ticker)
    resp = await client.get(url, params={"iss.meta": "off"})
    resp.raise_for_status()
    data = resp.json()

    marketdata = data.get("marketdata", {})
    columns = marketdata.get("columns", [])
    rows = marketdata.get("data", [])
    if not rows:
        return None

    row = dict(zip(columns, rows[0]))
    return {
        "ticker": ticker,
        "last": row.get("LAST"),
        "bid": row.get("BID"),
        "offer": row.get("OFFER"),
        "volume": row.get("VOLTODAY"),
        "time": row.get("TIME"),
    }


async def run() -> None:
    r = redis.from_url(REDIS_URL, decode_responses=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            for ticker in MOEX_TICKERS:
                try:
                    quote = await fetch_quote(client, ticker)
                    if quote:
                        await r.xadd(
                            STREAM_MOEX_QUOTES,
                            {"payload": json.dumps(quote)},
                            maxlen=50_000,
                            approximate=True,
                        )
                        log.info("moex %s last=%s", ticker, quote["last"])
                except Exception as exc:
                    log.warning("failed to fetch %s: %s", ticker, exc)
            await asyncio.sleep(MOEX_POLL_INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(run())
