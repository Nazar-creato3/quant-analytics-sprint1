"""Classic OTC forex pairs — data-only, never an execution venue.

## Provider decision (expansion round, 2026-09)

| Need | Provider | Plan | Incremental cost |
|------|----------|------|------------------|
| Forex RT (EUR/USD, USD/JPY, …) | **Twelve Data** (already wired) | Business Basic includes RT forex; **client-facing display** requires Venture from **$149/mo** (not Individual; not internal-only Basic) | $0 if key exists; Venture if displaying TD to paying users |
| Asia/EU equities (TSE, HKEX, KRX, LSE, XETRA) | **MarketStack** (already paid) | Existing Basic/Professional EOD | $0 |
| Intl indices (N225, HSI, KS11, SSEC) | Existing INDEX_UNIVERSE + ETF proxies | Yahoo/Finnhub/Alpaca aliases | $0 |

No third provider. Individual Twelve Data is non-commercial and is not used.

Twelve Data `/quote` + `/time_series` already accept `EUR/USD`. Finnhub forex
needs a separate `/forex` family — not worth a second paid surface.

Classic OTC forex is NOT executable here (broker/jurisdiction, not code).
MOEX CETS (USD000UTSTOM) stays on the existing T-Bank path.
"""
from __future__ import annotations

from dataclasses import dataclass

FOREX_FEED_LABEL_RU = "котировки валютной пары (только данные, без исполнения)"
FOREX_PROVIDER_NAME = "twelvedata"
FOREX_PROVIDER_CHOICE = (
    "Twelve Data free-tier /quote + /time_series already cover slash pairs; "
    "Finnhub forex needs a separate /forex API and weaker free coverage."
)

_MAJORS: tuple[tuple[str, str], ...] = (
    ("EUR/USD", "Euro / US Dollar"),
    ("GBP/USD", "British Pound / US Dollar"),
    ("USD/JPY", "US Dollar / Japanese Yen"),
    ("USD/CHF", "US Dollar / Swiss Franc"),
    ("AUD/USD", "Australian Dollar / US Dollar"),
    ("USD/CAD", "US Dollar / Canadian Dollar"),
    ("NZD/USD", "New Zealand Dollar / US Dollar"),
    ("USD/CNY", "US Dollar / Chinese Yuan"),
)

_MINORS: tuple[tuple[str, str], ...] = (
    ("EUR/GBP", "Euro / British Pound"),
    ("EUR/JPY", "Euro / Japanese Yen"),
    ("EUR/AUD", "Euro / Australian Dollar"),
    ("EUR/CAD", "Euro / Canadian Dollar"),
    ("EUR/CHF", "Euro / Swiss Franc"),
    ("GBP/JPY", "British Pound / Japanese Yen"),
    ("GBP/AUD", "British Pound / Australian Dollar"),
    ("GBP/CAD", "British Pound / Canadian Dollar"),
    ("AUD/JPY", "Australian Dollar / Japanese Yen"),
    ("AUD/CAD", "Australian Dollar / Canadian Dollar"),
    ("AUD/NZD", "Australian Dollar / New Zealand Dollar"),
    ("CAD/JPY", "Canadian Dollar / Japanese Yen"),
    ("NZD/JPY", "New Zealand Dollar / Japanese Yen"),
    ("CHF/JPY", "Swiss Franc / Japanese Yen"),
)

_ISO4217 = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "AUD",
        "CAD",
        "NZD",
        "NOK",
        "SEK",
        "DKK",
        "SGD",
        "HKD",
        "CNY",
        "MXN",
        "ZAR",
        "TRY",
        "PLN",
        "HUF",
        "CZK",
        "INR",
        "KRW",
        "BRL",
        "RUB",
    }
)


@dataclass(frozen=True, slots=True)
class ForexPair:
    symbol: str  # canonical Twelve Data form, e.g. EUR/USD
    name: str
    group: str  # major | minor
    data_only: bool = True
    execution_enabled: bool = False


FOREX_CATALOG: tuple[ForexPair, ...] = tuple(
    [ForexPair(sym, name, "major") for sym, name in _MAJORS]
    + [ForexPair(sym, name, "minor") for sym, name in _MINORS]
)

_BY_CANONICAL: dict[str, ForexPair] = {p.symbol: p for p in FOREX_CATALOG}
_BY_COMPACT: dict[str, ForexPair] = {p.symbol.replace("/", ""): p for p in FOREX_CATALOG}


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


def canonical_forex_symbol(symbol: str) -> str | None:
    """Return EUR/USD form, or None if this is not a classic forex pair."""
    raw = (symbol or "").strip().upper().replace(" ", "")
    if not raw:
        return None
    compact = _compact(raw)
    known = _BY_CANONICAL.get(raw.replace("-", "/").replace("_", "/")) or _BY_COMPACT.get(compact)
    if known:
        return known.symbol
    if len(compact) == 6 and compact[:3] in _ISO4217 and compact[3:] in _ISO4217:
        if compact[:3] == compact[3:]:
            return None
        return f"{compact[:3]}/{compact[3:]}"
    if len(raw) == 7 and raw[3] in {"/", "-", "_"}:
        base, quote = raw[:3], raw[4:]
        if base in _ISO4217 and quote in _ISO4217 and base != quote:
            return f"{base}/{quote}"
    return None


def is_forex_pair(symbol: str) -> bool:
    """True for classic OTC pairs. False for MOEX FX (USD000UTSTOM, USD/RUB) and crypto."""
    from app.services.market_data.moex_currency import is_moex_currency_ticker

    raw = (symbol or "").strip().upper()
    if not raw or raw.endswith("-USD") or raw.endswith("USDT"):
        return False
    if "000" in raw:  # MOEX currency board lots
        return False
    if is_moex_currency_ticker(raw):
        return False
    return canonical_forex_symbol(raw) is not None


def lookup_forex_pair(symbol: str) -> ForexPair | None:
    canon = canonical_forex_symbol(symbol)
    if not canon:
        return None
    known = _BY_CANONICAL.get(canon)
    if known:
        return known
    return ForexPair(canon, canon.replace("/", " / "), "other")


def forex_metadata_for_symbol(symbol: str) -> dict[str, object]:
    pair = lookup_forex_pair(symbol)
    if not pair:
        return {}
    return {
        "data_only": True,
        "execution_enabled": False,
        "provider": FOREX_PROVIDER_NAME,
        "feed": "forex",
        "feed_label_ru": FOREX_FEED_LABEL_RU,
        "exchange": "OTC",
        "region": "fx",
        "name": pair.name,
        "category": "fx",
    }


def match_forex_catalog(query: str, *, limit: int = 10) -> list[ForexPair]:
    """Rank catalog pairs: exact compact, symbol prefix, then name contains."""
    q = (query or "").strip().upper()
    if len(q) < 2:
        return []
    compact_q = _compact(q)
    scored: list[tuple[int, ForexPair]] = []
    for pair in FOREX_CATALOG:
        compact = pair.symbol.replace("/", "")
        name_u = pair.name.upper()
        if compact == compact_q or pair.symbol == q:
            scored.append((0, pair))
        elif compact.startswith(compact_q) or pair.symbol.startswith(q):
            scored.append((1, pair))
        elif compact_q in compact or q in name_u:
            scored.append((2, pair))
    scored.sort(key=lambda item: (item[0], item[1].symbol))
    # de-dupe
    seen: set[str] = set()
    out: list[ForexPair] = []
    for _, pair in scored:
        if pair.symbol in seen:
            continue
        seen.add(pair.symbol)
        out.append(pair)
        if len(out) >= limit:
            break
    return out
