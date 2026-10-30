"""Shared environment configuration for realtime data connectors."""

from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


REDIS_URL: str = _env("REDIS_STREAMS_URL", _env("REDIS_URL", "redis://redis:6379/0"))
DATABASE_URL: str = _env(
    "DATABASE_URL_SYNC",
    _env(
        "DATABASE_URL",
        "postgresql://apex:changeme@postgres:5432/apex_intel",
    ),
)

STREAM_BINANCE_TRADES: str = _env("STREAM_BINANCE_TRADES", "raw:binance:trades")
STREAM_BINANCE_DEPTH: str = _env("STREAM_BINANCE_DEPTH", "raw:binance:depth")
STREAM_TINKOFF_CANDLES: str = _env("STREAM_TINKOFF_CANDLES", "raw:tinkoff:candles")
STREAM_MOEX_QUOTES: str = _env("STREAM_MOEX_QUOTES", "raw:moex:quotes")

STREAM_CONSUMER_GROUP: str = _env("STREAM_CONSUMER_GROUP", "apex-consumer")
STREAM_BATCH_SIZE: int = int(_env("STREAM_BATCH_SIZE", "500"))
STREAM_FLUSH_INTERVAL_MS: int = int(_env("STREAM_FLUSH_INTERVAL_MS", "500"))

BINANCE_SYMBOLS: list[str] = [
    s.strip().lower()
    for s in _env("BINANCE_SYMBOLS", "btcusdt,ethusdt,solusdt,bnbusdt").split(",")
    if s.strip()
]
MOEX_TICKERS: list[str] = [
    s.strip().upper()
    for s in _env("MOEX_TICKERS", "SBER,GAZP,LKOH,GMKN").split(",")
    if s.strip()
]
MOEX_POLL_INTERVAL_SEC: int = int(_env("MOEX_POLL_INTERVAL_SEC", "5"))
NEWS_POLL_INTERVAL_SEC: int = int(_env("NEWS_POLL_INTERVAL_SEC", "60"))

TINKOFF_TOKEN: str = _env("TINKOFF_TOKEN", _env("TINKOFF_API_TOKEN"))
