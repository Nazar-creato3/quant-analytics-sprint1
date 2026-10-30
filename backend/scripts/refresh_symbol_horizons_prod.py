#!/usr/bin/env python3
"""Refresh per-symbol horizon cache from DB bars (prod one-shot)."""
from __future__ import annotations

import asyncio

from app.db.session import AsyncSessionLocal
from app.services.forecast.symbol_horizon import refresh_symbol_horizon_cache
from app.services.market_data.bars import get_bars_for_chart


async def main() -> None:
    symbols = ["AAPL", "MSFT", "SPY"]
    price_map: dict[str, list[float]] = {}
    async with AsyncSessionLocal() as session:
        for sym in symbols:
            bars = await get_bars_for_chart(session, sym, "1d", 504, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            if len(closes) >= 60:
                price_map[sym] = closes
    horizons = refresh_symbol_horizon_cache(price_map, use_ensemble=False)
    print("symbol_horizons:", horizons)


if __name__ == "__main__":
    asyncio.run(main())
