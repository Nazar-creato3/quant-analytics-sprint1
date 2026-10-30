"""
Apex Intel — Tinkoff Invest API realtime connector (requires TINKOFF_TOKEN).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import redis.asyncio as redis
from tinkoff.invest import AsyncClient
from tinkoff.invest.schemas import CandleInstrument, SubscriptionInterval
from tinkoff.invest.utils import quotation_to_decimal

from settings import REDIS_URL, STREAM_TINKOFF_CANDLES, TINKOFF_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tinkoff_client")

FIGI_LIST = [
    s.strip()
    for s in os.environ.get("TINKOFF_FIGI_LIST", "BBG004730N88,BBG004730RP0").split(",")
    if s.strip()
]

RECONNECT_DELAY_SEC = float(os.environ.get("TINKOFF_RECONNECT_DELAY_SEC", "5"))


def _resolve_token() -> str:
    token = TINKOFF_TOKEN or os.environ.get("TINKOFF_TOKEN") or os.environ.get("TINKOFF_API_TOKEN")
    if not token:
        raise RuntimeError("TINKOFF_TOKEN or TINKOFF_API_TOKEN is required for tinkoff-client")
    return token


async def _stream_once(token: str, r: redis.Redis) -> None:
    instruments = [
        CandleInstrument(
            figi=figi,
            interval=SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_MINUTE,
        )
        for figi in FIGI_LIST
    ]

    async with AsyncClient(token) as client:
        stream = client.create_market_data_stream()
        stream.candles.subscribe(instruments)
        log.info("Subscribed to Tinkoff candles for %s", ", ".join(FIGI_LIST))

        async for event in stream:
            if not event.candle or not event.candle.figi:
                continue
            c = event.candle
            payload = {
                "figi": c.figi,
                "open": str(quotation_to_decimal(c.open)),
                "close": str(quotation_to_decimal(c.close)),
                "high": str(quotation_to_decimal(c.high)),
                "low": str(quotation_to_decimal(c.low)),
                "volume": c.volume,
                "time": c.time.isoformat() if c.time else "",
            }
            await r.xadd(
                STREAM_TINKOFF_CANDLES,
                {"payload": json.dumps(payload)},
                maxlen=100_000,
                approximate=True,
            )
            log.info("candle %s close=%s", c.figi, payload["close"])


async def run() -> None:
    token = _resolve_token()
    r = redis.from_url(REDIS_URL, decode_responses=True)

    while True:
        try:
            await _stream_once(token, r)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "Tinkoff stream error (%s: %s), reconnecting in %ss...",
                type(exc).__name__,
                exc,
                RECONNECT_DELAY_SEC,
            )
            await asyncio.sleep(RECONNECT_DELAY_SEC)


if __name__ == "__main__":
    asyncio.run(run())