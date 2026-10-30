"""Running tape + data coverage helpers."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.services.terminal_platform.market.schemas import (
    DataCoverageRow,
    IndexQuoteRow,
    MarketHoursRow,
    MarketPulseBlock,
    NewsTapeRow,
    TapeItem,
    WatchlistEnrichedRow,
)

_TAPE_ALIASES: dict[str, str] = {
    "^VIX": "VIX",
    "VIX": "VIX",
    "BTC-USD": "BTC",
    "BTC/USDT": "BTC",
    "BTCUSDT": "BTC",
    "BTC": "BTC",
    "ETH-USD": "ETH",
    "ETH/USDT": "ETH",
    "ETHUSDT": "ETH",
    "ETH": "ETH",
    "GC=F": "GOLD",
    "GOLD": "GOLD",
    "GLD": "GOLD",
    "CL=F": "OIL",
    "OIL": "OIL",
    "USO": "OIL",
    "DX-Y.NYB": "DXY",
    "DXY": "DXY",
    "^TNX": "TNX",
    "TNX": "TNX",
}


def _canonical_tape_symbol(symbol: str | None) -> str:
    if not symbol:
        return ""
    raw = symbol.strip().upper()
    if raw in _TAPE_ALIASES:
        return _TAPE_ALIASES[raw]
    no_caret = raw.lstrip("^")
    if no_caret in _TAPE_ALIASES:
        return _TAPE_ALIASES[no_caret]
    no_suffix = re.sub(r"\.ME$", "", no_caret)
    if no_suffix in _TAPE_ALIASES:
        return _TAPE_ALIASES[no_suffix]
    crypto = re.match(r"^([A-Z]{2,10})[-/](USDT?|USD)$", raw)
    if crypto:
        return crypto.group(1)
    return no_suffix or raw


def build_tape_items(
    *,
    indices: list[IndexQuoteRow],
    watchlist: list[WatchlistEnrichedRow],
    pulse: MarketPulseBlock,
    hours: list[MarketHoursRow],
    news: list[NewsTapeRow],
    limit: int = 40,
) -> list[TapeItem]:
    now = datetime.now(timezone.utc).isoformat()
    items: list[TapeItem] = []
    seen_symbols: set[str] = set()

    def _add(item: TapeItem) -> None:
        sym = _canonical_tape_symbol(item.symbol)
        if sym:
            if sym in seen_symbols:
                return
            seen_symbols.add(sym)
        items.append(item)

    for row in indices:
        if row.status != "ok" or row.price is None:
            continue
        chg = f"{row.change_pct:+.2f}%" if row.change_pct is not None else "n/a"
        _add(
            TapeItem(
                kind="quote",
                symbol=row.symbol,
                text=f"{row.symbol} {row.price:.2f} ({chg})",
                change_pct=row.change_pct,
                price=row.price,
                ts=row.as_of or now,
            )
        )

    for w in watchlist:
        if w.status != "ok" or w.last is None:
            continue
        display = w.display or w.symbol
        chg = f"{w.change_pct:+.2f}%" if w.change_pct is not None else "n/a"
        _add(
            TapeItem(
                kind="quote",
                symbol=display,
                text=f"{display} {w.last:.2f} ({chg})",
                change_pct=w.change_pct,
                price=w.last,
                ts=w.as_of or now,
            )
        )

    for m in (pulse.gainers or [])[:3]:
        if m.change_pct is None:
            continue
        _add(
            TapeItem(
                kind="mover",
                symbol=m.symbol,
                text=f"↑ {m.symbol} {m.change_pct:+.2f}%",
                change_pct=m.change_pct,
                price=m.price,
                ts=now,
            )
        )
    for m in (pulse.losers or [])[:3]:
        if m.change_pct is None:
            continue
        _add(
            TapeItem(
                kind="mover",
                symbol=m.symbol,
                text=f"↓ {m.symbol} {m.change_pct:+.2f}%",
                change_pct=m.change_pct,
                price=m.price,
                ts=now,
            )
        )

    return items[:limit]


def build_data_coverage(
    *,
    indices_ok: int,
    indices_total: int,
    pulse: MarketPulseBlock,
    watch_ok: int,
    portfolio_wired: bool,
    news_count: int,
    calendar_count: int,
    fmp_keyed: bool,
    av_keyed: bool,
) -> list[DataCoverageRow]:
    return [
        DataCoverageRow(
            layer="global_indices",
            surfaced=indices_ok > 0,
            detail=f"{indices_ok}/{indices_total} indices with live quotes (yfinance/moex/fmp/av)",
            reason_if_not=None if indices_ok else "all index quotes failed",
        ),
        DataCoverageRow(
            layer="market_pulse",
            surfaced=pulse.fear_greed is not None or bool(pulse.global_snapshot),
            detail="Fear&Greed composite + MOEX breadth + FMP/local movers + global snapshot",
        ),
        DataCoverageRow(
            layer="us_exchange_breadth",
            surfaced=False,
            detail="NYSE/NASDAQ full advancers/decliners",
            reason_if_not="requires paid exchange breadth feed or large internal US universe; MOEX+watchlist estimate only",
        ),
        DataCoverageRow(
            layer="watchlist",
            surfaced=watch_ok > 0,
            detail=f"{watch_ok} enriched symbols (parity fields + ATR/trend when OHLCV available)",
        ),
        DataCoverageRow(
            layer="portfolio",
            surfaced=portfolio_wired,
            detail="Reuses portfolio.metrics / live_equity / exposure",
            reason_if_not=None if portfolio_wired else "auth required for user portfolio; honest empty otherwise",
        ),
        DataCoverageRow(
            layer="news",
            surfaced=news_count > 0,
            detail=(
                f"{news_count} headlines via Finnhub/Polygon/Tiingo (if keyed) "
                "+ RSS/NewsAPI + FMP/AV/yfinance fallback"
            ),
        ),
        DataCoverageRow(
            layer="economic_calendar",
            surfaced=calendar_count > 0,
            detail=f"{calendar_count} events (FMP → Finnhub econ+earnings → free FOMC/CBR)",
        ),
        DataCoverageRow(
            layer="fmp",
            surfaced=fmp_keyed,
            detail="FMP movers / calendar / quotes when FMP_API_KEY set",
            reason_if_not=None if fmp_keyed else "FMP_API_KEY not configured",
        ),
        DataCoverageRow(
            layer="alpha_vantage",
            surfaced=av_keyed,
            detail="Alpha Vantage news/quotes when ALPHA_VANTAGE_API_KEY set",
            reason_if_not=None if av_keyed else "ALPHA_VANTAGE_API_KEY not configured",
        ),
        DataCoverageRow(
            layer="holiday_calendar",
            surfaced=False,
            detail="Exchange holiday calendar",
            reason_if_not="deferred — market hours use weekday regular sessions only",
        ),
        DataCoverageRow(
            layer="crypto_stack_order_router",
            surfaced=False,
            detail="OrderRouter / crypto_stack cores",
            reason_if_not="intentionally not surfaced in Terminal Market read path (do not break trading cores)",
        ),
    ]
