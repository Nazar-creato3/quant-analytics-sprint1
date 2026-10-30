"""Server-side enforcement for data-only instruments (no order execution)."""
from __future__ import annotations

from app.services.market_data.commodities_catalog import (
    COMMODITY_FEED_LABEL_RU,
    commodity_metadata_for_symbol,
    is_commodity_pair,
)
from app.services.market_data.forex_catalog import (
    FOREX_FEED_LABEL_RU,
    forex_metadata_for_symbol,
    is_forex_pair,
)
from app.services.market_data.marketstack_catalog import (
    EOD_FEED_LABEL_RU,
    execution_enabled_for_symbol as marketstack_execution_enabled,
    instrument_metadata_for_symbol,
    is_data_only_symbol as is_marketstack_data_only,
    is_marketstack_catalog_symbol,
    is_marketstack_eligible,
)


class DataOnlyInstrumentError(ValueError):
    """Raised when a user attempts to trade a data-only instrument."""

    def __init__(self, symbol: str, feed_label: str | None = None) -> None:
        self.symbol = symbol.upper()
        label = feed_label or EOD_FEED_LABEL_RU
        super().__init__(f"{self.symbol}: только данные — торговля недоступна ({label})")


def is_data_only_symbol(symbol: str) -> bool:
    """Union of Marketstack international names, classic forex, and OTC commodities."""
    if is_forex_pair(symbol) or is_commodity_pair(symbol):
        return True
    return is_marketstack_data_only(symbol)


def assert_execution_allowed(symbol: str) -> None:
    """Reject order placement for data-only / non-executable instruments."""
    if not is_data_only_symbol(symbol):
        return
    flags = execution_flags(symbol)
    raise DataOnlyInstrumentError(
        symbol,
        feed_label=str(flags.get("feed_label_ru") or EOD_FEED_LABEL_RU),
    )


def execution_flags(symbol: str) -> dict[str, object]:
    """Metadata flags for API responses (watchlist, symbol-rules, instruments)."""
    if is_forex_pair(symbol):
        meta = forex_metadata_for_symbol(symbol)
        return {
            "data_only": True,
            "execution_enabled": False,
            "feed": "forex",
            "feed_label_ru": FOREX_FEED_LABEL_RU,
            **{k: v for k, v in meta.items() if k not in {"data_only", "execution_enabled", "feed"}},
        }
    if is_commodity_pair(symbol):
        meta = commodity_metadata_for_symbol(symbol)
        return {
            "data_only": True,
            "execution_enabled": False,
            "feed": "commodities",
            "feed_label_ru": COMMODITY_FEED_LABEL_RU,
            **{k: v for k, v in meta.items() if k not in {"data_only", "execution_enabled", "feed"}},
        }
    data_only = is_marketstack_data_only(symbol)
    execution_enabled = marketstack_execution_enabled(symbol)
    meta = instrument_metadata_for_symbol(symbol)
    feed = "eod" if data_only or is_marketstack_catalog_symbol(symbol) or is_marketstack_eligible(symbol) else None
    return {
        "data_only": data_only,
        "execution_enabled": execution_enabled,
        "feed": feed,
        "feed_label_ru": EOD_FEED_LABEL_RU if feed == "eod" else None,
        **{k: v for k, v in meta.items() if k not in {"data_only", "execution_enabled", "feed"}},
    }
