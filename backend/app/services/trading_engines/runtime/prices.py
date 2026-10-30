"""Resolve close prices for engine actions. Do not invent a series."""
from __future__ import annotations

from typing import Any


def resolve_close_prices(kwargs: dict[str, Any] | None, *, default_bars: int = 80) -> list[float]:
    raw = kwargs or {}
    prices = raw.get("prices")
    if not prices and isinstance(raw.get("payload"), dict):
        prices = raw["payload"].get("prices")
    if prices:
        out = [float(p) for p in prices if p is not None]
        if len(out) >= 8:
            return out

    symbol = raw.get("symbol")
    if not symbol and isinstance(raw.get("payload"), dict):
        symbol = raw["payload"].get("symbol")
    if symbol:
        from app.services.trading_engines.runtime.alpaca_data import fetch_daily_closes_sync

        alpaca = fetch_daily_closes_sync(str(symbol), limit=max(int(default_bars), 60))
        if len(alpaca) >= 8:
            return alpaca

    raise ValueError("нет данных")
