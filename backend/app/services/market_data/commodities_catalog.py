"""OTC commodities via Twelve Data — data-only, never an execution venue.

Same free-tier path as classic forex: Twelve Data `/quote` + `/time_series`.
Display symbols stay slash-form (XAU/USD); energy maps to Twelve Data codes.
"""
from __future__ import annotations

from dataclasses import dataclass

COMMODITY_FEED_LABEL_RU = "котировки сырья (только данные, без исполнения)"
COMMODITY_PROVIDER_NAME = "twelvedata"

# (canonical display, name, group, Twelve Data API symbol)
_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("XAU/USD", "Gold / US Dollar", "metals", "XAU/USD"),
    ("XAG/USD", "Silver / US Dollar", "metals", "XAG/USD"),
    ("WTI/USD", "WTI Crude Oil", "energy", "WTIOIL"),
    ("BRENT/USD", "Brent Crude Oil", "energy", "BRENTOIL"),
)

_ALIASES: dict[str, str] = {
    "GOLD": "XAU/USD",
    "XAU": "XAU/USD",
    "XAUUSD": "XAU/USD",
    "SILVER": "XAG/USD",
    "XAG": "XAG/USD",
    "XAGUSD": "XAG/USD",
    "OIL": "WTI/USD",
    "CRUDE": "WTI/USD",
    "WTI": "WTI/USD",
    "WTIUSD": "WTI/USD",
    "CL": "WTI/USD",
    "USOIL": "WTI/USD",
    "WTIOIL": "WTI/USD",
    "BRENT": "BRENT/USD",
    "BRENTUSD": "BRENT/USD",
    "UKOIL": "BRENT/USD",
    "BRENTOIL": "BRENT/USD",
}


@dataclass(frozen=True, slots=True)
class CommodityPair:
    symbol: str
    name: str
    group: str
    api_symbol: str
    data_only: bool = True
    execution_enabled: bool = False


COMMODITY_CATALOG: tuple[CommodityPair, ...] = tuple(
    CommodityPair(sym, name, group, api) for sym, name, group, api in _ROWS
)

_BY_CANONICAL: dict[str, CommodityPair] = {p.symbol: p for p in COMMODITY_CATALOG}
_BY_COMPACT: dict[str, CommodityPair] = {p.symbol.replace("/", ""): p for p in COMMODITY_CATALOG}
_BY_API: dict[str, CommodityPair] = {p.api_symbol.upper(): p for p in COMMODITY_CATALOG}


def _compact(symbol: str) -> str:
    return (
        (symbol or "")
        .strip()
        .upper()
        .replace(" ", "")
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace("=", "")
    )


def canonical_commodity_symbol(symbol: str) -> str | None:
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    compact = _compact(raw)
    alias = _ALIASES.get(compact) or _ALIASES.get(raw)
    if alias:
        return alias
    slash = raw.replace("-", "/").replace("_", "/")
    known = _BY_CANONICAL.get(slash) or _BY_COMPACT.get(compact) or _BY_API.get(raw)
    return known.symbol if known else None


def canonical_commodity_api_symbol(symbol: str) -> str | None:
    pair = lookup_commodity_pair(symbol)
    return pair.api_symbol if pair else None


def is_commodity_pair(symbol: str) -> bool:
    return canonical_commodity_symbol(symbol) is not None


def lookup_commodity_pair(symbol: str) -> CommodityPair | None:
    canon = canonical_commodity_symbol(symbol)
    if not canon:
        return None
    return _BY_CANONICAL.get(canon)


def commodity_metadata_for_symbol(symbol: str) -> dict[str, object]:
    pair = lookup_commodity_pair(symbol)
    if not pair:
        return {}
    return {
        "data_only": True,
        "execution_enabled": False,
        "provider": COMMODITY_PROVIDER_NAME,
        "feed": "commodities",
        "feed_label_ru": COMMODITY_FEED_LABEL_RU,
        "exchange": "OTC",
        "region": "commodities",
        "name": pair.name,
        "category": "commodities",
    }


def match_commodity_catalog(query: str, *, limit: int = 10) -> list[CommodityPair]:
    q = (query or "").strip().upper()
    if len(q) < 2:
        return []
    compact_q = _compact(q)
    scored: list[tuple[int, CommodityPair]] = []
    for pair in COMMODITY_CATALOG:
        compact = pair.symbol.replace("/", "")
        name_u = pair.name.upper()
        api_u = pair.api_symbol.upper()
        if compact == compact_q or pair.symbol == q or api_u == q:
            scored.append((0, pair))
        elif compact.startswith(compact_q) or pair.symbol.startswith(q) or name_u.startswith(q):
            scored.append((1, pair))
        elif compact_q in compact or q in name_u or compact_q in api_u:
            scored.append((2, pair))
        elif compact_q in _ALIASES and _ALIASES[compact_q] == pair.symbol:
            scored.append((0, pair))
    scored.sort(key=lambda item: (item[0], item[1].symbol))
    seen: set[str] = set()
    out: list[CommodityPair] = []
    for _, pair in scored:
        if pair.symbol in seen:
            continue
        seen.add(pair.symbol)
        out.append(pair)
        if len(out) >= limit:
            break
    return out
