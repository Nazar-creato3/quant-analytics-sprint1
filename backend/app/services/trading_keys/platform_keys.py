"""Flow A — company-owned platform keys for market data (never user trading keys).

Reads PLATFORM_* env vars first, then falls back to legacy ALPACA_*/FMP_* names
so existing deployments keep working until dedicated platform accounts are wired.
"""
from __future__ import annotations

import os
from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger(__name__)

# Legacy env name → optional dedicated platform override prefix.
_PLATFORM_OVERRIDES: dict[str, str] = {
    "ALPACA_API_KEY": "PLATFORM_ALPACA_API_KEY",
    "ALPACA_SECRET_KEY": "PLATFORM_ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL": "PLATFORM_ALPACA_DATA_BASE_URL",
    "FMP_API_KEY": "PLATFORM_FMP_API_KEY",
    "FINNHUB_API_KEY": "PLATFORM_FINNHUB_API_KEY",
    "MARKETSTACK_API_KEY": "PLATFORM_MARKETSTACK_API_KEY",
    "POLYGON_API_KEY": "PLATFORM_POLYGON_API_KEY",
    "ALPHA_VANTAGE_API_KEY": "PLATFORM_ALPHA_VANTAGE_API_KEY",
    "BINANCE_API_KEY": "PLATFORM_BINANCE_API_KEY",
    "BINANCE_API_SECRET": "PLATFORM_BINANCE_API_SECRET",
    "TINKOFF_API_TOKEN": "PLATFORM_TINKOFF_API_TOKEN",
    "TINKOFF_TOKEN": "PLATFORM_TINKOFF_API_TOKEN",
    "INVEST_TOKEN": "PLATFORM_TINKOFF_API_TOKEN",
    "MOEX_API_TOKEN": "PLATFORM_MOEX_API_TOKEN",
    "MOEX_USERNAME": "PLATFORM_MOEX_USERNAME",
    "MOEX_PASSWORD": "PLATFORM_MOEX_PASSWORD",
}


def platform_env(name: str, *, default: str = "") -> str:
    """Resolve a platform-scoped secret; never reads user vault paths."""
    override = _PLATFORM_OVERRIDES.get(name)
    if override:
        val = os.environ.get(override, "").strip()
        if val:
            return val
    return os.environ.get(name, default).strip()


def platform_key_configured(name: str) -> bool:
    return bool(platform_env(name))


def moex_platform_configured() -> bool:
    """Platform MOEX ISS credentials for market data (order book, fundamentals)."""
    return bool(
        platform_env("MOEX_API_TOKEN")
        or (platform_env("MOEX_USERNAME") and platform_env("MOEX_PASSWORD"))
    )


def tinkoff_platform_configured() -> bool:
    """Platform T-Bank token for MOEX market data fallback (never user vault keys)."""
    return tinkoff_market_data_token() is not None


def tinkoff_market_data_token() -> str | None:
    """Live T-Invest token for quotes/order book. Never user Settings keys, never sandbox token."""
    for name in ("TINKOFF_API_TOKEN", "TINKOFF_TOKEN", "INVEST_TOKEN"):
        token = platform_env(name)
        if token:
            return token
    return None


@lru_cache(maxsize=1)
def alpaca_data_headers() -> dict[str, str]:
    key = platform_env("ALPACA_API_KEY")
    secret = platform_env("ALPACA_SECRET_KEY")
    if not key or not secret:
        return {}
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def log_platform_key_source() -> None:
    """Startup hint — which platform overrides are active (no secret values)."""
    active = [legacy for legacy, plat in _PLATFORM_OVERRIDES.items() if os.environ.get(plat, "").strip()]
    if active:
        logger.info("Platform key overrides active", keys=active)
