"""
Apex Intel — Coinglass connector (requires COINGLASS_API_KEY).

DEPRECATED / SKIP — paid API; not deployed. See backend/data/README.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx
import redis.asyncio as redis

from settings import COINGLASS_API_KEY, REDIS_URL, STREAM_COINGLASS_DERIVATIVES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coinglass_client")

POLL_INTERVAL_SEC = int(os.environ.get("COINGLASS_POLL_INTERVAL_SEC", "15"))
BASE_URL = "https://open-api-v4.coinglass.com/api"
SYMBOLS = [
    s.strip().upper()
    for s in os.environ.get("COINGLASS_SYMBOLS", "BTC,ETH").split(",")
    if s.strip()
]


async def fetch_funding_rate(client: httpx.AsyncClient, symbol: str, api_key: str) -> dict:
    resp = await client.get(
        f"{BASE_URL}/futures/funding-rate",
        params={"symbol": symbol},
        headers={"coinglassSecret": api_key},
    )
    resp.raise_for_status()
    return resp.json()


async def run() -> None:
    api_key = COINGLASS_API_KEY or os.environ["COINGLASS_API_KEY"]
    r = redis.from_url(REDIS_URL, decode_responses=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            for symbol in SYMBOLS:
                try:
                    data = await fetch_funding_rate(client, symbol, api_key)
                    payload = {"symbol": symbol, "data": data}
                    await r.xadd(
                        STREAM_COINGLASS_DERIVATIVES,
                        {"payload": json.dumps(payload)},
                        maxlen=50_000,
                        approximate=True,
                    )
                    log.info("coinglass %s fetched", symbol)
                except Exception as exc:
                    log.warning("failed to fetch coinglass %s: %s", symbol, exc)
            await asyncio.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(run())
