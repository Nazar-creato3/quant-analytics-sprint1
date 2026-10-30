"""Quote helpers — never invent 0.00 for missing prices."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.terminal_platform.factory import get_terminal_router
from app.services.terminal_platform.market.hours import session_status_for_exchange
from app.services.terminal_platform.market.schemas import IndexQuoteRow
from app.services.terminal_platform.types import Timeframe

logger = get_logger(__name__)

# UI symbol → (name, yfinance/provider symbol, venue for session, preferred provider hint)
INDEX_UNIVERSE: list[tuple[str, str, str, str, Optional[str]]] = [
    ("SPX", "S&P 500", "^GSPC", "NYSE", None),
    ("IXIC", "NASDAQ Composite", "^IXIC", "NASDAQ", None),
    ("NDX", "NASDAQ 100", "^NDX", "NASDAQ", None),
    ("DJI", "Dow Jones", "^DJI", "NYSE", None),
    ("RUT", "Russell 2000", "^RUT", "NYSE", None),
    ("FTSE", "FTSE 100", "^FTSE", "LSE", None),
    ("DAX", "DAX", "^GDAXI", "LSE", None),  # Frankfurt hours ≈ LSE-ish; session approx
    ("FCHI", "CAC 40", "^FCHI", "LSE", None),
    ("N225", "Nikkei 225", "^N225", "TSE", None),
    ("HSI", "Hang Seng", "^HSI", "SSE", None),  # HK ≈ Asia; session approx via SSE window
    ("SSEC", "Shanghai Composite", "000001.SS", "SSE", None),
    ("KS11", "KOSPI", "^KS11", "SSE", None),
    ("IMOEX", "MOEX Russia", "IMOEX", "MOEX", "moex_iss"),
    ("RTSI", "RTS Index", "RTSI", "MOEX", "moex_iss"),
    ("VIX", "CBOE VIX", "^VIX", "NYSE", None),
    ("DXY", "US Dollar Index", "DX-Y.NYB", "NYSE", None),
    ("US10Y", "US 10Y Yield", "^TNX", "NYSE", None),
    ("GOLD", "Gold", "GC=F", "NYSE", None),
    ("OIL", "WTI Crude", "CL=F", "NYSE", None),
    ("BTC", "Bitcoin", "BTC-USD", "NYSE", "binance_public"),
]


def resolve_change_pct(
    live_pct: Optional[float],
    batch_pct: Optional[float],
    *,
    prefer_batch: bool = True,
) -> Optional[float]:
    """Unify daily % change — yfinance batch (prev close) wins over intraday live quote."""
    if prefer_batch:
        return batch_pct if batch_pct is not None else live_pct
    return live_pct if live_pct is not None else batch_pct

GLOBAL_SNAPSHOT_UNIVERSE: list[tuple[str, str, str, str]] = [
    ("VIX", "VIX", "^VIX", "CBOE Volatility"),
    ("US10Y", "US10Y", "^TNX", "US 10Y Yield"),
    ("DXY", "DXY", "DX-Y.NYB", "US Dollar Index"),
    ("GOLD", "GOLD", "GC=F", "Gold futures"),
    ("OIL", "OIL", "CL=F", "WTI Crude"),
    ("BTC", "BTC", "BTC-USD", "Bitcoin"),
]

DEFAULT_WATCH_FALLBACK = ["BTC-USD", "ETH-USD", "AAPL", "MSFT", "NVDA", "SBER", "GLD", "SPY"]


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _quote_fields(data: Any) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    return {
        "symbol": getattr(data, "symbol", None),
        "price": getattr(data, "price", None),
        "change_pct": getattr(data, "change_pct", None),
        "timestamp": getattr(data, "timestamp", None),
        "provider": getattr(data, "provider", None),
        "volume": getattr(data, "volume", None),
        "bid": getattr(data, "bid", None),
        "ask": getattr(data, "ask", None),
        "currency": getattr(data, "currency", None),
        "exchange": getattr(data, "exchange", None),
    }


async def _daily_change_pct(symbol: str, last_price: Optional[float] = None) -> Optional[float]:
    """Derive session/day % change from last two daily closes when quote lacks change_pct."""
    try:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=10)
        result = await get_terminal_router().get_ohlcv(symbol, Timeframe.D1, begin, end)
        if not result.success or not result.data:
            return None
        bars = result.data
        if not isinstance(bars, list) or len(bars) < 2:
            return None
        closes: list[float] = []
        for b in bars:
            c = _finite(b.close if hasattr(b, "close") else (b.get("close") if isinstance(b, dict) else None))
            if c is not None:
                closes.append(c)
        if len(closes) < 2:
            return None
        prev = closes[-2]
        last = last_price if last_price is not None else closes[-1]
        if not prev:
            return None
        return round((last / prev - 1.0) * 100.0, 4)
    except Exception as exc:
        logger.debug("daily change backfill failed", symbol=symbol, error=str(exc))
        return None


async def fetch_quote_safe(
    symbol: str,
    *,
    preferred_provider: Optional[str] = None,
    backfill_change: bool = True,
    chain_budget_s: float = 5.0,
) -> dict[str, Any]:
    """
    Fetch a quote and normalize to a dict.
    On failure returns {status: no_data, reason, symbol} — never fabricates price=0.
    """
    try:
        result = await get_terminal_router().get_quote(
            symbol,
            preferred_provider=preferred_provider,
            chain_budget_s=chain_budget_s,
        )
    except Exception as exc:
        logger.warning("terminal quote exception", symbol=symbol, error=str(exc))
        return {"symbol": symbol, "status": "no_data", "reason": "нет данных"}

    if not result.success or result.data is None:
        return {
            "symbol": symbol,
            "status": "no_data",
            "reason": "нет данных",
            "provider": result.provider,
        }

    fields = _quote_fields(result.data)
    price = _finite(fields.get("price"))
    if price is None or price == 0.0:
        return {
            "symbol": symbol,
            "status": "no_data",
            "reason": "missing_price",
            "provider": result.provider,
        }

    change_pct = _finite(fields.get("change_pct"))
    if change_pct is None and backfill_change:
        # Cap OHLCV backfill so it cannot blow the snapshot budget.
        try:
            change_pct = await asyncio.wait_for(
                _daily_change_pct(symbol, last_price=price),
                timeout=2.5,
            )
        except asyncio.TimeoutError:
            change_pct = None

    change = None
    if change_pct is not None and price is not None:
        # change ≈ price * pct / 100 vs prior close
        change = round(price * change_pct / 100.0, 6)

    ts = fields.get("timestamp")
    as_of = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else datetime.now(timezone.utc).isoformat())

    from app.services.instrument.asset_class import display_currency

    return {
        "symbol": symbol,
        "status": "ok",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "volume": _finite(fields.get("volume")),
        "bid": _finite(fields.get("bid")),
        "ask": _finite(fields.get("ask")),
        "provider": result.provider or fields.get("provider"),
        "as_of": as_of,
        "currency": display_currency(symbol, provider_currency=fields.get("currency")),
        "exchange": fields.get("exchange"),
    }


async def _period_change_pct(symbol: str, days: int) -> Optional[float]:
    """Compute % change over ~days using daily OHLCV. Returns None on failure."""
    try:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=days + 5)
        result = await get_terminal_router().get_ohlcv(
            symbol,
            Timeframe.D1,
            begin,
            end,
        )
        if not result.success or not result.data:
            return None
        bars = result.data
        if not isinstance(bars, list) or len(bars) < 2:
            return None
        closes: list[float] = []
        for b in bars:
            c = _finite(b.close if hasattr(b, "close") else (b.get("close") if isinstance(b, dict) else None))
            if c is not None:
                closes.append(c)
        if len(closes) < 2:
            return None
        # Approximate lookback: take close from ~days ago if available
        lookback = min(days, len(closes) - 1)
        old = closes[-(lookback + 1)]
        last = closes[-1]
        if old == 0:
            return None
        return round((last / old - 1.0) * 100.0, 4)
    except Exception as exc:
        logger.debug("period change failed", symbol=symbol, days=days, error=str(exc))
        return None


async def enrich_index_row(
    ui: str,
    name: str,
    api: str,
    venue: str,
    preferred: Optional[str],
    *,
    include_periods: bool = True,
    chain_budget_s: float = 4.0,
) -> IndexQuoteRow:
    from app.services.terminal_platform.market.index_fallbacks import fetch_index_quote_with_fallbacks

    q = await fetch_index_quote_with_fallbacks(
        api,
        preferred_provider=preferred,
        chain_budget_s=chain_budget_s,
        try_native=True,
    )
    session = session_status_for_exchange(venue)
    # Session CLOSED must not blank quotes — last print / ETF proxy still shown.
    if q.get("status") != "ok" or (q.get("price") is None and q.get("change_pct") is None):
        return IndexQuoteRow(
            symbol=ui,
            name=name,
            api_symbol=api,
            session_status=session,
            provider=q.get("provider"),
            status="no_data",
            reason=str(q.get("reason") or "no_data"),
        )

    change_pct = q.get("change_pct")
    change = q.get("change")
    price = q.get("price")
    if change_pct is None and change is not None and price is not None:
        try:
            px = float(price)
            ch = float(change)
            if px > 0:
                change_pct = round(ch / px * 100.0, 4)
        except (TypeError, ValueError):
            pass

    week = month = None
    if include_periods:
        try:
            week, month = await asyncio.wait_for(
                asyncio.gather(
                    _period_change_pct(api, 5),
                    _period_change_pct(api, 21),
                ),
                timeout=3.0,
            )
        except asyncio.TimeoutError:
            week = month = None

    from app.services.instrument.asset_class import display_currency

    proxy = str(q.get("reason") or "")
    currency = "USD" if proxy.startswith("etf_proxy") or proxy.startswith("vol_etf_proxy") else display_currency(
        ui, provider_currency=q.get("currency")
    )

    return IndexQuoteRow(
        symbol=ui,
        name=name,
        api_symbol=api,
        price=price,
        change=change,
        change_pct=change_pct,
        week_change_pct=week,
        month_change_pct=month,
        session_status=session,
        provider=q.get("provider"),
        as_of=q.get("as_of"),
        currency=currency,
        status="ok",
        reason=q.get("reason"),
    )


async def fetch_indices(*, include_periods: bool = False, deadline_s: float = 12.0) -> list[IndexQuoteRow]:
    """Fetch all index rows in parallel. Failed quotes → status=no_data (not 0.00).

    Prefer keyed ETF/CBOE/MOEX/Binance fallbacks (Yahoo often blocked on RU VPS).
    Soft-fails when deadline_s is hit so Terminal never hangs on open circuits.
    """
    import time

    from app.services.terminal_platform.market.batch_enrich import enrich_change_map
    from app.services.terminal_platform.market.index_fallbacks import INDEX_EQUITY_ALIASES
    from app.utils.cache import cache_get, cache_set

    cache_key = f"terminal:indices:v1:{include_periods}"
    cached = await cache_get(cache_key)
    if isinstance(cached, list) and cached:
        try:
            return [IndexQuoteRow.model_validate(row) for row in cached]
        except Exception:
            pass

    started = time.monotonic()
    remaining = lambda: max(0.2, deadline_s - (time.monotonic() - started))

    api_syms = [api for _, _, api, _, _ in INDEX_UNIVERSE]
    # Batch only liquid aliases + natives — skip Yahoo ^symbols that hang the proxy.
    batch_syms = list(
        dict.fromkeys(
            [
                *(INDEX_EQUITY_ALIASES.get(api, api) for api in api_syms if api not in {"IMOEX", "RTSI"}),
                "BTC-USD",
                "IMOEX.ME",
            ]
        )
    )

    batch: dict[str, dict[str, Any]] = {}
    try:
        batch_raw = await asyncio.wait_for(
            enrich_change_map(batch_syms, timeout_s=min(4.0, remaining())),
            timeout=min(4.5, remaining()),
        )
        for api in api_syms:
            alias = INDEX_EQUITY_ALIASES.get(api, api)
            yf = "IMOEX.ME" if api == "IMOEX" else alias
            if yf in batch_raw:
                batch[api] = batch_raw[yf]
            elif alias in batch_raw:
                batch[api] = batch_raw[alias]
            elif api in batch_raw:
                batch[api] = batch_raw[api]
    except asyncio.TimeoutError:
        logger.warning("index batch enrich timed out", deadline_s=deadline_s)
    except Exception as exc:
        logger.warning("index batch enrich failed", error=str(exc))

    # Always run live fallbacks in parallel — session closed does not skip.
    per_budget = min(5.0, max(2.0, remaining() * 0.85))
    live_rows = await asyncio.gather(
        *[
            enrich_index_row(
                ui,
                name,
                api,
                venue,
                pref,
                include_periods=False,
                chain_budget_s=per_budget,
            )
            for ui, name, api, venue, pref in INDEX_UNIVERSE
        ]
    )
    live_by_api = {api: row for row, (_ui, _name, api, _venue, _pref) in zip(live_rows, INDEX_UNIVERSE)}

    out: list[IndexQuoteRow] = []
    for ui, name, api, venue, _pref in INDEX_UNIVERSE:
        b = batch.get(api) or {}
        live = live_by_api.get(api)
        if live is not None and live.status == "ok":
            chg = resolve_change_pct(live.change_pct, b.get("change_pct"))
            change = live.change
            if change is None and chg is not None and live.price is not None:
                change = round(float(live.price) * float(chg) / 100.0, 6)
            week = b.get("week_change_pct") if include_periods else None
            month = b.get("month_change_pct") if include_periods else None
            out.append(
                live.model_copy(
                    update={
                        "change": change,
                        "change_pct": chg,
                        "week_change_pct": week,
                        "month_change_pct": month,
                        "provider": live.provider or b.get("provider"),
                    }
                )
            )
            continue

        if b.get("price") is not None:
            chg = b.get("change_pct")
            change = b.get("change")
            if change is None and chg is not None and b.get("price"):
                change = round(float(b["price"]) * float(chg) / 100.0, 6)
            out.append(
                IndexQuoteRow(
                    symbol=ui,
                    name=name,
                    api_symbol=api,
                    price=b.get("price"),
                    change=change,
                    change_pct=chg,
                    week_change_pct=b.get("week_change_pct") if include_periods else None,
                    month_change_pct=b.get("month_change_pct") if include_periods else None,
                    session_status=session_status_for_exchange(venue),
                    provider=b.get("provider") or "batch",
                    as_of=b.get("as_of"),
                    status="ok",
                )
            )
            continue

        if live is not None:
            out.append(live)
        else:
            out.append(
                IndexQuoteRow(
                    symbol=ui,
                    name=name,
                    api_symbol=api,
                    session_status=session_status_for_exchange(venue),
                    status="no_data",
                    reason="deadline_or_providers",
                )
            )
    await cache_set(
        cache_key,
        [row.model_dump(mode="json") for row in out],
        ttl=30,
    )
    return out
