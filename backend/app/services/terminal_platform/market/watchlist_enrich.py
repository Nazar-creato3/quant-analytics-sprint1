"""Enriched watchlist for Terminal — Dashboard parity + extras."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.terminal_platform.factory import get_terminal_router
from app.services.terminal_platform.market.hours import session_status_for_exchange
from app.services.instrument.data_only import execution_flags
from app.services.market_data.marketstack_catalog import (
    EOD_FEED_LABEL_RU,
    is_marketstack_catalog_symbol,
    lookup_marketstack_instrument,
)
from app.services.terminal_platform.market.quotes import (
    DEFAULT_WATCH_FALLBACK,
    _finite,
    fetch_quote_safe,
)
from app.services.terminal_platform.market.schemas import WatchlistEnrichedRow
from app.services.terminal_platform.types import DataType, Timeframe

logger = get_logger(__name__)


def _display_symbol(symbol: str) -> str:
    from app.services.instrument.asset_class import classify_symbol

    info = classify_symbol(symbol)
    if info.is_forex:
        return info.canonical_symbol
    s = info.canonical_symbol or symbol.upper()
    if info.is_crypto and s.endswith("-USD"):
        return s.replace("-USD", "/USDT")
    if s.endswith(".ME"):
        return s[:-3]
    return s


def _guess_venue(symbol: str) -> str:
    from app.services.instrument.asset_class import RoutingClass, classify_symbol

    info = classify_symbol(symbol)
    if info.market == "moex" or info.market == "moex_fx":
        return "MOEX"
    if info.routing_class in {RoutingClass.CRYPTO_PAIR, RoutingClass.FOREX_PAIR}:
        return "NASDAQ"  # 24h — session helper treats as always-open-ish
    if info.market == "asia":
        return "TSE"
    if info.market == "europe":
        return "LSE"
    return "NYSE"


def _api_symbol(symbol: str) -> str:
    from app.services.instrument.asset_class import chart_api_symbol

    return chart_api_symbol(symbol)


def _watchlist_feed_meta(api: str) -> dict[str, Any]:
    from app.services.instrument.asset_class import classify_symbol

    flags = execution_flags(api)
    info = classify_symbol(api)
    if info.is_forex:
        return {
            "live_delayed": "forex",
            "data_only": True,
            "execution_enabled": False,
            "feed_label_ru": str(flags.get("feed_label_ru") or ""),
            "reason": flags.get("feed_label_ru"),
        }
    if flags.get("data_only") or is_marketstack_catalog_symbol(api):
        return {
            "live_delayed": "eod",
            "data_only": True,
            "execution_enabled": False,
            "feed_label_ru": str(flags.get("feed_label_ru") or EOD_FEED_LABEL_RU),
            "reason": EOD_FEED_LABEL_RU,
        }
    return {
        "live_delayed": "delayed",
        "data_only": bool(flags.get("data_only")),
        "execution_enabled": bool(flags.get("execution_enabled", True)),
        "feed_label_ru": flags.get("feed_label_ru"),
    }


def _preferred_quote_provider(api: str) -> str | None:
    from app.services.instrument.asset_class import preferred_provider_for

    return preferred_provider_for(api)


async def _atr_and_trend(symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "atr": None,
        "vol_atr": None,
        "trend": None,
        "regime": None,
        "week_change_pct": None,
        "month_change_pct": None,
        "ytd_change_pct": None,
    }
    try:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=400)
        result = await get_terminal_router().get_ohlcv(symbol, Timeframe.D1, begin, end)
        if not result.success or not result.data:
            return out
        bars = result.data
        if not isinstance(bars, list) or len(bars) < 15:
            return out

        def _c(b: Any, key: str) -> Optional[float]:
            if hasattr(b, key):
                return _finite(getattr(b, key))
            if isinstance(b, dict):
                return _finite(b.get(key))
            return None

        closes = [c for c in (_c(b, "close") for b in bars) if c is not None]
        highs = [c for c in (_c(b, "high") for b in bars) if c is not None]
        lows = [c for c in (_c(b, "low") for b in bars) if c is not None]
        if len(closes) < 15:
            return out

        # ATR(14) simple
        trs: list[float] = []
        for i in range(1, min(len(closes), len(highs), len(lows))):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        if len(trs) >= 14:
            atr = sum(trs[-14:]) / 14.0
            out["atr"] = round(atr, 6)
            last = closes[-1]
            if last:
                out["vol_atr"] = round(atr / last * 100.0, 4)

        # Trend: close vs SMA20
        if len(closes) >= 20:
            sma = sum(closes[-20:]) / 20.0
            last = closes[-1]
            if last > sma * 1.01:
                out["trend"] = "up"
            elif last < sma * 0.99:
                out["trend"] = "down"
            else:
                out["trend"] = "sideways"

        # Regime via recent vol
        if len(closes) >= 21:
            rets = [(closes[i] / closes[i - 1] - 1) for i in range(-20, 0)]
            import statistics

            vol = statistics.pstdev(rets) * (252**0.5)
            if vol < 0.15:
                out["regime"] = "low_vol"
            elif vol < 0.30:
                out["regime"] = "normal"
            else:
                out["regime"] = "high_vol"

        def pct_from(n: int) -> Optional[float]:
            if len(closes) <= n:
                return None
            old = closes[-(n + 1)]
            if not old:
                return None
            return round((closes[-1] / old - 1.0) * 100.0, 4)

        out["week_change_pct"] = pct_from(5)
        out["month_change_pct"] = pct_from(21)
        # YTD: find first bar of current year if timestamps available
        year = end.year
        ytd_close = None
        for b in bars:
            ts = getattr(b, "timestamp", None) if not isinstance(b, dict) else b.get("timestamp")
            if ts is None:
                continue
            if hasattr(ts, "year"):
                y = ts.year
            else:
                try:
                    y = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).year
                except Exception:
                    continue
            c = _c(b, "close")
            if y == year and c is not None:
                if ytd_close is None:
                    ytd_close = c
        if ytd_close and closes:
            out["ytd_change_pct"] = round((closes[-1] / ytd_close - 1.0) * 100.0, 4)
    except Exception as exc:
        logger.debug("watchlist ohlcv enrich failed", symbol=symbol, error=str(exc))
    return out


def _quote_class_kwargs(api: str, q: dict[str, Any]) -> dict[str, Any]:
    from app.services.instrument.asset_class import RoutingClass, classify_symbol, display_currency

    info = classify_symbol(api)
    volume = None if not info.show_volume else q.get("volume")
    return {
        "currency": display_currency(api, provider_currency=q.get("currency")),
        "bid": _finite(q.get("bid")),
        "ask": _finite(q.get("ask")),
        "routing_class": info.routing_class.value,
        "show_volume": info.show_volume,
        "volume": volume,
        "session_open": info.routing_class in {RoutingClass.CRYPTO_PAIR, RoutingClass.FOREX_PAIR},
    }


async def enrich_one(symbol: str, *, category: Optional[str] = None) -> WatchlistEnrichedRow:
    api = _api_symbol(symbol)
    q = await fetch_quote_safe(api, preferred_provider=_preferred_quote_provider(api))
    venue = _guess_venue(api)
    cls_kw = _quote_class_kwargs(api, q)
    session = "open" if cls_kw.pop("session_open") else session_status_for_exchange(venue)
    ticker = _display_symbol(api) or api

    if q.get("status") != "ok":
        return WatchlistEnrichedRow(
            symbol=ticker,
            display=ticker,
            category=category,
            session=session,
            status="no_data",
            reason=str(q.get("reason") or "no_data"),
            provider=q.get("provider"),
            routing_class=cls_kw.get("routing_class"),
            currency=cls_kw.get("currency"),
            show_volume=cls_kw.get("show_volume"),
        )

    extras = await _atr_and_trend(api)
    chg = q.get("change_pct")
    risk = None
    if chg is not None:
        risk = round(min(100.0, abs(float(chg)) * 12.0 + (extras.get("vol_atr") or 0)), 2)

    inst = lookup_marketstack_instrument(api)
    sector = f"{inst.region}/{inst.exchange}" if inst else None
    try:
        fund = await get_terminal_router().fetch(
            DataType.FUNDAMENTALS,
            symbol=api,
            use_cache=True,
            cache_ttl=3600,
        )
        if fund.success and fund.data is not None:
            sector = getattr(fund.data, "sector", None) or (
                fund.data.get("sector") if isinstance(fund.data, dict) else None
            )
    except Exception:
        sector = None

    feed_meta = _watchlist_feed_meta(api)
    display = inst.name if inst else ticker
    return WatchlistEnrichedRow(
        symbol=ticker,
        display=display,
        category=category,
        last=q.get("price"),
        change=q.get("change"),
        change_pct=chg,
        day_change_pct=chg,
        week_change_pct=extras.get("week_change_pct"),
        month_change_pct=extras.get("month_change_pct"),
        ytd_change_pct=extras.get("ytd_change_pct"),
        atr=extras.get("atr"),
        vol_atr=extras.get("vol_atr"),
        trend=extras.get("trend"),
        regime=extras.get("regime"),
        risk_score=risk,
        sector=sector or (f"{inst.region}/{inst.exchange}" if inst else None),
        session=session,
        live_delayed=feed_meta["live_delayed"],
        data_only=feed_meta["data_only"],
        execution_enabled=feed_meta["execution_enabled"],
        feed_label_ru=feed_meta.get("feed_label_ru"),
        provider=q.get("provider"),
        as_of=q.get("as_of"),
        status="ok",
        reason=feed_meta.get("reason") if feed_meta.get("live_delayed") in {"eod", "forex"} else None,
        **{k: v for k, v in cls_kw.items() if k != "session_open"},
    )


async def resolve_watch_symbols(
    db: Optional[AsyncSession] = None,
    email: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    try:
        from app.services.settings.watchlist import get_effective_watchlist_enriched

        entries = await get_effective_watchlist_enriched(db, email)
        if entries:
            return entries
    except Exception as exc:
        logger.warning("effective watchlist unavailable", error=str(exc))

    fallback = list(settings.default_watchlist_list) or list(DEFAULT_WATCH_FALLBACK)
    return [{"symbol": s, "category": None} for s in fallback]


async def build_enriched_watchlist(
    db: Optional[AsyncSession] = None,
    email: Optional[str] = None,
    *,
    limit: int = 20,
) -> list[WatchlistEnrichedRow]:
    from app.services.terminal_platform.market.batch_enrich import enrich_change_map

    entries = await resolve_watch_symbols(db, email)
    entries = entries[:limit]
    symbols = [str(e["symbol"]) for e in entries]
    api_syms = [_api_symbol(s) for s in symbols]

    # One batch history pass for 1D/1W/1M/YTD + ATR/regime — avoids per-symbol OHLCV storms
    try:
        batch = await asyncio.wait_for(enrich_change_map(api_syms, timeout_s=5.0), timeout=5.5)
    except asyncio.TimeoutError:
        logger.warning("watchlist batch enrich timed out")
        batch = {}

    async def _one(entry: dict[str, Optional[str]]) -> WatchlistEnrichedRow:
        api = _api_symbol(str(entry["symbol"]))
        category = entry.get("category")
        b = batch.get(api) or {}
        venue = _guess_venue(api)
        cls_kw = _quote_class_kwargs(api, {})
        session = "open" if cls_kw.pop("session_open", False) else session_status_for_exchange(venue)
        ticker = _display_symbol(str(entry["symbol"]) or api) or api

        # Prefer live quote, fall back to batch price — short chain so OPEN circuits skip fast.
        preferred = _preferred_quote_provider(api)
        q = await fetch_quote_safe(
            api,
            preferred_provider=preferred,
            backfill_change=False,
            chain_budget_s=3.5,
        )
        if q.get("status") != "ok":
            if b.get("price") is None:
                return WatchlistEnrichedRow(
                    symbol=ticker,
                    display=ticker,
                    category=category,
                    session=session,
                    status="no_data",
                    reason=str(q.get("reason") or "no_data"),
                    provider=q.get("provider"),
                    routing_class=cls_kw.get("routing_class"),
                    currency=cls_kw.get("currency"),
                    show_volume=cls_kw.get("show_volume"),
                )
            q = {**b, "status": "ok"}
        cls_kw = _quote_class_kwargs(api, q)
        cls_kw.pop("session_open", None)

        chg = q.get("change_pct")
        if chg is None:
            chg = b.get("change_pct")
        change = q.get("change")
        if change is None and chg is not None and q.get("price") is not None:
            change = round(float(q["price"]) * float(chg) / 100.0, 6)

        week = b.get("week_change_pct")
        month = b.get("month_change_pct")
        ytd = b.get("ytd_change_pct")
        atr = b.get("atr")
        vol_atr = b.get("vol_atr")
        trend = b.get("trend")
        regime = b.get("regime")

        # Skip slow per-symbol OHLCV fallback when batch already covered — prevents hangs.
        if (week is None or atr is None) and not b:
            try:
                extras = await asyncio.wait_for(_atr_and_trend(api), timeout=2.0)
                week = week if week is not None else extras.get("week_change_pct")
                month = month if month is not None else extras.get("month_change_pct")
                ytd = ytd if ytd is not None else extras.get("ytd_change_pct")
                atr = atr if atr is not None else extras.get("atr")
                vol_atr = vol_atr if vol_atr is not None else extras.get("vol_atr")
                trend = trend or extras.get("trend")
                regime = regime or extras.get("regime")
            except asyncio.TimeoutError:
                pass

        risk = None
        if chg is not None:
            risk = round(min(100.0, abs(float(chg)) * 12.0 + (vol_atr or 0)), 2)
        elif vol_atr is not None:
            risk = round(min(100.0, float(vol_atr) * 2.0), 2)

        inst = lookup_marketstack_instrument(api)
        display = inst.name if inst else ticker
        feed_meta = _watchlist_feed_meta(api)
        return WatchlistEnrichedRow(
            symbol=ticker,
            display=display,
            category=category,
            last=q.get("price"),
            change=change,
            change_pct=chg,
            day_change_pct=chg,
            week_change_pct=week,
            month_change_pct=month,
            ytd_change_pct=ytd,
            atr=atr,
            vol_atr=vol_atr,
            trend=trend,
            regime=regime,
            risk_score=risk,
            sector=f"{inst.region}/{inst.exchange}" if inst else None,
            session=session,
            live_delayed=feed_meta["live_delayed"],
            data_only=feed_meta["data_only"],
            execution_enabled=feed_meta["execution_enabled"],
            feed_label_ru=feed_meta.get("feed_label_ru"),
            provider=q.get("provider") or b.get("provider"),
            as_of=q.get("as_of") or b.get("as_of"),
            status="ok",
            reason=feed_meta.get("reason") if feed_meta.get("live_delayed") in {"eod", "forex"} else None,
            **cls_kw,
        )

    return list(await asyncio.gather(*[_one(e) for e in entries]))
