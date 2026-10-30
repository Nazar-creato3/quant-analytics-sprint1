"""Put the Russian market first in existing accounts' watchlists.

New accounts already get the Russian-first list. Accounts created earlier keep
their stored list; this adds the Russian tickers in front of it (nothing removed).
--full also appends the main US shares and funds that are missing (nothing removed).

    docker compose exec backend python -m app.scripts.watchlist_ru --email you@example.com
    docker compose exec backend python -m app.scripts.watchlist_ru --all
    docker compose exec backend python -m app.scripts.watchlist_ru --all --full
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

RU_FIRST = ["SBER", "GAZP", "LKOH", "YDEX", "ROSN", "GMKN", "PLZL", "MOEX", "IMOEX"]
GLOBAL = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ", "JPM", "V", "BTC-USD"]


def merge(current: list[str], full: bool = False) -> list[str]:
    """Russian tickers first, then the user's own order; with full, missing GLOBAL at the end."""
    merged = RU_FIRST + [t for t in current if t not in RU_FIRST]
    if full:
        merged += [t for t in GLOBAL if t not in merged]
    return merged


async def apply(email: str, full: bool = False) -> list[str]:
    from app.db.session import AsyncSessionLocal
    from app.services.settings.watchlist import get_effective_watchlist, sync_default_watchlist
    from app.utils.cache import cache_get, cache_set
    from app.utils.helpers import get_user_settings_key

    async with AsyncSessionLocal() as db:
        current = await get_effective_watchlist(db, email)
        merged = merge(current, full)
        await sync_default_watchlist(db, email, merged)
    key = get_user_settings_key(email)
    stored = await cache_get(key) or {}
    stored["default_watchlist"] = merged
    await cache_set(key, stored, ttl=60 * 60 * 24 * 365)
    return merged


async def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--email")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--full", action="store_true", help="добавить недостающие основные бумаги США и BTC")
    args = ap.parse_args()
    emails = [args.email.lower()] if args.email else []
    if args.all:
        from app.db.models import User
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            emails = [u.email for u in (await db.execute(select(User).where(User.is_active.is_(True)))).scalars()]
    from app.utils.cache import close_redis_client

    try:
        for e in emails:
            print(e, "→", ", ".join(await apply(e, args.full)))
    finally:
        await close_redis_client()


if __name__ == "__main__":
    asyncio.run(main())
