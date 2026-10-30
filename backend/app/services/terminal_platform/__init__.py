"""Terminal platform data connectors package."""
from __future__ import annotations

from app.services.terminal_platform.factory import get_terminal_router, reset_terminal_router
from app.services.terminal_platform.models import (
    FetchResult,
    Fundamentals,
    MacroSeries,
    NewsItem,
    OHLCV,
    ProviderHealth,
    Quote,
)
from app.services.terminal_platform.router import ProviderRouter
from app.services.terminal_platform.types import DataType, Timeframe

__all__ = [
    "DataType",
    "FetchResult",
    "Fundamentals",
    "MacroSeries",
    "NewsItem",
    "OHLCV",
    "ProviderHealth",
    "ProviderRouter",
    "Quote",
    "Timeframe",
    "get_terminal_router",
    "reset_terminal_router",
]
