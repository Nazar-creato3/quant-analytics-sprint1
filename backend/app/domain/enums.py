"""Core domain enumerations for Apex Intel."""
from __future__ import annotations

from enum import Enum


class AssetCategory(str, Enum):
    """Hierarchical asset taxonomy for instruments and sleeves."""

    EQUITIES = "equities"
    ETF = "etf"
    CRYPTO = "crypto"
    FX = "fx"
    COMMODITIES = "commodities"
    RATES_BONDS = "rates_bonds"
    INDICES = "indices"
    THEMATIC_BASKET = "thematic_basket"
    SECTOR_BASKET = "sector_basket"
    MACRO_HEDGE = "macro_hedge"
    EVENT_DRIVEN_WATCHLIST = "event_driven_watchlist"
    INCOME_SLEEVE = "income_sleeve"
    DEFENSIVE_SLEEVE = "defensive_sleeve"
    SPECULATIVE_SLEEVE = "speculative_sleeve"
    CUSTOM_USER_BASKET = "custom_user_basket"
    OTHER = "other"


# Parent category for hierarchical navigation (``None`` = root).
CATEGORY_PARENTS: dict[AssetCategory, AssetCategory | None] = {
    AssetCategory.EQUITIES: None,
    AssetCategory.ETF: None,
    AssetCategory.CRYPTO: None,
    AssetCategory.FX: None,
    AssetCategory.COMMODITIES: None,
    AssetCategory.RATES_BONDS: None,
    AssetCategory.INDICES: None,
    AssetCategory.THEMATIC_BASKET: AssetCategory.EQUITIES,
    AssetCategory.SECTOR_BASKET: AssetCategory.EQUITIES,
    AssetCategory.EVENT_DRIVEN_WATCHLIST: AssetCategory.EQUITIES,
    AssetCategory.MACRO_HEDGE: AssetCategory.RATES_BONDS,
    AssetCategory.INCOME_SLEEVE: None,
    AssetCategory.DEFENSIVE_SLEEVE: None,
    AssetCategory.SPECULATIVE_SLEEVE: None,
    AssetCategory.CUSTOM_USER_BASKET: None,
    AssetCategory.OTHER: None,
}


class InstrumentSource(str, Enum):
    FINAM = "finam"
    BINANCE = "binance"
    TINKOFF = "tinkoff"
    MOEX = "moex"


class TradableUnit(str, Enum):
    """How the instrument is sized at execution time."""

    PER_SHARE = "per_share"


class Strategy(str, Enum):
    GRID = "grid"
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    HEDGE = "hedge"
    INCOME = "income"
    ROTATION = "rotation"
    VOLATILITY_HARVESTING = "volatility_harvesting"


class SleeveStatus(str, Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    EXPERIMENTAL = "experimental"
