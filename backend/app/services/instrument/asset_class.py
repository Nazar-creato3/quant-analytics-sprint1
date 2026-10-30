"""Single source of truth for symbol → asset-class routing.

The four routing classes the Terminal / Watchlist / search must share:

* ``crypto_pair``     — BTC/USDT, BTC-USD, ETHUSDT
* ``us_equity_index`` — AAPL, SPY, SPX, IMOEX (already-working listed path)
* ``forex_pair``      — EUR/USD, USD/JPY (classic OTC; data-only)
* ``international``   — 005930, 7203.T, N225, 0700.HK

Do not add per-surface if-branches for a new market: extend this module.

Portfolio FX conversion (KRW/JPY/EUR → USD/RUB totals) is intentionally out of
scope here — this round is display + data routing only.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.domain.enums import AssetCategory


class RoutingClass(str, Enum):
    CRYPTO_PAIR = "crypto_pair"
    US_EQUITY_INDEX = "us_equity_index"
    FOREX_PAIR = "forex_pair"
    INTERNATIONAL = "international"
    OTHER = "other"


# UI / Yahoo symbols that ride the existing US/MOEX listed path.
_US_INDEX_UI = frozenset(
    {"SPX", "IXIC", "NDX", "DJI", "RUT", "VIX", "DXY", "US10Y", "GOLD", "OIL", "BTC"}
)
_US_INDEX_API = frozenset(
    {"^GSPC", "^IXIC", "^NDX", "^DJI", "^RUT", "^VIX", "^TNX", "DX-Y.NYB", "GC=F", "CL=F"}
)
_INTL_INDEX_UI = frozenset({"N225", "HSI", "SSEC", "KS11", "FTSE", "DAX", "FCHI", "CAC"})
_INTL_INDEX_API = frozenset({"^N225", "^HSI", "^KS11", "^FTSE", "^GDAXI", "^FCHI", "000001.SS"})
_MOEX_INDEX_UI = frozenset({"IMOEX", "RTSI"})

_CRYPTO_QUOTES = frozenset({"USDT", "USDC", "BUSD", "USD"})
_KNOWN_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK"}
)

# Exchange suffix → ISO 4217. Registry metadata, not a guess from the price number.
_SUFFIX_CURRENCY: dict[str, str] = {
    ".T": "JPY",
    ".HK": "HKD",
    ".KS": "KRW",
    ".KQ": "KRW",
    ".TW": "TWD",
    ".SS": "CNY",
    ".SZ": "CNY",
    ".XETRA": "EUR",
    ".DE": "EUR",
    ".F": "EUR",
    ".PA": "EUR",
    ".AS": "EUR",
    ".L": "GBP",
    ".SW": "CHF",
    ".ME": "RUB",
}

_INDEX_CURRENCY: dict[str, str] = {
    "N225": "JPY",
    "^N225": "JPY",
    "HSI": "HKD",
    "^HSI": "HKD",
    "KS11": "KRW",
    "^KS11": "KRW",
    "SSEC": "CNY",
    "000001.SS": "CNY",
    "FTSE": "GBP",
    "^FTSE": "GBP",
    "DAX": "EUR",
    "^GDAXI": "EUR",
    "FCHI": "EUR",
    "CAC": "EUR",
    "^FCHI": "EUR",
    "IMOEX": "RUB",
    "RTSI": "USD",
    "SPX": "USD",
    "IXIC": "USD",
    "NDX": "USD",
    "DJI": "USD",
    "RUT": "USD",
    "VIX": "USD",
    "^GSPC": "USD",
    "^IXIC": "USD",
    "^NDX": "USD",
    "^DJI": "USD",
    "^RUT": "USD",
    "^VIX": "USD",
}


@dataclass(frozen=True, slots=True)
class AssetClassInfo:
    """Resolved routing for chart, watchlist, and search."""

    routing_class: RoutingClass
    canonical_symbol: str
    category: AssetCategory
    market: str
    currency: str
    preferred_provider: Optional[str]
    show_volume: bool
    chart_api_symbol: str

    @property
    def is_forex(self) -> bool:
        return self.routing_class == RoutingClass.FOREX_PAIR

    @property
    def is_crypto(self) -> bool:
        return self.routing_class == RoutingClass.CRYPTO_PAIR

    @property
    def is_international(self) -> bool:
        return self.routing_class == RoutingClass.INTERNATIONAL


def _raw(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _suffix_currency(sym: str) -> Optional[str]:
    for sfx, code in _SUFFIX_CURRENCY.items():
        if sym.endswith(sfx):
            return code
    return None


def classify_symbol(symbol: str, *, exchange: str | None = None) -> AssetClassInfo:
    """Classify a ticker. Used by chart routing, watchlist, and search."""
    from app.services.market_data.binance_spot import normalize_crypto_ticker
    from app.services.market_data.forex_catalog import canonical_forex_symbol, is_forex_pair
    from app.services.market_data.marketstack_catalog import (
        canonicalize_international_symbol,
        is_marketstack_eligible,
        lookup_marketstack_instrument,
    )
    from app.services.market_data.moex_currency import is_moex_currency_ticker, normalize_moex_currency_symbol
    from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

    sym = _raw(symbol)
    exch = (exchange or "").strip().lower()

    if not sym:
        return AssetClassInfo(
            routing_class=RoutingClass.OTHER,
            canonical_symbol=sym,
            category=AssetCategory.OTHER,
            market="other",
            currency="USD",
            preferred_provider=None,
            show_volume=True,
            chart_api_symbol=sym,
        )

    # 1) Classic OTC forex BEFORE slash-as-crypto (EUR/USD must not become EUR-USD).
    if is_forex_pair(sym) or exch in {"forex", "fx", "otc"}:
        canon = canonical_forex_symbol(sym) or sym.replace("-", "/")
        quote_ccy = canon.split("/")[-1] if "/" in canon else "USD"
        return AssetClassInfo(
            routing_class=RoutingClass.FOREX_PAIR,
            canonical_symbol=canon,
            category=AssetCategory.FX,
            market="forex",
            currency=quote_ccy,
            preferred_provider="forex",
            show_volume=False,
            chart_api_symbol=canon,
        )

    # 2) Crypto pairs (BTC/USDT, BTC-USD, ETHUSDT). Forex already excluded.
    crypto = normalize_crypto_ticker(sym)
    if crypto or exch in {"binance", "crypto"}:
        canon = crypto or sym
        return AssetClassInfo(
            routing_class=RoutingClass.CRYPTO_PAIR,
            canonical_symbol=canon,
            category=AssetCategory.CRYPTO,
            market="crypto",
            currency="USD",
            preferred_provider="binance_public",
            show_volume=True,
            chart_api_symbol=canon,
        )

    # 3) MOEX FX board lots stay on the listed/MOEX path (executable via T-Bank).
    if is_moex_currency_ticker(sym) or exch in {"moex_fx", "cets", "moex_currency"}:
        canon = normalize_moex_currency_symbol(sym)
        return AssetClassInfo(
            routing_class=RoutingClass.US_EQUITY_INDEX,
            canonical_symbol=canon,
            category=AssetCategory.FX,
            market="moex_fx",
            currency="RUB",
            preferred_provider="moex_iss",
            show_volume=False,
            chart_api_symbol=canon,
        )

    # 4) International indices (N225 / Hang Seng / KOSPI / Shanghai / FTSE / DAX / CAC).
    if (
        sym in _INTL_INDEX_UI
        or sym in _INTL_INDEX_API
        or (sym.startswith("^") and sym in _INTL_INDEX_API)
    ):
        api = {
            "N225": "^N225",
            "HSI": "^HSI",
            "KS11": "^KS11",
            "SSEC": "000001.SS",
            "FTSE": "^FTSE",
            "DAX": "^GDAXI",
            "FCHI": "^FCHI",
            "CAC": "^FCHI",
        }.get(sym, sym)
        ccy = _INDEX_CURRENCY.get(sym) or _INDEX_CURRENCY.get(api) or "USD"
        return AssetClassInfo(
            routing_class=RoutingClass.INTERNATIONAL,
            canonical_symbol=sym if sym in _INTL_INDEX_UI else api,
            category=AssetCategory.INDICES,
            market="index",
            currency=ccy,
            preferred_provider="yfinance",
            show_volume=False,
            chart_api_symbol=api,
        )

    # 5) International equities — suffix, catalog, or numeric KRX/HKEX tickers.
    intl = canonicalize_international_symbol(sym)
    if intl and is_marketstack_eligible(intl):
        inst = lookup_marketstack_instrument(intl)
        ccy = (inst.currency if inst else None) or _suffix_currency(intl) or "USD"
        market = (inst.region if inst else None) or (
            "asia" if any(intl.endswith(s) for s in (".T", ".HK", ".KS", ".KQ", ".TW", ".SS", ".SZ")) else "europe"
        )
        return AssetClassInfo(
            routing_class=RoutingClass.INTERNATIONAL,
            canonical_symbol=intl,
            category=AssetCategory.EQUITIES,
            market=market,
            currency=ccy,
            preferred_provider="marketstack",
            show_volume=True,
            chart_api_symbol=intl,
        )

    # 6) US / MOEX listed (existing working path, including IMOEX).
    if is_moex_ticker(sym) or exch in {"moex", "moex_spot"} or sym in _MOEX_INDEX_UI:
        canon = normalize_moex_symbol(sym) if is_moex_ticker(sym) else sym
        is_idx = sym in _MOEX_INDEX_UI
        return AssetClassInfo(
            routing_class=RoutingClass.US_EQUITY_INDEX,
            canonical_symbol=canon,
            category=AssetCategory.INDICES if is_idx else AssetCategory.EQUITIES,
            market="moex",
            currency="RUB",
            preferred_provider="moex_iss",
            show_volume=not is_idx,
            chart_api_symbol=canon,
        )

    if sym in _US_INDEX_UI or sym in _US_INDEX_API or sym.startswith("^"):
        api = {
            "SPX": "^GSPC",
            "IXIC": "^IXIC",
            "NDX": "^NDX",
            "DJI": "^DJI",
            "RUT": "^RUT",
            "VIX": "^VIX",
            "DXY": "DX-Y.NYB",
            "US10Y": "^TNX",
            "GOLD": "GC=F",
            "OIL": "CL=F",
            "BTC": "BTC-USD",
        }.get(sym, sym)
        ccy = _INDEX_CURRENCY.get(sym) or _INDEX_CURRENCY.get(api) or "USD"
        return AssetClassInfo(
            routing_class=RoutingClass.US_EQUITY_INDEX,
            canonical_symbol=sym if sym in _US_INDEX_UI else api,
            category=AssetCategory.INDICES,
            market="index",
            currency=ccy,
            preferred_provider=None,
            show_volume=False,
            chart_api_symbol=api,
        )

    # Default: US equity / ETF ticker (AAPL, SPY).
    return AssetClassInfo(
        routing_class=RoutingClass.US_EQUITY_INDEX,
        canonical_symbol=sym,
        category=AssetCategory.EQUITIES,
        market="us",
        currency="USD",
        preferred_provider=None,
        show_volume=True,
        chart_api_symbol=sym,
    )


def preferred_provider_for(symbol: str) -> Optional[str]:
    return classify_symbol(symbol).preferred_provider


def chart_api_symbol(symbol: str) -> str:
    """Symbol to send to quote/OHLCV endpoints — never rewrite forex as crypto."""
    return classify_symbol(symbol).chart_api_symbol


def display_currency(symbol: str, *, provider_currency: str | None = None) -> str:
    """Prefer the provider's currency field; fall back to exchange registry."""
    raw = (provider_currency or "").strip().upper()
    if raw and raw not in {"UNKNOWN", "NONE", "N/A"}:
        return raw
    return classify_symbol(symbol).currency
