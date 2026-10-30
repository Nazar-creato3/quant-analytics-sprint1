"""Universal instrument search — Marketstack universe + local executable venues.

Watchlist is NOT the search universe. Search hits Marketstack's ticker database
(and local crypto/MOEX/US/forex catalogs) in real time; Watchlist is only pins.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.core.logging import get_logger
from app.services.instrument.category import detect_ticker_category
from app.services.instrument.data_only import execution_flags, is_data_only_symbol
from app.services.market_data.binance_spot import is_crypto_ticker
from app.services.market_data.commodities_catalog import (
    COMMODITY_FEED_LABEL_RU,
    match_commodity_catalog,
)
from app.services.market_data.forex_catalog import (
    FOREX_CATALOG,
    FOREX_FEED_LABEL_RU,
    match_forex_catalog,
)
from app.services.market_data.http_providers import MarketStackClient, key_configured
from app.services.market_data.marketstack_catalog import (
    EOD_FEED_LABEL_RU,
    MARKETSTACK_CATALOG,
    infer_region_from_exchange,
    is_us_execution_exchange,
)
from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol
from app.services.market_data.moex_currency import (
    is_moex_currency_ticker,
    list_moex_currency_instruments,
    normalize_moex_currency_symbol,
)

logger = get_logger(__name__)

DATA_TIER_FULL = "full_trading"
DATA_TIER_DATA = "data_only"
DATA_TIER_LABEL_RU = {
    DATA_TIER_FULL: "К торговле",
    DATA_TIER_DATA: "Только котировки",
}

SearchCategory = Literal["equities", "etf", "crypto", "fx", "commodities", "all"]
SearchRegion = Literal["us", "europe", "asia", "moex", "fx", "all"]

_SEARCH_CACHE_TTL_S = 45.0
_SEARCH_CACHE: dict[str, tuple[float, list["UniverseHit"]]] = {}
_KNOWN_CRYPTO = (
    ("BTC-USD", "Bitcoin", "BINANCE"),
    ("ETH-USD", "Ethereum", "BINANCE"),
    ("SOL-USD", "Solana", "BINANCE"),
    ("BNB-USD", "BNB", "BINANCE"),
    ("XRP-USD", "XRP", "BINANCE"),
    ("ADA-USD", "Cardano", "BINANCE"),
    ("DOGE-USD", "Dogecoin", "BINANCE"),
)

# Local index search — N225/HSI/KOSPI must resolve without a third vendor.
_INTL_INDEX_HITS = (
    ("N225", "Nikkei 225", "TSE", "asia"),
    ("HSI", "Hang Seng", "HKEX", "asia"),
    ("KS11", "KOSPI", "KRX", "asia"),
    ("SSEC", "Shanghai Composite", "SSE", "asia"),
    ("FTSE", "FTSE 100", "LSE", "europe"),
    ("DAX", "DAX", "XETRA", "europe"),
    ("FCHI", "CAC 40", "EPA", "europe"),
)

# Named US names so "Apple" / "Microsoft" resolve without Marketstack.
_US_NAME_CATALOG: tuple[tuple[str, str], ...] = (
    ("AAPL", "Apple Inc"),
    ("MSFT", "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
    ("META", "Meta Platforms"),
    ("NVDA", "NVIDIA"),
    ("TSLA", "Tesla"),
    ("SPY", "SPDR S&P 500 ETF"),
    ("QQQ", "Invesco QQQ"),
    ("JPM", "JPMorgan Chase"),
    ("V", "Visa"),
    ("UNH", "UnitedHealth"),
    ("XOM", "Exxon Mobil"),
    ("JNJ", "Johnson & Johnson"),
    ("WMT", "Walmart"),
    ("MA", "Mastercard"),
    ("PG", "Procter & Gamble"),
    ("HD", "Home Depot"),
    ("CVX", "Chevron"),
    ("KO", "Coca-Cola"),
    ("PEP", "PepsiCo"),
    ("BAC", "Bank of America"),
    ("DIS", "Walt Disney"),
    ("NFLX", "Netflix"),
    ("AMD", "Advanced Micro Devices"),
    ("INTC", "Intel"),
    ("ORCL", "Oracle"),
    ("CRM", "Salesforce"),
    ("COST", "Costco"),
    ("AVGO", "Broadcom"),
)

_MOEX_NAME_CATALOG: tuple[tuple[str, str], ...] = (
    ("SBER", "Сбербанк Sberbank"),
    ("SBERP", "Сбербанк-п Sberbank pref"),
    ("GAZP", "Газпром Gazprom"),
    ("LKOH", "Лукойл Lukoil"),
    ("GMKN", "Норникель Nornickel"),
    ("YDEX", "Яндекс Yandex"),
    ("YNDX", "Яндекс Yandex (старый тикер)"),
    ("ROSN", "Роснефть Rosneft"),
    ("NVTK", "Новатэк Novatek"),
    ("MTSS", "МТС"),
    ("MGNT", "Магнит Magnit"),
    ("PLZL", "Полюс Polyus"),
    ("TCSG", "Т-Технологии TCS"),
    ("MOEX", "Московская биржа"),
    ("VTBR", "ВТБ"),
    ("ALRS", "АЛРОСА"),
    ("CHMF", "Северсталь Severstal"),
    ("NLMK", "НЛМК"),
    ("MAGN", "ММК"),
    ("TATN", "Татнефть"),
    ("SNGS", "Сургутнефтегаз"),
    ("IRAO", "Интер РАО"),
    ("AFLT", "Аэрофлот Aeroflot"),
    ("OZON", "Ozon"),
    ("VKCO", "VK"),
    ("EQMX", "БПИФ EQMX"),
    ("IMOEX", "Индекс МосБиржи"),
)

_MOEX_BOARD_CACHE: tuple[float, list[tuple[str, str]]] = (0.0, [])
_MOEX_BOARD_TTL_S = 3600.0


@dataclass(frozen=True, slots=True)
class UniverseHit:
    symbol: str
    name: str
    exchange: str
    region: str
    category: str
    category_label_ru: str
    data_tier: str
    data_tier_label_ru: str
    source: str
    pinned: bool = False
    feed_label_ru: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "region": self.region,
            "category": self.category,
            "category_label_ru": self.category_label_ru,
            "data_tier": self.data_tier,
            "data_tier_label_ru": self.data_tier_label_ru,
            "source": self.source,
            "pinned": self.pinned,
            "feed_label_ru": self.feed_label_ru,
        }


def _tier_for_symbol(symbol: str, *, exchange: str = "", mic: str = "", country: str = "") -> str:
    if is_data_only_symbol(symbol):
        return DATA_TIER_DATA
    if is_us_execution_exchange(exchange=exchange, mic=mic, country=country):
        return DATA_TIER_FULL
    if is_crypto_ticker(symbol) or is_moex_ticker(symbol):
        return DATA_TIER_FULL
    flags = execution_flags(symbol)
    if flags.get("data_only"):
        return DATA_TIER_DATA
    return DATA_TIER_FULL if flags.get("execution_enabled", True) else DATA_TIER_DATA


def _fold(text: str) -> str:
    return (
        (text or "")
        .upper()
        .replace("Ё", "Е")
        .replace("/", " ")
        .replace("-", " ")
        .replace(".", " ")
    )


def _score(query: str, symbol: str, name: str) -> int:
    """Lower is better. Match ticker *or* company name (incl. Cyrillic / multi-word)."""
    q = _fold(query).strip()
    if not q:
        return 8
    compact_q = q.replace(" ", "")
    sym = _fold(symbol)
    compact_sym = sym.replace(" ", "")
    name_u = _fold(name)
    if compact_sym == compact_q or sym == q:
        return 0
    if compact_sym.startswith(compact_q) or sym.startswith(q):
        return 1
    if compact_q in compact_sym:
        return 2
    if name_u.startswith(q) or q in name_u:
        return 3
    name_tokens = [t for t in name_u.split() if t]
    q_tokens = [t for t in q.split() if t]
    if q_tokens and all(any(tok.startswith(qt) or qt in tok for tok in name_tokens) for qt in q_tokens):
        return 4
    if any(tok.startswith(compact_q) or compact_q in tok for tok in name_tokens):
        return 5
    return 9


def _passes_filters(
    hit: UniverseHit,
    *,
    category: str,
    region: str,
) -> bool:
    cat = (category or "all").lower()
    reg = (region or "all").lower()
    if cat not in {"", "all"} and hit.category != cat:
        return False
    if reg not in {"", "all"} and hit.region != reg:
        return False
    return True


def _local_executable_hits(query: str) -> list[UniverseHit]:
    q = query.strip().upper()
    hits: list[UniverseHit] = []
    for sym, name, exch in _KNOWN_CRYPTO:
        if _score(q, sym, name) < 9:
            hits.append(
                UniverseHit(
                    symbol=sym,
                    name=name,
                    exchange=exch,
                    region="us",
                    category="crypto",
                    category_label_ru="Крипто",
                    data_tier=DATA_TIER_FULL,
                    data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                    source="ccxt",
                )
            )
    for ui, name, exch, region in _INTL_INDEX_HITS:
        if _score(q, ui, name) < 9:
            hits.append(
                UniverseHit(
                    symbol=ui,
                    name=name,
                    exchange=exch,
                    region=region,
                    category="indices",
                    category_label_ru="Индексы",
                    data_tier=DATA_TIER_DATA,
                    data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                    source="index",
                )
            )
    if is_moex_ticker(q) or (len(q) <= 5 and q.isalpha() and is_moex_ticker(q)):
        bare = normalize_moex_symbol(q)
        if is_moex_ticker(bare):
            info = detect_ticker_category(bare)
            hits.append(
                UniverseHit(
                    symbol=bare,
                    name=info.label_ru,
                    exchange="MOEX",
                    region="moex",
                    category="equities",
                    category_label_ru="Акции",
                    data_tier=DATA_TIER_FULL,
                    data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                    source="moex",
                )
            )
    if is_moex_currency_ticker(q):
        bare = normalize_moex_currency_symbol(q)
        hits.append(
            UniverseHit(
                symbol=bare,
                name=q if "/" in q else bare,
                exchange="MOEX",
                region="moex",
                category="fx",
                category_label_ru="Валюты",
                data_tier=DATA_TIER_FULL,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                source="moex",
            )
        )
    else:
        compact = q.replace("/", "").replace("-", "")
        if len(compact) < 6:
            compact = ""
        for row in list_moex_currency_instruments():
            pair = str(row.get("pair") or "").replace("/", "")
            if compact and (compact == pair or compact == str(row.get("symbol") or "")):
                hits.append(
                    UniverseHit(
                        symbol=row["symbol"],
                        name=row["name"],
                        exchange="MOEX",
                        region="moex",
                        category="fx",
                        category_label_ru="Валюты",
                        data_tier=DATA_TIER_FULL,
                        data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                        source="moex",
                    )
                )
                break
    # Bare 1–5 letter US ticker typed exactly — executable via Alpaca, not a Marketstack dump.
    if 1 <= len(q) <= 5 and q.isalpha() and not is_moex_ticker(q) and not is_crypto_ticker(q):
        info = detect_ticker_category(q)
        category = "etf" if info.category.value == "etf" else "equities"
        hits.append(
            UniverseHit(
                symbol=q,
                name=info.label_ru,
                exchange="US",
                region="us",
                category=category,
                category_label_ru="ETF" if category == "etf" else "Акции",
                data_tier=DATA_TIER_FULL,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                source="alpaca",
            )
        )
    return hits


def _forex_hits(query: str) -> list[UniverseHit]:
    out: list[UniverseHit] = []
    for pair in match_forex_catalog(query, limit=12):
        out.append(
            UniverseHit(
                symbol=pair.symbol,
                name=pair.name,
                exchange="OTC",
                region="fx",
                category="fx",
                category_label_ru="Валюты",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="forex",
                feed_label_ru=FOREX_FEED_LABEL_RU,
            )
        )
    return out


def _commodity_hits(query: str) -> list[UniverseHit]:
    out: list[UniverseHit] = []
    for pair in match_commodity_catalog(query, limit=12):
        out.append(
            UniverseHit(
                symbol=pair.symbol,
                name=pair.name,
                exchange="OTC",
                region="commodities",
                category="commodities",
                category_label_ru="Сырьё",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="commodities",
                feed_label_ru=COMMODITY_FEED_LABEL_RU,
            )
        )
    return out


def _catalog_fallback_hits(query: str) -> list[UniverseHit]:
    q = query.strip().upper()
    hits: list[UniverseHit] = []
    for inst in MARKETSTACK_CATALOG:
        if _score(q, inst.symbol, inst.name) >= 9:
            continue
        hits.append(
            UniverseHit(
                symbol=inst.symbol,
                name=inst.name,
                exchange=inst.exchange,
                region=inst.region,
                category="equities",
                category_label_ru="Акции",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="marketstack_catalog",
                feed_label_ru=EOD_FEED_LABEL_RU,
            )
        )
    return hits


def _named_catalog_hits(query: str) -> list[UniverseHit]:
    q = query.strip()
    hits: list[UniverseHit] = []
    for sym, name in _US_NAME_CATALOG:
        if _score(q, sym, name) < 9:
            hits.append(
                UniverseHit(
                    symbol=sym,
                    name=name,
                    exchange="US",
                    region="us",
                    category="etf" if sym in {"SPY", "QQQ"} else "equities",
                    category_label_ru="ETF" if sym in {"SPY", "QQQ"} else "Акции",
                    data_tier=DATA_TIER_FULL,
                    data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                    source="alpaca",
                )
            )
    for sym, name in _MOEX_NAME_CATALOG:
        if _score(q, sym, name) < 9:
            hits.append(
                UniverseHit(
                    symbol=sym,
                    name=name.split()[0] if name else sym,
                    exchange="MOEX",
                    region="moex",
                    category="equities",
                    category_label_ru="Акции",
                    data_tier=DATA_TIER_FULL,
                    data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                    source="moex",
                )
            )
    return hits


def _load_moex_board_rows() -> list[tuple[str, str]]:
    global _MOEX_BOARD_CACHE
    now = time.monotonic()
    cached_at, rows = _MOEX_BOARD_CACHE
    if rows and now - cached_at < _MOEX_BOARD_TTL_S:
        return rows
    try:
        from app.services.market_data.moex_iss_provider import _fetch_board_securities_sync

        raw = _fetch_board_securities_sync()
    except Exception as exc:
        logger.debug("MOEX TQBR list for search failed", error=str(exc))
        return rows
    parsed: list[tuple[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        secid = str(row.get("SECID") or "").strip().upper()
        if not secid:
            continue
        short = str(row.get("SHORTNAME") or secid).strip()
        full = str(row.get("SECNAME") or "").strip()
        label = f"{short} {full}".strip() if full and full.lower() != short.lower() else short
        parsed.append((secid, label))
    if parsed:
        _MOEX_BOARD_CACHE = (now, parsed)
        return parsed
    return rows


def _moex_board_hits(query: str, *, limit: int) -> list[UniverseHit]:
    q = (query or "").strip()
    hits: list[UniverseHit] = []
    for secid, short in _load_moex_board_rows():
        if q and _score(q, secid, short) >= 9:
            continue
        hits.append(
            UniverseHit(
                symbol=secid,
                name=short,
                exchange="MOEX",
                region="moex",
                category="equities",
                category_label_ru="Акции",
                data_tier=DATA_TIER_FULL,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                source="moex",
            )
        )
    if q:
        hits.sort(key=lambda h: (_score(q, h.symbol, h.name), h.symbol))
    return hits[: max(1, limit)]


def _hit_from_marketstack_row(row: dict[str, Any]) -> UniverseHit | None:
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    name = str(row.get("name") or symbol).strip()
    exch = row.get("stock_exchange") if isinstance(row.get("stock_exchange"), dict) else {}
    acronym = str(exch.get("acronym") or exch.get("mic") or "").upper()
    mic = str(exch.get("mic") or "").upper()
    country = str(exch.get("country_code") or exch.get("country") or "").upper()
    region = infer_region_from_exchange(acronym=acronym, mic=mic, country=country, symbol=symbol)
    name_u = name.upper()
    if "ETF" in name_u or "UCITS" in name_u:
        category = "etf"
        category_ru = "ETF"
    else:
        category = "equities"
        category_ru = "Акции"
    if region == "moex":
        tier = DATA_TIER_FULL
        source = "moex"
        feed = None
    elif is_us_execution_exchange(exchange=acronym, mic=mic, country=country) and not is_data_only_symbol(
        symbol
    ):
        tier = DATA_TIER_FULL
        source = "alpaca"
        feed = None
    else:
        tier = DATA_TIER_DATA
        source = "marketstack"
        feed = EOD_FEED_LABEL_RU
    return UniverseHit(
        symbol=symbol,
        name=name,
        exchange=acronym or mic or "MKT",
        region=region,
        category=category,
        category_label_ru=category_ru,
        data_tier=tier,
        data_tier_label_ru=DATA_TIER_LABEL_RU[tier],
        source=source,
        feed_label_ru=feed,
    )


async def _marketstack_search(query: str, *, limit: int) -> list[UniverseHit]:
    if not key_configured("marketstack"):
        return _catalog_fallback_hits(query)
    cache_key = f"{query.strip().upper()}|{limit}"
    now = time.monotonic()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and now - cached[0] < _SEARCH_CACHE_TTL_S:
        return list(cached[1])
    try:
        client = MarketStackClient()
        rows = await client.search_tickers(query, limit=limit)
    except Exception as exc:
        logger.warning("Marketstack ticker search failed", error=str(exc), query=query[:40])
        return _catalog_fallback_hits(query)
    hits: list[UniverseHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        hit = _hit_from_marketstack_row(row)
        if hit:
            hits.append(hit)
    if not hits:
        hits = _catalog_fallback_hits(query)
    _SEARCH_CACHE[cache_key] = (now, hits)
    if len(_SEARCH_CACHE) > 256:
        oldest = min(_SEARCH_CACHE, key=lambda k: _SEARCH_CACHE[k][0])
        _SEARCH_CACHE.pop(oldest, None)
    return hits


def _merge_rank(
    query: str,
    groups: list[list[UniverseHit]],
    *,
    limit: int,
    category: str,
    region: str,
    pinned: set[str],
) -> list[UniverseHit]:
    scored: list[tuple[int, str, UniverseHit]] = []
    seen: set[str] = set()
    for group in groups:
        for hit in group:
            if hit.symbol in seen:
                continue
            if not _passes_filters(hit, category=category, region=region):
                continue
            seen.add(hit.symbol)
            flagged = UniverseHit(
                symbol=hit.symbol,
                name=hit.name,
                exchange=hit.exchange,
                region=hit.region,
                category=hit.category,
                category_label_ru=hit.category_label_ru,
                data_tier=hit.data_tier,
                data_tier_label_ru=hit.data_tier_label_ru,
                source=hit.source,
                pinned=hit.symbol.upper() in pinned or hit.symbol in pinned,
                feed_label_ru=hit.feed_label_ru,
            )
            scored.append((_score(query, hit.symbol, hit.name), hit.symbol, flagged))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def _browse_universe(
    *,
    limit: int,
    category: str,
    region: str,
    pinned: set[str],
) -> list[UniverseHit]:
    """Initial search list — not the user watchlist."""
    hits: list[UniverseHit] = []
    for sym, name in _US_NAME_CATALOG:
        hits.append(
            UniverseHit(
                symbol=sym,
                name=name,
                exchange="US",
                region="us",
                category="etf" if sym in {"SPY", "QQQ"} else "equities",
                category_label_ru="ETF" if sym in {"SPY", "QQQ"} else "Акции",
                data_tier=DATA_TIER_FULL,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                source="alpaca",
                pinned=sym.upper() in pinned,
            )
        )
    hits.extend(_moex_board_hits("", limit=400))
    for inst in MARKETSTACK_CATALOG:
        hits.append(
            UniverseHit(
                symbol=inst.symbol,
                name=inst.name,
                exchange=inst.exchange,
                region=inst.region,
                category="equities",
                category_label_ru="Акции",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="marketstack",
                pinned=inst.symbol.upper() in pinned,
                feed_label_ru=EOD_FEED_LABEL_RU,
            )
        )
    for pair in FOREX_CATALOG:
        hits.append(
            UniverseHit(
                symbol=pair.symbol,
                name=pair.name,
                exchange="OTC",
                region="fx",
                category="fx",
                category_label_ru="Валюты",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="forex",
                pinned=pair.symbol.upper() in pinned,
                feed_label_ru=FOREX_FEED_LABEL_RU,
            )
        )
    for sym, name, exch in _KNOWN_CRYPTO:
        hits.append(
            UniverseHit(
                symbol=sym,
                name=name,
                exchange=exch,
                region="us",
                category="crypto",
                category_label_ru="Крипто",
                data_tier=DATA_TIER_FULL,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_FULL],
                source="binance",
                pinned=sym.upper() in pinned,
            )
        )
    for sym, name, exch, reg in _INTL_INDEX_HITS:
        hits.append(
            UniverseHit(
                symbol=sym,
                name=name,
                exchange=exch,
                region=reg,
                category="etf",
                category_label_ru="Индекс",
                data_tier=DATA_TIER_DATA,
                data_tier_label_ru=DATA_TIER_LABEL_RU[DATA_TIER_DATA],
                source="index",
                pinned=sym.upper() in pinned,
            )
        )
    seen: set[str] = set()
    filtered: list[UniverseHit] = []
    for hit in hits:
        if hit.symbol in seen:
            continue
        if not _passes_filters(hit, category=category, region=region):
            continue
        seen.add(hit.symbol)
        filtered.append(hit)
    return filtered[:limit]


async def search_universe(
    query: str,
    *,
    limit: int = 10,
    category: str = "all",
    region: str = "all",
    pinned_symbols: Optional[list[str]] = None,
) -> list[UniverseHit]:
    """Search the full instrument universe. Never restricted to the watchlist."""
    q = (query or "").strip()
    cap = max(1, min(int(limit), 50))
    pinned = {s.strip().upper() for s in (pinned_symbols or []) if s and s.strip()}
    cat = (category or "all").lower()
    reg = (region or "all").lower()
    if len(q) < 1:
        return _browse_universe(limit=cap, category=cat, region=reg, pinned=pinned)
    local_task = asyncio.to_thread(_local_executable_hits, q)
    named_task = asyncio.to_thread(_named_catalog_hits, q)
    moex_task = asyncio.to_thread(_moex_board_hits, q, limit=max(cap, 40))
    forex_task = asyncio.to_thread(_forex_hits, q)
    commodity_task = asyncio.to_thread(_commodity_hits, q)
    ms_task = _marketstack_search(q, limit=max(cap, 25))
    local, named, moex, forex, commodities, marketstack = await asyncio.gather(
        local_task, named_task, moex_task, forex_task, commodity_task, ms_task
    )
    return _merge_rank(
        q,
        [named, moex, forex, commodities, local, marketstack],
        limit=cap,
        category=cat,
        region=reg,
        pinned=pinned,
    )
