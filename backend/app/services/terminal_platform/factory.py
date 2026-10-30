"""Factory for the default terminal ProviderRouter."""
from __future__ import annotations

from functools import lru_cache

from app.services.terminal_platform.providers.alpha_vantage import AlphaVantageDataProvider
from app.services.terminal_platform.providers.binance_public import BinancePublicDataProvider
from app.services.terminal_platform.providers.ccxt_provider import CCXTProvider
from app.services.terminal_platform.providers.cbr import CbrDataProvider
from app.services.terminal_platform.providers.fmp import FmpDataProvider
from app.services.terminal_platform.providers.forex import ForexDataProvider
from app.services.terminal_platform.providers.fred import FredDataProvider
from app.services.terminal_platform.providers.imf import ImfDataProvider
from app.services.terminal_platform.providers.keyed_market import (
    AlpacaDataProvider,
    CoinGeckoDataProvider,
    FinnhubDataProvider,
    PolygonDataProvider,
    TiingoDataProvider,
    TwelveDataDataProvider,
)
from app.services.terminal_platform.providers.marketstack import MarketstackProvider
from app.services.terminal_platform.providers.moex_iss import MoexIssDataProvider
from app.services.terminal_platform.providers.public_macro import (
    EcbDataProvider,
    EiaDataProvider,
    EurostatLiveProvider,
    OecdDataProvider,
)
from app.services.terminal_platform.providers.rosstat import RosstatDataProvider
from app.services.terminal_platform.providers.stooq import StooqDataProvider
from app.services.terminal_platform.providers.world_bank import WorldBankDataProvider
from app.services.terminal_platform.providers.yfinance import YFinanceDataProvider
from app.services.terminal_platform.router import ProviderRouter
from app.services.terminal_platform.types import CircuitBreakerConfig


def build_default_providers() -> list:
    """Instantiate all terminal data providers (keys optional — degrade gracefully)."""
    return [
        BinancePublicDataProvider(),
        CCXTProvider("binance"),
        CCXTProvider("bybit"),
        CCXTProvider("okx"),
        CoinGeckoDataProvider(),
        ForexDataProvider(),
        MoexIssDataProvider(),
        AlpacaDataProvider(),
        PolygonDataProvider(),
        TwelveDataDataProvider(),
        TiingoDataProvider(),
        MarketstackProvider(),
        FinnhubDataProvider(),
        CbrDataProvider(),
        RosstatDataProvider(),
        FredDataProvider(),
        EiaDataProvider(),
        EcbDataProvider(),
        OecdDataProvider(),
        EurostatLiveProvider(),
        ImfDataProvider(),
        WorldBankDataProvider(),
        StooqDataProvider(),
        YFinanceDataProvider(),
        AlphaVantageDataProvider(),
        FmpDataProvider(),
    ]


@lru_cache(maxsize=1)
def get_terminal_router() -> ProviderRouter:
    """Process-wide singleton router used by FastAPI endpoints."""
    # Higher threshold + longer cooldown: one AV rate-limit must not kill Terminal.
    router = ProviderRouter(
        build_default_providers(),
        circuit_config=CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout_seconds=180.0,
            half_open_max_calls=2,
        ),
        cache_ttl_seconds=120,
    )
    return router


def reset_terminal_router() -> None:
    """Clear singleton (tests)."""
    get_terminal_router.cache_clear()
