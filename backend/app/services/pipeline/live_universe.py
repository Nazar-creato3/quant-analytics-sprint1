"""Universe for maneuver selection in «Боевой»: only what the user's brokers can trade.

T-Bank and Finam (as connected here) trade the Moscow Exchange. Proposing Apple or
an American fund to someone whose only live account is at T-Bank gives ideas
that cannot be approved, so in live mode the watchlist is cut to MOEX tickers.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

MOEX_BROKERS = frozenset({"tinkoff", "tbank", "finam"})


def is_moex(symbol: str) -> bool:
    from app.services.instrument.category import enrich_watchlist_entry

    return str(enrich_watchlist_entry(symbol).get("market") or "").startswith("moex")


def restrict_to_brokers(watchlist: list[str], live_venues: set[str]) -> list[str]:
    """Only MOEX brokers connected → MOEX tickers; any other live venue → unchanged."""
    venues = {v.lower() for v in live_venues}
    if not venues or not venues <= MOEX_BROKERS:
        return list(watchlist)
    return [t for t in watchlist if is_moex(t)]


async def live_venues(db: AsyncSession, user_id: str) -> set[str]:
    from app.services.trading_keys.resolver import list_user_connected_venues

    metas = await list_user_connected_venues(db, user_id)
    return {str(m.venue or "").lower() for m in metas if str(m.account_mode or "") == "live"}
