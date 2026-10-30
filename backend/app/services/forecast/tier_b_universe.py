"""Tier B: liquid names we can retrain daily without paid PIT vendors."""
from __future__ import annotations

from app.core.config import settings

TIER_B_US = (
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "JPM", "V", "UNH", "XOM", "JNJ", "PG", "HD", "BAC", "AMD", "NFLX",
)
TIER_B_CRYPTO = ("BTC-USD", "ETH-USD", "SOL-USD")


def daily_retrain_symbols(watchlist: list[str] | None = None) -> list[str]:
    """Watchlist (tier A) ∪ liquid extras (tier B). Deduped, uppercased."""
    out: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        key = sym.strip().upper()
        if key and key not in seen:
            seen.add(key)
            out.append(key)

    for sym in watchlist or settings.default_watchlist_list:
        add(sym)
    for sym in TIER_B_US:
        add(sym)
    for sym in TIER_B_CRYPTO:
        add(sym)
    return out
