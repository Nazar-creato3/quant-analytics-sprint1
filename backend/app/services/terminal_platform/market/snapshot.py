"""Aggregate Terminal Market snapshot orchestrator."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.terminal_platform.factory import get_terminal_router
from app.services.terminal_platform.market.coverage import build_data_coverage, build_tape_items
from app.services.terminal_platform.market.factors import build_quant_factors
from app.services.terminal_platform.market.hours import build_market_hours
from app.services.terminal_platform.market.portfolio_block import build_portfolio_summary
from app.services.terminal_platform.market.pulse import build_pulse
from app.services.terminal_platform.market.quotes import fetch_indices
from app.services.terminal_platform.market.risk_block import build_risk_summary
from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi
from app.services.terminal_platform.market.schemas import (
    CalendarTapeRow,
    NewsTapeRow,
    PerformanceRow,
    TerminalMarketSnapshot,
)
from app.services.terminal_platform.market.watchlist_enrich import build_enriched_watchlist

logger = get_logger(__name__)


def _build_performance(
    indices_by_sym: dict[str, Any],
    watch_rows: list[Any],
    pulse: Optional[Any] = None,
) -> list[PerformanceRow]:
    """
    UI-aligned performance rows.

    Policy: never show no_data when a live quote with change_pct exists for that symbol.
    Never invent 0%. Include short reason when truly unavailable.
    """
    rows: list[PerformanceRow] = []

    def pct_from_index(*syms: str) -> tuple[Optional[float], Optional[str], Optional[str]]:
        for sym in syms:
            row = indices_by_sym.get(sym)
            if row is None:
                continue
            if row.status == "ok" and row.change_pct is not None:
                return float(row.change_pct), "ok", None
            if row.status == "ok" and row.change is not None and row.price is not None:
                try:
                    px = float(row.price)
                    ch = float(row.change)
                    if px > 0:
                        return round(ch / px * 100.0, 4), "ok", None
                except (TypeError, ValueError):
                    pass
            if row.status == "ok" and row.price is not None and row.change_pct is None:
                return None, "no_data", "change_pct_unavailable"
        return None, "no_data", "index_missing"

    def add_pct(label: str, value: Optional[float], status: str, reason: Optional[str], period: str = "TODAY"):
        rows.append(
            PerformanceRow(
                label=label,
                period=period,
                value=value,
                unit="pct",
                status=status,  # type: ignore[arg-type]
                reason=reason if status != "ok" else None,
            )
        )

    ndx_v, ndx_st, ndx_r = pct_from_index("NDX", "IXIC")
    add_pct("NASDAQ Daily", ndx_v, ndx_st, ndx_r or "NASDAQ quote missing")

    dji_v, dji_st, dji_r = pct_from_index("DJI")
    add_pct("DOW Daily", dji_v, dji_st, dji_r or "DOW quote missing")

    spx_v, spx_st, spx_r = pct_from_index("SPX")
    add_pct("S&P 500 Daily", spx_v, spx_st, spx_r or "SPX quote missing")

    if spx_v is not None and dji_v is not None:
        add_pct("S&P vs DOW Spread", round(spx_v - dji_v, 4), "ok", None)
    else:
        add_pct("S&P vs DOW Spread", None, "no_data", "need SPX and DJI change_pct")

    if ndx_v is not None and spx_v is not None:
        add_pct("NASDAQ vs S&P Spread", round(ndx_v - spx_v, 4), "ok", None)
    else:
        add_pct("NASDAQ vs S&P Spread", None, "no_data", "need NASDAQ and SPX change_pct")

    vix = indices_by_sym.get("VIX")
    if vix and vix.status == "ok" and vix.price is not None:
        rows.append(
            PerformanceRow(label="VIX", period="LEVEL", value=float(vix.price), unit="level", status="ok")
        )
    else:
        rows.append(
            PerformanceRow(
                label="VIX",
                period="LEVEL",
                value=None,
                unit="level",
                status="no_data",
                reason="VIX quote missing",
            )
        )

    # GOLD — watch GLD, or pulse global GOLD / GC=F
    gold_pct: Optional[float] = None
    gld = next((w for w in watch_rows if (w.symbol or "").upper() in {"GLD", "GC=F", "GOLD"} and w.status == "ok"), None)
    if gld and gld.change_pct is not None:
        gold_pct = float(gld.change_pct)
    if gold_pct is None and pulse is not None:
        for g in getattr(pulse, "global_snapshot", None) or []:
            key = (getattr(g, "key", None) or getattr(g, "symbol", None) or "").upper()
            if key in {"GOLD", "XAU", "GC=F"} and getattr(g, "change_pct", None) is not None:
                gold_pct = float(g.change_pct)
                break
    if gold_pct is not None:
        add_pct("GOLD (XAU)", gold_pct, "ok", None)
    else:
        add_pct("GOLD (XAU)", None, "no_data", "gold quote missing")

    # BTC — watchlist or pulse
    btc_pct: Optional[float] = None
    btc = next(
        (
            w
            for w in watch_rows
            if "BTC" in (w.symbol or "").upper() and w.status == "ok" and w.change_pct is not None
        ),
        None,
    )
    if btc is not None:
        btc_pct = float(btc.change_pct)
    if btc_pct is None and pulse is not None:
        for g in getattr(pulse, "global_snapshot", None) or []:
            key = (getattr(g, "key", None) or getattr(g, "symbol", None) or "").upper()
            if key in {"BTC", "BTCUSDT", "BTC-USD"} and getattr(g, "change_pct", None) is not None:
                btc_pct = float(g.change_pct)
                break
    if btc_pct is not None:
        add_pct("BTC/USDT", btc_pct, "ok", None)
    else:
        add_pct("BTC/USDT", None, "no_data", "btc_quote_unavailable")

    imoex_v, imoex_st, imoex_r = pct_from_index("IMOEX")
    add_pct("IMOEX", imoex_v, imoex_st, imoex_r or "IMOEX quote missing")

    return rows


async def _fetch_chart_for_symbol(ui_symbol: str) -> Any:
    """Real OHLCV for any Terminal focus symbol — crypto, US equity, MOEX index."""
    from app.services.terminal_platform.market.schemas import ChartPoint, ChartSeries
    from app.services.terminal_platform.types import Timeframe

    sym = (ui_symbol or "").strip().upper()
    if not sym:
        sym = "BTC/USDT"

    # Route-specific symbol attempts (same order as frontend resolveChartApiSymbol).
    candidates: list[tuple[str, str | None]] = []
    if "/" in sym:
        base = sym.split("/")[0]
        candidates.extend(
            [
                (sym, "binance_public"),
                (f"{base}-USD", "binance_public"),
                (f"{base}USDT", "binance_public"),
            ]
        )
    elif sym in {"IMOEX", "RTSI"}:
        candidates.append((sym, "moex_iss"))
    elif sym in {"SPX", "DJI", "IXIC", "NDX", "VIX"}:
        alias = {"SPX": "^GSPC", "DJI": "^DJI", "IXIC": "^IXIC", "NDX": "^NDX", "VIX": "^VIX"}.get(sym, sym)
        candidates.append((alias, None))
    else:
        candidates.append((sym, None))

    end = datetime.now(timezone.utc)
    begin = end - timedelta(days=5)
    last_err: Optional[str] = None

    for api_sym, preferred in candidates:
        try:
            result = await get_terminal_router().get_ohlcv(
                api_sym,
                Timeframe.H1,
                begin,
                end,
                preferred_provider=preferred,
                chain_budget_s=4.0,
            )
            if not result.success or not result.data:
                last_err = result.error or result.error_code or "ohlcv_failed"
                continue
            bars = result.data if isinstance(result.data, list) else []
            points: list[ChartPoint] = []
            for b in bars:
                if isinstance(b, dict):
                    ts = b.get("timestamp")
                    close = b.get("close")
                else:
                    ts = getattr(b, "timestamp", None)
                    close = getattr(b, "close", None)
                try:
                    close_f = float(close)
                except (TypeError, ValueError):
                    continue
                if close_f <= 0:
                    continue
                if hasattr(ts, "timestamp"):
                    t_ms = int(ts.timestamp() * 1000)
                else:
                    continue
                points.append(ChartPoint(t=t_ms, v=close_f))
            points = points[-96:]
            if len(points) < 4:
                last_err = "insufficient_bars"
                continue
            return ChartSeries(
                symbol=ui_symbol,
                points=points,
                provider=result.provider,
                source="live",
            )
        except Exception as exc:
            last_err = str(exc)
            logger.debug("chart fetch failed", symbol=api_sym, ui=ui_symbol, error=str(exc))

    return ChartSeries(
        symbol=ui_symbol,
        points=[],
        source="empty",
        reason=last_err or "all_ohlcv_providers_failed",
    )


async def _fetch_btc_chart() -> Any:
    """Default snapshot chart — BTC/USDT."""
    return await _fetch_chart_for_symbol("BTC/USDT")

async def _fetch_news(limit: int = 15) -> list[NewsTapeRow]:
    try:
        return await fetch_terminal_news_multi(limit=limit)
    except Exception as exc:
        logger.warning("terminal news fetch failed", error=str(exc))
        return []


async def _fetch_calendar(limit: int = 25) -> list[CalendarTapeRow]:
    try:
        from app.services.terminal_platform.calendar import fetch_terminal_calendar

        today = datetime.now(timezone.utc).date()
        result = await fetch_terminal_calendar(
            from_date=today,
            to_date=today + timedelta(days=14),
            limit=limit,
        )
        if not result.success or not result.data:
            return []
        items = result.data if isinstance(result.data, list) else []
        out: list[CalendarTapeRow] = []
        for ev in items[:limit]:
            when = getattr(ev, "when", None) or (ev.get("when") if isinstance(ev, dict) else None)
            when_s = when.isoformat() if hasattr(when, "isoformat") else str(when or "")
            out.append(
                CalendarTapeRow(
                    id=str(getattr(ev, "id", None) or (ev.get("id") if isinstance(ev, dict) else when_s)),
                    title=str(getattr(ev, "title", None) or (ev.get("title") if isinstance(ev, dict) else "")),
                    when=when_s,
                    region=getattr(ev, "region", None) or (ev.get("region") if isinstance(ev, dict) else None),
                    importance=getattr(ev, "importance", None)
                    or (ev.get("importance") if isinstance(ev, dict) else None),
                    expected=getattr(ev, "expected", None) or (ev.get("expected") if isinstance(ev, dict) else None),
                    actual=getattr(ev, "actual", None) or (ev.get("actual") if isinstance(ev, dict) else None),
                    previous=getattr(ev, "previous", None) or (ev.get("previous") if isinstance(ev, dict) else None),
                    forecast=getattr(ev, "expected", None) or (ev.get("forecast") if isinstance(ev, dict) else None),
                )
            )
        return out
    except Exception as exc:
        logger.warning("terminal calendar fetch failed", error=str(exc))
        return []


async def build_terminal_snapshot(
    *,
    db: Optional[AsyncSession] = None,
    email: Optional[str] = None,
    include_periods: bool = True,
    deadline_s: float = 26.0,
) -> TerminalMarketSnapshot:
    """
    Single Market-view payload.

    Hard deadline (default 26s): soft-fail slow sections so OPEN/degraded foreign
    providers never block the Terminal page. Progressive: core (indices+watchlist)
    first, then news/calendar/chart/pulse in parallel under remaining budget.
    include_periods defaults True — week/month attached via batch when budget allows.
    """
    import time

    from app.utils.cache import cache_get, cache_set

    cache_key = f"terminal:snapshot:v1:{email or 'anon'}:{include_periods}"
    cached = await cache_get(cache_key)
    if isinstance(cached, dict) and cached:
        try:
            return TerminalMarketSnapshot.model_validate(cached)
        except Exception:
            pass

    started = time.monotonic()
    as_of = datetime.now(timezone.utc).isoformat()
    notes: list[str] = []

    def remaining() -> float:
        return max(0.1, deadline_s - (time.monotonic() - started))

    async def _soft(name: str, coro, default, *, min_budget: float = 0.3):
        budget = remaining()
        if budget < min_budget:
            notes.append(f"{name}:skipped_budget")
            return default
        try:
            return await asyncio.wait_for(coro, timeout=budget)
        except asyncio.TimeoutError:
            notes.append(f"{name}:timeout")
            logger.warning("terminal snapshot section timed out", section=name, budget_s=budget)
            return default
        except Exception as exc:
            notes.append(f"{name}:error")
            logger.warning("terminal snapshot section failed", section=name, error=str(exc))
            return default

    # Core panels first (indices + watchlist) — leave room for enrichment.
    core_budget = min(14.0, max(6.0, deadline_s * 0.55))
    indices_task = fetch_indices(include_periods=include_periods, deadline_s=core_budget)
    watch_task = build_enriched_watchlist(db, email, limit=16)
    portfolio_task = build_portfolio_summary(db, email)
    # Pure CPU — run inline so a saturated default executor cannot starve market hours.
    async def _hours():
        return build_market_hours()

    hours_task = _hours()

    indices, watchlist, portfolio, hours = await asyncio.gather(
        _soft("indices", indices_task, [], min_budget=0.5),
        _soft("watchlist", watch_task, [], min_budget=0.5),
        _soft("portfolio", portfolio_task, None, min_budget=0.3),
        _soft("hours", hours_task, [], min_budget=0.1),
    )
    if portfolio is None:
        from app.services.terminal_platform.market.schemas import PortfolioSummaryBlock

        portfolio = PortfolioSummaryBlock(
            has_positions=False,
            message="portfolio_unavailable",
            open_positions=0,
        )

    # Secondary panels in parallel under remaining budget (news/calendar were sequential
    # and got skipped_budget under the old 12s deadline).
    enrich_budget = remaining()
    news_t = _soft("news", _fetch_news(), [], min_budget=0.8)
    calendar_t = _soft("calendar", _fetch_calendar(), [], min_budget=0.8)
    chart_t = _soft("chart", _fetch_btc_chart(), None, min_budget=0.8)

    indices_by = {r.symbol: r for r in indices}
    seed_quotes = [
        {
            "symbol": w.symbol,
            "display": w.display,
            "status": w.status,
            "price": w.last,
            "change_pct": w.change_pct,
            "volume": w.volume,
        }
        for w in watchlist
    ]
    for r in indices:
        seed_quotes.append(
            {
                "symbol": r.symbol,
                "display": r.symbol,
                "status": r.status,
                "price": r.price,
                "change_pct": r.change_pct,
            }
        )

    index_pcts = {
        sym: (indices_by[sym].change_pct if sym in indices_by else None)
        for sym in ("SPX", "NDX", "BTC", "IMOEX", "VIX")
    }
    btc_w = next((w for w in watchlist if "BTC" in (w.symbol or "").upper()), None)
    if btc_w and btc_w.status == "ok":
        index_pcts["BTC"] = btc_w.change_pct

    pulse_t = _soft(
        "pulse",
        build_pulse(seed_quotes=seed_quotes, index_change_pcts=index_pcts),
        None,
        min_budget=0.8,
    )

    news, calendar, chart, pulse = await asyncio.gather(news_t, calendar_t, chart_t, pulse_t)
    from app.services.terminal_platform.market.feed_freshness import (
        build_freshness_meta,
        freshness_from_calendar_cache,
        freshness_from_news_cache,
        get_cached_calendar,
        get_cached_news,
    )

    news_cached = get_cached_news()
    news_refreshed = news_cached.last_refreshed_at if news_cached else datetime.now(timezone.utc)
    _, news_freshness = freshness_from_news_cache(allow_stale_serve=True)
    if news_freshness is None:
        news_freshness = build_freshness_meta(news, refreshed_at=news_refreshed, ts_attr="published_at")

    cal_cached = get_cached_calendar()
    cal_refreshed = cal_cached.last_refreshed_at if cal_cached else datetime.now(timezone.utc)
    _, calendar_freshness = freshness_from_calendar_cache(allow_stale_serve=True)
    if calendar_freshness is None:
        calendar_freshness = build_freshness_meta(
            calendar,
            refreshed_at=cal_refreshed,
            ts_attr="when",
            stale_after_sec=3600,
            expected_interval_sec=1800,
        )
    if chart is None:
        from app.services.terminal_platform.market.schemas import ChartSeries

        chart = ChartSeries(symbol="BTC/USDT", points=[], source="empty", reason="budget_or_providers")
    if pulse is None:
        from app.services.terminal_platform.market.schemas import MarketPulseBlock

        pulse = MarketPulseBlock()

    performance = _build_performance(indices_by, watchlist, pulse=pulse)
    risk = build_risk_summary(watchlist, indices=indices)

    # Align chart last print with live BTC quote when available (hourly bar can lag).
    if chart is not None and getattr(chart, "points", None) and btc_w and btc_w.status == "ok" and btc_w.last:
        from app.services.terminal_platform.market.schemas import ChartPoint

        last_pt = chart.points[-1]
        live = float(btc_w.last)
        if live > 0 and abs(live - last_pt.v) / live < 0.08:
            chart.points[-1] = ChartPoint(t=last_pt.t, v=live)
        elif live > 0:
            chart.points.append(ChartPoint(t=int(datetime.now(timezone.utc).timestamp() * 1000), v=live))

    factors = build_quant_factors(pulse=pulse, portfolio=portfolio, index_change_pcts=index_pcts)
    tape = build_tape_items(
        indices=indices,
        watchlist=watchlist,
        pulse=pulse,
        hours=hours,
        news=news,
    )

    indices_ok = sum(1 for r in indices if r.status == "ok")
    watch_ok = sum(1 for w in watchlist if w.status == "ok")
    coverage = build_data_coverage(
        indices_ok=indices_ok,
        indices_total=len(indices) or 1,
        pulse=pulse,
        watch_ok=watch_ok,
        portfolio_wired=bool(email),
        news_count=len(news),
        calendar_count=len(calendar),
        fmp_keyed=bool((settings.FMP_API_KEY or "").strip()),
        av_keyed=bool((settings.ALPHA_VANTAGE_API_KEY or "").strip()),
    )

    if indices_ok == 0 and watch_ok == 0 and not news and not calendar:
        source = "empty"
    elif indices_ok < max(1, (len(indices) or 1) // 2) or notes:
        source = "partial"
    else:
        source = "live"

    # Compact alerts for UI (no LLM walls) — omit optional-key spam.
    alerts_compact: list[dict[str, str]] = []
    if notes:
        alerts_compact.append(
            {
                "severity": "info",
                "title": "Snapshot soft-fail",
                "body": f"Returned in budget; skipped/slow: {', '.join(notes[:6])}",
            }
        )
    if not (settings.FMP_API_KEY or "").strip():
        alerts_compact.append(
            {"severity": "warn", "title": "FMP key missing", "body": "Set FMP_API_KEY in container env"}
        )
    if chart is None or getattr(chart, "source", None) != "live":
        # Only warn when chart empty AND we had budget — avoid noise when BTC points exist.
        if not getattr(chart, "points", None):
            alerts_compact.append(
                {
                    "severity": "warn",
                    "title": "BTC chart empty",
                    "body": getattr(chart, "reason", None) or "ohlcv providers failed",
                }
            )

    elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
    _ = enrich_budget  # retained for clarity / future progressive meta

    result = TerminalMarketSnapshot(
        as_of=as_of,
        source=source,  # type: ignore[arg-type]
        indices=indices,
        performance=performance,
        pulse=pulse,
        watchlist_enriched=watchlist,
        portfolio_summary=portfolio,
        market_hours=hours,
        tape_items=tape,
        news=news,
        calendar=calendar,
        risk=risk,
        quant_factors=factors,
        data_coverage=coverage,
        chart=chart,
        news_freshness=news_freshness,
        calendar_freshness=calendar_freshness,
        meta={
            "include_periods": include_periods,
            "authenticated": bool(email),
            "index_ok": indices_ok,
            "watch_ok": watch_ok,
            "index_with_change_pct": sum(1 for r in indices if r.status == "ok" and r.change_pct is not None),
            "pulse_gainers": len(pulse.gainers or []),
            "pulse_losers": len(pulse.losers or []),
            "chart_source": getattr(chart, "source", None),
            "chart_provider": getattr(chart, "provider", None),
            "alerts_compact": alerts_compact,
            "deadline_s": deadline_s,
            "elapsed_ms": elapsed_ms,
            "soft_fail_notes": notes,
        },
    )
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=25)
    return result
