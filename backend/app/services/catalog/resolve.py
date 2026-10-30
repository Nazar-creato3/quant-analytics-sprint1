"""Deterministic instrument resolution. Does not guess when several assets match."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

_MOEX = frozenset(
    {
        "SBER", "GAZP", "LKOH", "GMKN", "YNDX", "ROSN", "NVTK", "MTSS", "MGNT", "PLZL",
        "TCSG", "MOEX", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "TATN", "SNGS", "SNGSP",
        "IRAO", "HYDR", "FEES", "RTKM", "AFKS", "PHOR", "PIKK", "FIVE", "OZON", "VKCO",
        "SBERP", "AFLT", "IMOEX", "RTSI",
        # Current tickers after 2024–2025 renames (YNDX→YDEX, FIVE→X5, HHRU→HEAD) and liquid names.
        "YDEX", "X5", "HEAD", "LQDT", "SBMM", "SVCB", "ASTR", "MTLR", "SMLT", "SFIN", "POSI", "WUSH", "MDMG", "LENT", "BSPB", "CBOM", "ENPG", "UGLD", "SELG", "RENI", "DELI", "MSRS", "CNRU", "IVAT", "SOFL", "DIAS", "DATA", "UPRO", "GECO", "OZPH", "KZOS", "TRMK", "RASP", "FLOT", "NMTP", "LSRG", "BELU", "AQUA", "MVID", "SGZH",
    }
)
_US_BLOCK = frozenset(
    {
        "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ",
        "AMD", "NFLX", "JPM", "BRK.B", "BRK.A",
    }
)
_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK"}
)
_FX_MOEX = {
    "USD/RUB": "USD000UTSTOM",
    "USDRUB": "USD000UTSTOM",
    "EUR/RUB": "EUR000UTSTOM",
    "EURRUB": "EUR000UTSTOM",
    "CNY/RUB": "CNY000UTSTOM",
    "CNYRUB": "CNY000UTSTOM",
}
_ALIASES = {
    "BITCOIN": "BTC-USD",
    "ETHEREUM": "ETH-USD",
    "APPLE": "AAPL",
    "BRK B": "BRK.B",
    "BRK/B": "BRK.B",
}
_TOKEN_TO_ASSET = {
    "AAPLX": "AAPL",
    "TSLAX": "TSLA",
}
_FUTURES = {
    "SI-9.24": ("Si", "future", "MOEX"),
    "BR-11.24": ("BR", "future", "MOEX"),
}


@dataclass(frozen=True)
class ResolveHit:
    query: str
    symbol: str
    asset_id: str
    instrument_kind: str
    venue: str
    listings: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    ambiguous: bool = False
    tradeable: bool = True
    trade_block_reason: str | None = None


def _norm(raw: str) -> str:
    collapsed = raw.strip().upper().replace("/", "-")
    collapsed = " ".join(collapsed.split())
    if collapsed in _ALIASES:
        return _ALIASES[collapsed]
    class_share = collapsed.replace(" ", ".")
    if class_share.count(".") == 1:
        left, right = class_share.split(".")
        if right == "ME":
            return left
        if len(right) == 1 and left.isalpha():
            return f"{left}.{right}"
    return collapsed.replace(" ", "")


def resolve(identifier: str) -> ResolveHit:
    """Resolve any known identifier. Ambiguous → candidates, no guess."""
    query = identifier.strip()
    if not query:
        raise ValueError("identifier must not be blank")
    key = _norm(query)
    fx = _FX_MOEX.get(query.strip().upper().replace("-", "/")) or _FX_MOEX.get(key.replace("-", ""))
    if fx:
        return ResolveHit(
            query=query,
            symbol=fx,
            asset_id=f"fx:{fx[:3].lower()}",
            instrument_kind="fx",
            venue="MOEX",
            listings=(fx,),
        )
    if key in _FUTURES:
        root, kind, venue = _FUTURES[key]
        return ResolveHit(query=query, symbol=key, asset_id=f"fut:{root}", instrument_kind=kind, venue=venue, listings=(key,))
    if key in _TOKEN_TO_ASSET:
        asset = _TOKEN_TO_ASSET[key]
        return ResolveHit(
            query=query,
            symbol=key,
            asset_id=f"eq:{asset}",
            instrument_kind="tokenized_equity",
            venue="TOKEN",
            listings=(key, asset),
        )
    if key.endswith("USDT") and key[:-4] in _CRYPTO_BASES:
        base = key[:-4]
        return ResolveHit(
            query=query,
            symbol=f"{base}-USD",
            asset_id=f"crypto:{base}",
            instrument_kind="crypto",
            venue="BINANCE",
            listings=(f"{base}USDT", f"{base}-USD"),
        )
    if key.endswith("-USD") and key.split("-")[0] in _CRYPTO_BASES:
        base = key.split("-")[0]
        return ResolveHit(
            query=query,
            symbol=key,
            asset_id=f"crypto:{base}",
            instrument_kind="crypto",
            venue="BINANCE",
            listings=(f"{base}USDT", key),
        )
    if key in _CRYPTO_BASES:
        return ResolveHit(
            query=query,
            symbol=f"{key}-USD",
            asset_id=f"crypto:{key}",
            instrument_kind="crypto",
            venue="BINANCE",
            listings=(f"{key}USDT", f"{key}-USD"),
        )
    if key.endswith(".ME") or (key in _MOEX and key not in _US_BLOCK):
        bare = key[:-3] if key.endswith(".ME") else key
        return ResolveHit(
            query=query,
            symbol=bare,
            asset_id=f"eq:{bare}",
            instrument_kind="equity",
            venue="MOEX",
            listings=(bare, f"{bare}.ME"),
        )
    if key in _US_BLOCK or (key.replace(".", "").isalpha() and 1 <= len(key) <= 6):
        # Ambiguous short letters that are both a US ticker idea and something else.
        if key == "T":
            return ResolveHit(
                query=query,
                symbol=key,
                asset_id="eq:T",
                instrument_kind="equity",
                venue="US",
                listings=(key,),
                candidates=("T", "TATN"),
                ambiguous=True,
            )
        venue = "US"
        kind = "equity"
        return ResolveHit(
            query=query,
            symbol=key,
            asset_id=f"eq:{key}",
            instrument_kind=kind,
            venue=venue,
            listings=(key,),
        )
    raise KeyError(f"unresolved identifier: {identifier!r}")


def list_known() -> list[ResolveHit]:
    """Canonical catalog names from Prompt 03 blocks (no vendor scrape)."""
    symbols = sorted(set(_MOEX) | set(_US_BLOCK) | {f"{b}-USD" for b in _CRYPTO_BASES})
    out: list[ResolveHit] = []
    for symbol in symbols:
        try:
            out.append(resolve(symbol))
        except KeyError:
            continue
    return out


def resolve_many(identifiers: Iterable[str]) -> list[ResolveHit]:
    return [resolve(item) for item in identifiers]
