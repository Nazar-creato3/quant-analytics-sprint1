"""Where does manoeuvre generation spend its time on this server? One run, top functions.

    docker compose ... exec backend python -m app.scripts.profile_maneuvers

Loads daily bars for the default watchlist from the database (no provider calls), runs the
generator once under cProfile and prints the 25 most expensive call sites. Writes nothing.
"""
from __future__ import annotations

import asyncio
import cProfile
import io
import pstats
import time
from datetime import datetime, timedelta, timezone


async def load_bars() -> dict:
    from app.core.config import settings
    from app.services.pipeline.io import fetch_watchlist_bars_parallel

    tickers = [t.strip() for t in str(settings.DEFAULT_WATCHLIST).split(",") if t.strip()]
    end = datetime.now(timezone.utc)
    try:
        data, _ = await fetch_watchlist_bars_parallel(tickers, end - timedelta(days=300), end, bar_limit=210)
    finally:
        from app.utils.cache import close_redis_client

        await close_redis_client()  # otherwise "Event loop is closed" tracebacks at exit
    return data


def main() -> None:
    from app.services.risk.maneuver_generator import ManeuverGenerator

    t0 = time.monotonic()
    data = asyncio.run(load_bars())
    print(f"Бары загружены: {len(data)} бумаг за {time.monotonic() - t0:.1f} с", flush=True)
    gen = ManeuverGenerator(portfolio_size=10_000.0, confidence_threshold=None)
    prof = cProfile.Profile()
    t1 = time.monotonic()
    prof.enable()
    out = gen.generate(market_data=data)
    prof.disable()
    print(f"Манёвров: {len(out)}, генерация {time.monotonic() - t1:.1f} с\n", flush=True)
    buf = io.StringIO()
    stats = pstats.Stats(prof, stream=buf)
    stats.sort_stats("cumulative").print_stats(r"app/services", 25)
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    print("\n".join(lines[-27:]), flush=True)


if __name__ == "__main__":
    main()
