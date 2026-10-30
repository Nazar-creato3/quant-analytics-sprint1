"""Factory for the regulatory data provider."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.fundamental_data.composite import CompositeRegulatoryProvider
from app.services.fundamental_data.provider import FundamentalDataProvider


@lru_cache(maxsize=1)
def get_fundamental_data_provider() -> FundamentalDataProvider:
    settings = get_settings()
    return CompositeRegulatoryProvider(use_sidecar=bool(settings.ENABLE_OPENBB_SOURCE))


def reset_fundamental_data_provider_cache() -> None:
    get_fundamental_data_provider.cache_clear()
