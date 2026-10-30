"""
Apex Intel — Redis Streams → TimescaleDB consumer.

Reads from ingestion streams via consumer groups, normalizes payloads,
and batch-writes to market_trades / ohlcv / derivatives_metrics tables.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg
import redis.asyncio as redis

from settings import (
    DATABASE_URL,
    REDIS_URL,
    STREAM_BATCH_SIZE,
    STREAM_BINANCE_DEPTH,
    STREAM_BINANCE_TRADES,
    STREAM_CONSUMER_GROUP,
    STREAM_FLUSH_INTERVAL_MS,
    STREAM_MOEX_QUOTES,
    STREAM_TINKOFF_CANDLES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stream_consumer")

STREAMS = [
    STREAM_BINANCE_TRADES,
    STREAM_BINANCE_DEPTH,
    STREAM_TINKOFF_CANDLES,
    STREAM_MOEX_QUOTES,
]

CONSUMER_NAME = f"{socket.gethostname()}"


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        if value.isdigit():
            return _parse_ts(int(value))
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _normalize_depth_levels(raw_levels: list[list[str]]) -> list[dict[str, str]]:
    levels: list[dict[str, str]] = []
    for level in raw_levels or []:
        if len(level) < 2:
            continue
        levels.append({"price": str(level[0]), "qty": str(level[1])})
    return levels


def _compute_spread_bps(
    bid_depth: list[dict[str, str]],
    ask_depth: list[dict[str, str]],
) -> Decimal | None:
    if not bid_depth or not ask_depth:
        return None
    try:
        best_bid = float(bid_depth[0]["price"])
        best_ask = float(ask_depth[0]["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
        return None
    mid = (best_bid + best_ask) / 2.0
    return _dec(round((best_ask - best_bid) / mid * 10_000, 4))


@dataclass
class PendingTrade:
    time: datetime
    symbol: str
    source: str
    instrument_type: str
    price: Decimal
    quantity: Decimal
    side: str | None
    trade_id: int | None
    stream: str
    msg_id: str


@dataclass
class PendingOhlcv:
    time: datetime
    symbol: str
    source: str
    instrument_type: str
    timeframe: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    stream: str
    msg_id: str


@dataclass
class PendingDeriv:
    time: datetime
    symbol: str
    source: str
    instrument_type: str
    metric_type: str
    value: Decimal
    side: str | None
    stream: str
    msg_id: str


@dataclass
class PendingOrderBook:
    time: datetime
    symbol: str
    source: str
    instrument_type: str
    bid_depth: list[dict[str, str]]
    ask_depth: list[dict[str, str]]
    spread_bps: Decimal | None
    stream: str
    msg_id: str


@dataclass
class Buffer:
    trades: list[PendingTrade] = field(default_factory=list)
    ohlcv: list[PendingOhlcv] = field(default_factory=list)
    deriv: list[PendingDeriv] = field(default_factory=list)
    order_books: list[PendingOrderBook] = field(default_factory=list)

    def size(self) -> int:
        return len(self.trades) + len(self.ohlcv) + len(self.deriv) + len(self.order_books)


class StreamConsumer:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._pool: asyncpg.Pool | None = None
        self._instrument_cache: dict[tuple[str, str], int] = {}
        self._buf = Buffer()
        self._flush_lock = asyncio.Lock()

    async def start(self) -> None:
        self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        await self._ensure_consumer_groups()
        log.info("Consumer %s started (group=%s)", CONSUMER_NAME, STREAM_CONSUMER_GROUP)
        await asyncio.gather(self._read_loop(), self._flush_loop())

    async def _ensure_consumer_groups(self) -> None:
        assert self._redis is not None
        for stream in STREAMS:
            try:
                await self._redis.xgroup_create(stream, STREAM_CONSUMER_GROUP, id="0", mkstream=True)
                log.info("Created consumer group %s on %s", STREAM_CONSUMER_GROUP, stream)
            except redis.ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def _get_instrument_id(
        self, conn: asyncpg.Connection, symbol: str, source: str, instrument_type: str
    ) -> int:
        key = (symbol, source)
        cached = self._instrument_cache.get(key)
        if cached is not None:
            return cached

        row = await conn.fetchrow(
            """
            INSERT INTO instruments (symbol, source, instrument_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (symbol, source) DO UPDATE SET symbol = EXCLUDED.symbol
            RETURNING id
            """,
            symbol,
            source,
            instrument_type,
        )
        instrument_id = int(row["id"])
        self._instrument_cache[key] = instrument_id
        return instrument_id

    def _parse_message(self, stream: str, msg_id: str, payload: dict) -> None:
        if stream == STREAM_BINANCE_TRADES:
            price = _dec(payload.get("price"))
            qty = _dec(payload.get("quantity"))
            if price is None or qty is None:
                return
            trade_id = payload.get("trade_id")
            self._buf.trades.append(
                PendingTrade(
                    time=_parse_ts(payload.get("event_time")),
                    symbol=str(payload["symbol"]),
                    source="binance",
                    instrument_type="spot",
                    price=price,
                    quantity=qty,
                    side=payload.get("side"),
                    trade_id=int(trade_id) if trade_id is not None else None,
                    stream=stream,
                    msg_id=msg_id,
                )
            )
        elif stream == STREAM_BINANCE_DEPTH:
            bid_depth = _normalize_depth_levels(payload.get("bids", []))
            ask_depth = _normalize_depth_levels(payload.get("asks", []))
            spread = _compute_spread_bps(bid_depth, ask_depth)
            self._buf.order_books.append(
                PendingOrderBook(
                    time=_parse_ts(payload.get("event_time")),
                    symbol=str(payload["symbol"]),
                    source="binance",
                    instrument_type="spot",
                    bid_depth=bid_depth,
                    ask_depth=ask_depth,
                    spread_bps=spread,
                    stream=stream,
                    msg_id=msg_id,
                )
            )
        elif stream == STREAM_TINKOFF_CANDLES:
            self._buf.ohlcv.append(
                PendingOhlcv(
                    time=_parse_ts(payload.get("time")),
                    symbol=str(payload["figi"]),
                    source="tinkoff",
                    instrument_type="stock",
                    timeframe="1m",
                    open=_dec(payload.get("open")),
                    high=_dec(payload.get("high")),
                    low=_dec(payload.get("low")),
                    close=_dec(payload.get("close")),
                    volume=_dec(payload.get("volume")),
                    stream=stream,
                    msg_id=msg_id,
                )
            )
        elif stream == STREAM_MOEX_QUOTES:
            last = _dec(payload.get("last"))
            if last is None:
                return
            bid = _dec(payload.get("bid"))
            offer = _dec(payload.get("offer"))
            self._buf.ohlcv.append(
                PendingOhlcv(
                    time=datetime.now(timezone.utc),
                    symbol=str(payload["ticker"]),
                    source="moex",
                    instrument_type="stock",
                    timeframe="tick",
                    open=last,
                    high=max(v for v in (last, bid, offer) if v is not None),
                    low=min(v for v in (last, bid, offer) if v is not None),
                    close=last,
                    volume=_dec(payload.get("volume")),
                    stream=stream,
                    msg_id=msg_id,
                )
            )
    async def _read_loop(self) -> None:
        assert self._redis is not None
        while True:
            try:
                results = await self._redis.xreadgroup(
                    groupname=STREAM_CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={s: ">" for s in STREAMS},
                    count=STREAM_BATCH_SIZE,
                    block=1000,
                )
                if not results:
                    continue

                for stream, messages in results:
                    for msg_id, fields in messages:
                        raw = fields.get("payload")
                        if not raw:
                            await self._redis.xack(stream, STREAM_CONSUMER_GROUP, msg_id)
                            continue
                        try:
                            payload = json.loads(raw)
                            self._parse_message(stream, msg_id, payload)
                        except json.JSONDecodeError:
                            log.warning("Invalid JSON in %s:%s", stream, msg_id)
                            await self._redis.xack(stream, STREAM_CONSUMER_GROUP, msg_id)

                if self._buf.size() >= STREAM_BATCH_SIZE:
                    await self._flush()
            except Exception as exc:
                log.exception("Read loop error: %s", exc)
                await asyncio.sleep(1)

    async def _flush_loop(self) -> None:
        interval = STREAM_FLUSH_INTERVAL_MS / 1000.0
        while True:
            await asyncio.sleep(interval)
            if self._buf.size():
                await self._flush()

    async def _flush(self) -> None:
        async with self._flush_lock:
            if not self._buf.size():
                return
            assert self._pool is not None and self._redis is not None

            buf, self._buf = self._buf, Buffer()
            acks: dict[str, list[str]] = {}

            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    if buf.trades:
                        rows = []
                        for item in buf.trades:
                            iid = await self._get_instrument_id(
                                conn, item.symbol, item.source, item.instrument_type
                            )
                            rows.append((item.time, iid, item.price, item.quantity, item.side, item.trade_id))
                            acks.setdefault(item.stream, []).append(item.msg_id)
                        await conn.executemany(
                            """
                            INSERT INTO market_trades (time, instrument_id, price, quantity, side, trade_id)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            rows,
                        )

                    if buf.ohlcv:
                        rows = []
                        for item in buf.ohlcv:
                            iid = await self._get_instrument_id(
                                conn, item.symbol, item.source, item.instrument_type
                            )
                            rows.append(
                                (
                                    item.time,
                                    iid,
                                    item.timeframe,
                                    item.open,
                                    item.high,
                                    item.low,
                                    item.close,
                                    item.volume,
                                )
                            )
                            acks.setdefault(item.stream, []).append(item.msg_id)
                        await conn.executemany(
                            """
                            INSERT INTO ohlcv (time, instrument_id, timeframe, open, high, low, close, volume)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            ON CONFLICT (instrument_id, timeframe, time) DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume
                            """,
                            rows,
                        )

                    if buf.deriv:
                        rows = []
                        for item in buf.deriv:
                            iid = await self._get_instrument_id(
                                conn, item.symbol, item.source, item.instrument_type
                            )
                            rows.append((item.time, iid, item.metric_type, item.value, item.side))
                            acks.setdefault(item.stream, []).append(item.msg_id)
                        await conn.executemany(
                            """
                            INSERT INTO derivatives_metrics (time, instrument_id, metric_type, value, side)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            rows,
                        )

                    if buf.order_books:
                        rows = []
                        for item in buf.order_books:
                            iid = await self._get_instrument_id(
                                conn, item.symbol, item.source, item.instrument_type
                            )
                            rows.append(
                                (
                                    item.time,
                                    iid,
                                    json.dumps(item.bid_depth),
                                    json.dumps(item.ask_depth),
                                    item.spread_bps,
                                )
                            )
                            acks.setdefault(item.stream, []).append(item.msg_id)
                        await conn.executemany(
                            """
                            INSERT INTO order_book_snapshots
                                (time, instrument_id, bid_depth, ask_depth, spread_bps)
                            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
                            """,
                            rows,
                        )

            for stream, ids in acks.items():
                await self._redis.xack(stream, STREAM_CONSUMER_GROUP, *ids)

            total = len(buf.trades) + len(buf.ohlcv) + len(buf.deriv) + len(buf.order_books)
            if total:
                log.info(
                    "Flushed %d rows (trades=%d ohlcv=%d deriv=%d depth=%d)",
                    total,
                    len(buf.trades),
                    len(buf.ohlcv),
                    len(buf.deriv),
                    len(buf.order_books),
                )


async def main() -> None:
    consumer = StreamConsumer()
    await consumer.start()


if __name__ == "__main__":
    asyncio.run(main())
