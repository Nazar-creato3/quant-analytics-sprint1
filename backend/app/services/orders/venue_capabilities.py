"""Venue order-ticket capabilities. Platform never extends credit (Flow B relay only)."""
from __future__ import annotations

from typing import Literal

TimeInForce = Literal["gtc", "ioc", "fok", "day", "gtd"]

# Spot/equity venues currently wired for execution. Futures leverage is NOT
# exposed unless a venue executor explicitly sets leverage_supported.
VENUE_TIF: dict[str, tuple[TimeInForce, ...]] = {
    "binance": ("gtc", "ioc", "fok"),
    "alpaca": ("gtc", "day", "ioc", "fok"),
    "tinkoff": ("gtc", "day"),
    "paper": ("gtc", "day", "gtd", "ioc", "fok"),
    "bybit": ("gtc", "ioc", "fok"),
}

VENUE_POST_ONLY: dict[str, bool] = {
    "binance": True,  # enforced locally (spot has no GTX); reject if would take
    "alpaca": True,
    "tinkoff": True,
    "paper": True,
    "bybit": True,
}

VENUE_TAKER_FEE: dict[str, float] = {
    "binance": 0.001,
    "alpaca": 0.0,
    "tinkoff": 0.0005,
    "paper": 0.001,
    "bybit": 0.001,
}

# Leverage selector is shown ONLY when the connected venue API actually
# supports margin on its own books. Current executors are spot/cash.
VENUE_LEVERAGE_API: dict[str, bool] = {
    "binance": False,  # BinanceUserExecutor is spot
    "alpaca": False,   # cash/margin exists but no leverage multiplier API in executor
    "tinkoff": False,
    "paper": False,
    "bybit": False,
}


def tif_for_venue(venue: str | None) -> tuple[TimeInForce, ...]:
    if not venue:
        return ("gtc", "ioc", "fok")
    return VENUE_TIF.get(venue.lower(), ("gtc",))


def fee_rate_for_venue(venue: str | None, *, maker: bool = False) -> float:
    base = VENUE_TAKER_FEE.get((venue or "").lower(), 0.001)
    if maker:
        return max(0.0, base * 0.8)
    return base


def leverage_supported(venue: str | None) -> bool:
    if not venue:
        return False
    return bool(VENUE_LEVERAGE_API.get(venue.lower(), False))
