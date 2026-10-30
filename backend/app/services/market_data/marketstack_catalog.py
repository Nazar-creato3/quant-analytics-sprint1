"""Curated Asia/Europe instruments for Marketstack EOD (data-only, no execution)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# UI label for EOD-only instruments (Marketstack free tier).
EOD_FEED_LABEL_RU = "данные на конец предыдущего торгового дня"

# Exchange suffixes routed to Marketstack before US equity chain.
_MARKETSTACK_SUFFIXES = (
    ".T", ".HK", ".KS", ".KQ", ".TW", ".XETRA", ".DE", ".F", ".L", ".PA", ".AS", ".SW", ".SS", ".SZ",
)

_EXCHANGE_CURRENCY: dict[str, str] = {
    "TSE": "JPY",
    "HKEX": "HKD",
    "KRX": "KRW",
    "TWSE": "TWD",
    "XETRA": "EUR",
    "LSE": "GBP",
}

# Bare / numeric aliases → canonical Marketstack ticker (KRX 6-digit, HKEX 4-digit, …).
_SYMBOL_ALIASES: dict[str, str] = {
    "005930": "005930.KS",
    "005930.KS": "005930.KS",
    "000660": "000660.KS",
    "2330": "2330.TW",
    "2330.TW": "2330.TW",
    "0700": "0700.HK",
    "700": "0700.HK",
    "0700.HK": "0700.HK",
}


@dataclass(frozen=True, slots=True)
class MarketstackInstrument:
    """Registry entry — curated subset, not full Marketstack universe."""

    symbol: str  # canonical Marketstack ticker (e.g. 7203.T)
    name: str
    exchange: str  # TSE | HKEX | KRX | TWSE | XETRA | LSE
    region: str  # asia | europe
    country: str
    data_only: bool = True
    execution_enabled: bool = False
    currency: str = ""


# Nikkei subset, Hang Seng majors, DAX/FTSE blue chips.
MARKETSTACK_CATALOG: tuple[MarketstackInstrument, ...] = (
    # ── Japan (TSE) ──
    MarketstackInstrument("7203.T", "Toyota Motor", "TSE", "asia", "JP"),
    MarketstackInstrument("6758.T", "Sony Group", "TSE", "asia", "JP"),
    MarketstackInstrument("9984.T", "SoftBank Group", "TSE", "asia", "JP"),
    MarketstackInstrument("6861.T", "Keyence", "TSE", "asia", "JP"),
    MarketstackInstrument("8306.T", "MUFJ Financial", "TSE", "asia", "JP"),
    # ── Hong Kong (HKEX) ──
    MarketstackInstrument("0700.HK", "Tencent", "HKEX", "asia", "HK"),
    MarketstackInstrument("0941.HK", "China Mobile", "HKEX", "asia", "HK"),
    MarketstackInstrument("0005.HK", "HSBC Holdings", "HKEX", "asia", "HK"),
    MarketstackInstrument("1299.HK", "AIA Group", "HKEX", "asia", "HK"),
    MarketstackInstrument("2318.HK", "Ping An Insurance", "HKEX", "asia", "HK"),
    # ── Germany (XETRA / DAX) ──
    MarketstackInstrument("SAP.XETRA", "SAP SE", "XETRA", "europe", "DE"),
    MarketstackInstrument("SIE.XETRA", "Siemens", "XETRA", "europe", "DE"),
    MarketstackInstrument("ALV.XETRA", "Allianz", "XETRA", "europe", "DE"),
    MarketstackInstrument("BMW.XETRA", "BMW", "XETRA", "europe", "DE"),
    MarketstackInstrument("MBG.XETRA", "Mercedes-Benz", "XETRA", "europe", "DE"),
    # ── UK (LSE / FTSE) ──
    MarketstackInstrument("BARC.L", "Barclays", "LSE", "europe", "GB"),
    MarketstackInstrument("SHEL.L", "Shell", "LSE", "europe", "GB"),
    MarketstackInstrument("AZN.L", "AstraZeneca", "LSE", "europe", "GB"),
    MarketstackInstrument("ULVR.L", "Unilever", "LSE", "europe", "GB"),
    MarketstackInstrument("HSBA.L", "HSBC (LSE)", "LSE", "europe", "GB"),
    # ── Korea (KRX) ──
    MarketstackInstrument("005930.KS", "Samsung Electronics", "KRX", "asia", "KR", currency="KRW"),
    MarketstackInstrument("000660.KS", "SK Hynix", "KRX", "asia", "KR", currency="KRW"),
    # ── Taiwan (TWSE) ──
    MarketstackInstrument("2330.TW", "TSMC", "TWSE", "asia", "TW", currency="TWD"),
)

_BY_SYMBOL: dict[str, MarketstackInstrument] = {
    inst.symbol.upper(): inst for inst in MARKETSTACK_CATALOG
}
for alias, canonical in _SYMBOL_ALIASES.items():
    inst = _BY_SYMBOL.get(canonical.upper())
    if inst:
        _BY_SYMBOL[alias.upper()] = inst


def _digits_only(symbol: str) -> str:
    return "".join(ch for ch in (symbol or "") if ch.isdigit())


def canonicalize_international_symbol(symbol: str) -> Optional[str]:
    """Map 005930 / 0700 / Samsung-style aliases to Marketstack canonical tickers."""
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    if raw in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[raw]
    if raw in _BY_SYMBOL:
        return _BY_SYMBOL[raw].symbol
    if any(raw.endswith(sfx) for sfx in _MARKETSTACK_SUFFIXES):
        return raw
    digits = _digits_only(raw)
    if digits and digits == raw.replace(".", ""):
        if len(digits) == 6:
            return f"{digits}.KS"
        if len(digits) == 4 and digits.startswith("0"):
            return f"{digits.zfill(4)}.HK"
        padded = digits.zfill(4)
        for sfx in (".T", ".TW", ".HK"):
            candidate = f"{padded}{sfx}"
            if candidate in _BY_SYMBOL:
                return candidate
    return None

# Default watchlist seed symbols (Marketstack EOD, data-only).
MARKETSTACK_WATCHLIST_SEED: tuple[str, ...] = tuple(inst.symbol for inst in MARKETSTACK_CATALOG)


def lookup_marketstack_instrument(symbol: str) -> Optional[MarketstackInstrument]:
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    if raw in _BY_SYMBOL:
        return _BY_SYMBOL[raw]
    canon = canonicalize_international_symbol(raw)
    if canon and canon in _BY_SYMBOL:
        return _BY_SYMBOL[canon]
    return None


def is_marketstack_catalog_symbol(symbol: str) -> bool:
    return lookup_marketstack_instrument(symbol) is not None


def is_marketstack_eligible(symbol: str) -> bool:
    """True for curated catalog entries or known international exchange suffixes."""
    if is_marketstack_catalog_symbol(symbol):
        return True
    raw = canonicalize_international_symbol(symbol) or (symbol or "").strip().upper()
    return any(raw.endswith(sfx) for sfx in _MARKETSTACK_SUFFIXES)


def resolve_marketstack_symbol(symbol: str) -> Optional[str]:
    """Return canonical Marketstack API symbol."""
    inst = lookup_marketstack_instrument(symbol)
    if inst:
        return inst.symbol
    raw = canonicalize_international_symbol(symbol) or (symbol or "").strip().upper()
    if raw and is_marketstack_eligible(raw):
        return raw
    return None


def is_data_only_symbol(symbol: str) -> bool:
    inst = lookup_marketstack_instrument(symbol)
    if inst:
        return inst.data_only
    raw = (symbol or "").strip().upper()
    if raw and is_marketstack_eligible(raw):
        return True
    return False


def execution_enabled_for_symbol(symbol: str) -> bool:
    inst = lookup_marketstack_instrument(symbol)
    if inst:
        return inst.execution_enabled
    return True


def instrument_metadata_for_symbol(symbol: str) -> dict[str, object]:
    inst = lookup_marketstack_instrument(symbol)
    if not inst:
        return {}
    return {
        "data_only": inst.data_only,
        "execution_enabled": inst.execution_enabled,
        "provider": "marketstack",
        "feed": "eod",
        "feed_label_ru": EOD_FEED_LABEL_RU,
        "exchange": inst.exchange,
        "region": inst.region,
        "country": inst.country,
        "name": inst.name,
        "currency": inst.currency or _EXCHANGE_CURRENCY.get(inst.exchange, "USD"),
    }

def infer_region_from_exchange(
    *,
    acronym: str = "",
    mic: str = "",
    country: str = "",
    symbol: str = "",
) -> str:
    sym = (symbol or "").upper()
    c = (country or "").upper()
    ex = (acronym or mic or "").upper()
    if sym.endswith(".ME") or ex in ("MOEX", "MICEX") or c == "RU":
        return "moex"
    if c in ("US", "USA") or ex in ("NASDAQ", "NYSE", "AMEX", "XNAS", "XNYS", "ARCA"):
        return "us"
    if sym.endswith((".T", ".HK", ".SS", ".SZ", ".KS", ".KQ", ".TW")) or c in (
        "JP",
        "CN",
        "HK",
        "KR",
        "SG",
        "TW",
        "IN",
    ):
        return "asia"
    if sym.endswith((".XETRA", ".DE", ".F", ".L", ".PA", ".SW")) or c in (
        "DE",
        "GB",
        "FR",
        "CH",
        "NL",
        "IT",
        "ES",
    ):
        return "europe"
    if "/" in sym:
        return "fx"
    return "us"


def is_us_execution_exchange(*, exchange: str = "", mic: str = "", country: str = "") -> bool:
    c = (country or "").upper()
    ex = (exchange or mic or "").upper()
    return c in ("US", "USA") or ex in ("NASDAQ", "NYSE", "AMEX", "XNAS", "XNYS", "ARCA", "BATS")

