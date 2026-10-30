"""
Apex Intel — Binance realtime connector.
Subscribes to Binance trade + partial depth streams, publishes to Redis Streams,
and mirrors the latest trade price into Redis for sub-second chart quotes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as redis
import websockets

from settings import (
    BINANCE_SYMBOLS,
    REDIS_URL,
    STREAM_BINANCE_DEPTH,
    STREAM_BINANCE_TRADES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("binance_ws")

LIVE_WS_KEY_PREFIX = "live:binance:"
LIVE_WS_TTL = 60


def live_ws_cache_key(symbol: str) -> str:
    return f"{LIVE_WS_KEY_PREFIX}{symbol.lower()}"


def build_stream_url(symbols: list[str]) -> str:
    streams: list[str] = []
    for symbol in symbols:
        streams.append(f"{symbol}@trade")
        streams.append(f"{symbol}@depth20@100ms")
    joined = "/".join(streams)
    return f"wss://stream.binance.com:9443/stream?streams={joined}"


def _symbol_from_stream(stream_name: str) -> str | None:
    if not stream_name:
        return None
    base = stream_name.split("@", 1)[0]
    return base.upper() if base else None


def _depth_payload(symbol: str, data: dict) -> dict:
    bids = data.get("bids") or data.get("b", [])
    asks = data.get("asks") or data.get("a", [])
    return {
        "symbol": symbol,
        "event_time": data.get("E") or int(time.time() * 1000),
        "last_update_id": data.get("lastUpdateId"),
        "bids": bids,
        "asks": asks,
    }


async def consume() -> None:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    url = build_stream_url(BINANCE_SYMBOLS)

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                log.info("Connected to Binance WS: %s", url)
                async for raw_message in ws:
                    msg = json.loads(raw_message)
                    stream_name = str(msg.get("stream", ""))
                    data = msg.get("data", {})
                    if not data:
                        continue

                    if "@trade" in stream_name:
                        symbol = str(data["s"])
                        price = data["p"]
                        event_time = data["E"]

                        payload = {
                            "symbol": symbol,
                            "price": price,
                            "quantity": data["q"],
                            "trade_id": data["t"],
                            "side": "sell" if data["m"] else "buy",
                            "event_time": event_time,
                        }
                        await r.xadd(
                            STREAM_BINANCE_TRADES,
                            {"payload": json.dumps(payload)},
                            maxlen=100_000,
                            approximate=True,
                        )

                        await r.setex(
                            live_ws_cache_key(symbol),
                            LIVE_WS_TTL,
                            json.dumps(
                                {
                                    "symbol": symbol,
                                    "price": price,
                                    "event_time": event_time,
                                    "source": "binance_ws",
                                }
                            ),
                        )
                    elif "@depth" in stream_name:
                        symbol = _symbol_from_stream(stream_name)
                        if not symbol:
                            continue
                        payload = _depth_payload(symbol, data)
                        await r.xadd(
                            STREAM_BINANCE_DEPTH,
                            {"payload": json.dumps(payload)},
                            maxlen=100_000,
                            approximate=True,
                        )
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            log.warning("Connection lost (%s), reconnecting in 2s...", exc)
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(consume())
