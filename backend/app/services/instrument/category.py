"""Automatic ticker category detection from symbol, exchange, and metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.enums import AssetCategory, InstrumentSource
from app.services.instrument.asset_class import RoutingClass, classify_symbol
from app.services.market_data.moex_currency import (
    currency_display_name,
    is_moex_currency_ticker,
    normalize_moex_currency_symbol,
)
from app.services.market_data.moex_spot import is_moex_ticker
from app.services.macro.sector_seed import sector_for_symbol

_ETF_SYMBOLS = frozenset(
    {"SPY", "QQQ", "GLD", "IVV", "IWM", "DIA", "TLT", "HYG", "VTI", "VOO", "EFA", "EEM", "ARKK"}
)
_INDEX_SYMBOLS = frozenset({"SPY", "QQQ"})
_KNOWN_CRYPTO = frozenset({"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"})
_CRYPTO_ALIASES = {"ETHEREUM": "ETH-USD", "BITCOIN": "BTC-USD"}
_WATCHLIST_TECH_SECTORS = frozenset({"technology", "communication_services", "consumer_discretionary"})

_SECTOR_RU: dict[str, str] = {
    "technology": "технологии",
    "financials": "финансы",
    "energy": "энергетика",
    "consumer_discretionary": "потребительский сектор",
    "communication_services": "коммуникации",
    "indices": "индексы",
    "macro_hedge": "макро-хедж",
    "digital_assets": "цифровые активы",
    "materials": "материалы",
}

_MARKET_LABEL: dict[str, str] = {
    "us": "US equity",
    "moex": "MOEX",
    "crypto": "crypto",
    "etf": "ETF",
    "index": "index",
    "forex": "forex",
    "asia": "Asia equity",
    "europe": "Europe equity",
    "other": "other",
}


@dataclass(frozen=True, slots=True)
class TickerCategoryInfo:
    """Resolved category for display and registry enrichment."""

    category: AssetCategory
    market: str
    sector: str | None
    industry: str | None
    label: str
    label_ru: str
    source: InstrumentSource

    def to_metadata(self) -> dict[str, Any]:
        return {
            "detected_category": self.category.value,
            "market": self.market,
            "sector": self.sector,
            "industry": self.industry,
            "category_label": self.label,
            "category_label_ru": self.label_ru,
        }


def _normalize_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    raw = _CRYPTO_ALIASES.get(raw, raw)
    routed = classify_symbol(raw)
    return routed.canonical_symbol or raw


def _is_crypto_symbol(sym: str) -> bool:
    from app.services.market_data.forex_catalog import is_forex_pair

    if is_forex_pair(sym):
        return False
    if sym.endswith("USDT") or sym.endswith("-USD"):
        return True
    base = sym.split("-")[0].split("/")[0]
    return base in _KNOWN_CRYPTO


def detect_ticker_category(
    symbol: str,
    *,
    exchange: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TickerCategoryInfo:
    """Infer asset category from symbol/exchange/instrument metadata."""
    meta = dict(metadata or {})
    sym = _normalize_symbol(symbol)
    exchange_key = (exchange or meta.get("exchange") or "").strip().lower()

    seed = sector_for_symbol(sym)
    sector = seed[0] if seed else meta.get("sector")
    industry = seed[1] if seed else meta.get("industry")
    sector_ru = _SECTOR_RU.get(str(sector), str(sector).replace("_", " ") if sector else None)
    routed = classify_symbol(symbol, exchange=exchange_key or None)

    if routed.routing_class == RoutingClass.FOREX_PAIR:
        return TickerCategoryInfo(
            category=AssetCategory.FX,
            market="forex",
            sector="fx",
            industry="currency",
            label=f"FX · {routed.canonical_symbol}",
            label_ru=f"валюты · {routed.canonical_symbol}",
            source=InstrumentSource.FINAM,
        )

    if routed.routing_class == RoutingClass.INTERNATIONAL:
        loc = "Asia" if routed.market == "asia" else ("Europe" if routed.market == "europe" else "international")
        loc_ru = "Азия" if routed.market == "asia" else ("Европа" if routed.market == "europe" else "международные")
        is_idx = routed.category == AssetCategory.INDICES
        return TickerCategoryInfo(
            category=routed.category,
            market=routed.market,
            sector="indices" if is_idx else sector,
            industry=industry,
            label=f"{loc} {'index' if is_idx else 'equity'} · {routed.currency}",
            label_ru=f"{loc_ru} {'индекс' if is_idx else 'акции'} · {routed.currency}",
            source=InstrumentSource.FINAM,
        )

    if _is_crypto_symbol(sym) or exchange_key in {"binance", "crypto"} or routed.is_crypto:
        return TickerCategoryInfo(
            category=AssetCategory.CRYPTO,
            market="crypto",
            sector=sector or "digital_assets",
            industry=industry,
            label="crypto · digital assets",
            label_ru="крипто · цифровые активы",
            source=InstrumentSource.BINANCE,
        )

    if is_moex_currency_ticker(sym) or exchange_key in {"moex_fx", "cets", "moex_currency"}:
        label = currency_display_name(sym) or sym
        return TickerCategoryInfo(
            category=AssetCategory.FX,
            market="moex_fx",
            sector="fx",
            industry="currency",
            label=f"MOEX · {label}",
            label_ru=f"MOEX · {label}",
            source=InstrumentSource.TINKOFF,
        )

    if is_moex_ticker(sym) or exchange_key in {"moex", "moex_spot"}:
        sector_part = sector_ru or "акции"
        return TickerCategoryInfo(
            category=AssetCategory.EQUITIES,
            market="moex",
            sector=sector,
            industry=industry,
            label=f"MOEX · {sector_part}",
            label_ru=f"MOEX · {sector_part}",
            source=InstrumentSource.MOEX,
        )


    if sym in _ETF_SYMBOLS or meta.get("instrument_type") == "etf":
        return TickerCategoryInfo(
            category=AssetCategory.ETF,
            market="etf",
            sector=sector,
            industry=industry,
            label="ETF · US",
            label_ru="ETF · US",
            source=InstrumentSource.FINAM,
        )

    if sym in _INDEX_SYMBOLS or sector == "indices":
        return TickerCategoryInfo(
            category=AssetCategory.INDICES,
            market="index",
            sector=sector or "indices",
            industry=industry,
            label="US index",
            label_ru="US индекс",
            source=InstrumentSource.FINAM,
        )

    if seed is not None:
        sector_label = sector_ru or "equity"
        return TickerCategoryInfo(
            category=AssetCategory.EQUITIES,
            market="us",
            sector=sector,
            industry=industry,
            label=f"{sector_label} · US equity",
            label_ru=f"{sector_label} · US equity",
            source=InstrumentSource.FINAM,
        )

    if exchange_key in {"nasdaq", "nyse", "us", "finam", "tinkoff"}:
        return TickerCategoryInfo(
            category=AssetCategory.EQUITIES,
            market="us",
            sector=sector,
            industry=industry,
            label="US equity",
            label_ru="US equity",
            source=InstrumentSource.FINAM,
        )

    return TickerCategoryInfo(
        category=AssetCategory.OTHER,
        market="other",
        sector=None,
        industry=None,
        label=_MARKET_LABEL["other"],
        label_ru="прочее",
        source=InstrumentSource.FINAM,
    )


def watchlist_filter_key(info: TickerCategoryInfo) -> str:
    """Map detected category to dashboard watchlist tab id."""
    if info.category == AssetCategory.CRYPTO:
        return "crypto"
    if info.category == AssetCategory.FX or info.market in {"moex_fx", "forex"}:
        return "currencies"
    if info.category == AssetCategory.ETF:
        return "etf"
    if info.category == AssetCategory.EQUITIES and info.sector in _WATCHLIST_TECH_SECTORS:
        return "tech"
    return "other"


def enrich_watchlist_entry(symbol: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return watchlist display payload with auto-detected category."""
    info = detect_ticker_category(symbol, metadata=metadata)
    return {
        "symbol": _normalize_symbol(symbol),
        "category": info.category.value,
        "market": info.market,
        "sector": info.sector,
        "label": info.label,
        "label_ru": info.label_ru,
        "filter_key": watchlist_filter_key(info),
    }
