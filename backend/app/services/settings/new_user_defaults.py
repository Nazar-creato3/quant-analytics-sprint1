"""Seed settings for newly registered users."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings.watchlist import sync_default_watchlist
from app.utils.cache import cache_set
from app.utils.helpers import get_user_settings_key

SETTINGS_TTL = 60 * 60 * 24 * 365

NEW_USER_WATCHLIST = [
    "SBER",
    "GAZP",
    "LKOH",
    "YDEX",
    "ROSN",
    "GMKN",
    "PLZL",
    "MOEX",
    "IMOEX",
    "AAPL",
    "NVDA",
    "SPY",
    "BTC-USD",
]


# Simulated starting cash for demo / trial paper trading. Not real money.
DEMO_PAPER_EQUITY_USD = 10_000.0


def new_user_settings_payload() -> dict:
    return {
        "portfolio_size": DEMO_PAPER_EQUITY_USD,
        "paper_equity_usd": DEMO_PAPER_EQUITY_USD,
        "max_risk_per_trade_pct": 2.0,
        "confidence_threshold": 0.5,
        "daily_max_loss_pct": 5.0,
        "default_watchlist": list(NEW_USER_WATCHLIST),
    }


async def seed_new_user_settings(db: AsyncSession, email: str) -> None:
    payload = new_user_settings_payload()
    key = get_user_settings_key(email)
    await cache_set(key, payload, ttl=SETTINGS_TTL)
    await sync_default_watchlist(db, email, payload["default_watchlist"])
