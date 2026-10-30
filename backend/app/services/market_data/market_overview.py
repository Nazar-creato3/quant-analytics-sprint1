"""Koyfin-style 'today's markets' board — Yahoo chart (fast), human regime copy."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

BOARD: dict[str, list[tuple[str, str]]] = {
    "us_equity": [
        ("SPY", "S&P 500"),
        ("QQQ", "Nasdaq 100"),
        ("DIA", "Dow Jones"),
        ("IWM", "Russell 2000"),
        ("VXX", "страх рынка"),
    ],
    "us_sectors": [
        ("XLK", "технологии"),
        ("XLF", "финансы"),
        ("XLE", "энергия"),
        ("XLV", "здравоохранение"),
        ("XLI", "промышленность"),
        ("XLY", "потребление"),
        ("XLP", "товары первой необходимости"),
        ("XLU", "коммунальные"),
        ("XLB", "материалы"),
        ("XLC", "связь"),
        ("XLRE", "недвижимость"),
    ],
    "fixed_income": [
        ("SHY", "короткие казначейские"),
        ("IEF", "средние казначейские"),
        ("TLT", "длинные казначейские"),
        ("LQD", "инвест. облигации"),
        ("HYG", "высокодоходные"),
        ("TIP", "с защитой от инфляции"),
    ],
    "fx": [
        ("UUP", "доллар"),
        ("FXE", "евро"),
        ("FXY", "иена"),
        ("FXB", "фунт"),
        ("FXC", "канадский доллар"),
        ("FXA", "австралийский доллар"),
    ],
    "global": [
        ("EWJ", "Япония"),
        ("EWG", "Германия"),
        ("EWU", "Великобритания"),
        ("FXI", "Китай"),
        ("EWZ", "Бразилия"),
        ("EEM", "развивающиеся"),
    ],
    "commodities": [
        ("GLD", "золото"),
        ("SLV", "серебро"),
        ("USO", "нефть"),
        ("UNG", "газ"),
        ("DBA", "сельхоз"),
        ("BTC-USD", "биткоин"),
    ],
}

COMPARE_SYMBOLS = ("SPY", "QQQ", "IWM")

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QuantAnalytics/1.0; +https://quantanalyticsclub.ru)",
    "Accept": "application/json",
}

_LAST_GOOD_OVERVIEW: dict[str, Any] | None = None
_OVERVIEW_CACHE_KEY = "market:overview:v8"
_OVERVIEW_LOCK_KEY = "market:overview:lock:v8"
_OVERVIEW_TTL = 300
_OVERVIEW_BUDGET_SEC = 25.0
_QUOTE_CONCURRENCY = 8


def _stale_overview(payload: dict[str, Any], *, rebuilding: bool = False) -> dict[str, Any]:
    stale = dict(payload)
    stale["stale"] = True
    if rebuilding:
        stale["rebuilding"] = True
    return _tag_overview(stale)


def _tag_overview(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.market_data.license import stamp_quote

    groups = payload.get("groups") or {}
    tagged = {
        key: [stamp_quote(dict(row)) for row in rows]
        for key, rows in groups.items()
    }
    out = dict(payload)
    out["groups"] = tagged
    return out


def _data_layer_status() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from app.services.market_data.equity_eod_store import store_status as eod_status

        st = eod_status()
        out["equity_eod"] = {
            "synced_at": st.get("synced_at"),
            "symbol_count": st.get("symbol_count"),
        }
    except Exception as exc:
        out["equity_eod"] = {"error": str(exc)[:80]}
    try:
        from app.services.market_data.stooq_bulk_store import store_status as stooq_status

        st = stooq_status()
        out["stooq"] = {
            "synced_at": st.get("synced_at"),
            "symbol_count": st.get("symbol_count"),
        }
    except Exception as exc:
        out["stooq"] = {"error": str(exc)[:80]}
    try:
        from app.services.market_data.fred_bulk_store import store_status as fred_status

        st = fred_status()
        out["fred"] = {"synced_at": st.get("synced_at"), "series_count": st.get("series_count")}
    except Exception as exc:
        out["fred"] = {"error": str(exc)[:80]}
    return out


def _board_from_local_only() -> dict[str, list[dict[str, Any]]] | None:
    """Instant board from EOD and/or Stooq bulk — skip Yahoo when local coverage is enough."""
    groups: dict[str, list[dict[str, Any]]] = {}
    priced = 0
    total = 0
    eod_quote = None
    stooq_quote = None
    try:
        from app.services.market_data.equity_eod_store import read_latest_quote as eod_quote
    except Exception:
        eod_quote = None
    try:
        from app.services.market_data.stooq_bulk_store import read_latest_quote as stooq_quote
    except Exception:
        stooq_quote = None
    if eod_quote is None and stooq_quote is None:
        return None

    for key, pairs in BOARD.items():
        rows: list[dict[str, Any]] = []
        for sym, name in pairs:
            total += 1
            local: dict[str, Any] = {}
            if eod_quote is not None:
                try:
                    local = eod_quote(sym) or {}
                except Exception:
                    local = {}
            if local.get("price") is None and stooq_quote is not None:
                try:
                    local = stooq_quote(sym) or {}
                except Exception:
                    local = {}
            if local.get("price") is not None:
                priced += 1
                src = str(local.get("source") or "")
                if src.startswith("stooq"):
                    rows.append(
                        {
                            "symbol": sym,
                            "name": name,
                            "price": local.get("price"),
                            "change_pct": local.get("change_pct"),
                            "volume": local.get("volume"),
                            "prev_close": None,
                            "day_high": None,
                            "day_low": None,
                            "source": "stooq_local",
                        }
                    )
                else:
                    rows.append(_enrich_from_eod_bars(sym, name, local))
            else:
                rows.append(_empty_row(sym, name))
        groups[key] = rows
    if priced < max(8, int(total * 0.55)):
        return None
    return groups


async def _bounded_gather(coros: list, *, limit: int = _QUOTE_CONCURRENCY):
    sem = asyncio.Semaphore(limit)

    async def _wrap(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_wrap(c) for c in coros], return_exceptions=True)


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def rebase_closes(closes: list[tuple[str, float]]) -> list[dict[str, Any]]:
    if not closes:
        return []
    base = closes[0][1]
    if not base:
        return []
    return [{"date": d, "pct": round((c / base - 1.0) * 100.0, 3)} for d, c in closes]


def regime_from_board(groups: dict[str, list[dict[str, Any]]]) -> str | None:
    """Human one-liner for traders. None when board has no usable quotes."""

    def chg(symbol: str) -> float | None:
        for rows in groups.values():
            for row in rows:
                if row.get("symbol") == symbol:
                    return _num(row.get("change_pct"))
        return None

    priced = 0
    for rows in groups.values():
        for row in rows:
            if _num(row.get("price")) is not None or _num(row.get("change_pct")) is not None:
                priced += 1
    if priced < 3:
        return None

    spy = chg("SPY")
    if spy is None:
        return "Котировки части рынков есть, но по S&P 500 пока нет ясного дня — смотрите сектора ниже."

    hyg = chg("HYG")
    tlt = chg("TLT")
    vxx = chg("VXX")
    if spy >= 0.35 and (hyg is None or hyg >= 0):
        return "Риск сегодня скорее включают: широкие акции растут, кредитный рынок не пугает."
    if spy <= -0.35 and (hyg is not None and hyg < 0):
        return "Риск сегодня скорее выключают: акции и высокодоходные облигации вместе слабеют."
    if tlt is not None and tlt >= 0.4 and spy <= 0:
        return "Деньги уходят в длинные облигации — фон защитный, акции без импульса."
    if vxx is not None and vxx >= 3.0 and spy < 0:
        return "Страх на рынке вырос (VXX вверх) при слабом S&P — осторожнее с размером позиции."
    if spy >= 0.15:
        return f"S&P 500 сегодня около +{spy:.2f}% — фон умеренно позитивный, без чистого risk-off."
    if spy <= -0.15:
        return f"S&P 500 сегодня около {spy:.2f}% — мягкий нажим на риск, смотрите лидеров и отстающих в секторах."
    return "Фон смешанный: нет чистого включения или выключения риска — важнее относительная сила секторов."


def _empty_row(symbol: str, name: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": name,
        "price": None,
        "change_pct": None,
        "volume": None,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "source": None,
    }


def _enrich_from_eod_bars(symbol: str, name: str, quote: dict[str, Any]) -> dict[str, Any]:
    """Attach OHLC/volume fields from nightly EOD when available."""
    row = {
        "symbol": symbol,
        "name": name,
        "price": quote.get("price"),
        "change_pct": quote.get("change_pct"),
        "volume": quote.get("volume"),
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "source": quote.get("source") or "eod_local",
    }
    try:
        from app.services.market_data.equity_eod_store import read_bars as eod_bars

        bars = eod_bars(symbol)
        if len(bars) >= 1:
            last = bars[-1]
            row["day_high"] = _num(last.get("high"))
            row["day_low"] = _num(last.get("low"))
            if row["volume"] is None:
                row["volume"] = last.get("volume")
        if len(bars) >= 2:
            row["prev_close"] = _num(bars[-2].get("close"))
    except Exception as exc:
        logger.warning(
            "eod bar enrich unavailable",
            symbol=symbol,
            error=str(exc)[:200],
        )
    return row


def _parse_yahoo_chart(payload: dict[str, Any]) -> tuple[float | None, float | None, list[tuple[str, float]]]:
    """Return (last_price, change_pct, daily closes for rebase)."""
    try:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None, None, []
        block = result[0]
        meta = block.get("meta") or {}
        timestamps = block.get("timestamp") or []
        closes_raw = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        closes: list[tuple[str, float]] = []
        for ts, close in zip(timestamps, closes_raw):
            if close is None:
                continue
            try:
                day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                closes.append((day, float(close)))
            except (TypeError, ValueError, OSError):
                continue
        if not closes:
            price = _num(meta.get("regularMarketPrice"))
            return price, None, []
        last = closes[-1][1]
        prev = closes[-2][1] if len(closes) > 1 else _num(meta.get("chartPreviousClose")) or last
        chg = ((last / prev) - 1.0) * 100.0 if prev else None
        return last, chg, closes
    except Exception:
        return None, None, []


async def _yahoo_chart(
    client: httpx.AsyncClient,
    symbol: str,
    *,
    range_: str = "5d",
) -> tuple[float | None, float | None, list[tuple[str, float]]]:
    try:
        resp = await client.get(
            _YAHOO_CHART.format(symbol=symbol),
            params={"range": range_, "interval": "1d"},
        )
        if resp.status_code != 200:
            return None, None, []
        return _parse_yahoo_chart(resp.json())
    except Exception as exc:
        logger.debug("overview_yahoo_failed", ticker=symbol, error=str(exc)[:160])
        return None, None, []


async def _quote_row(
    client: httpx.AsyncClient,
    symbol: str,
    name: str,
) -> dict[str, Any]:
    # Prefer nightly equity EOD / Stooq bulk when present — shared with charts/robots.
    try:
        from app.services.market_data.equity_eod_store import read_latest_quote as eod_quote

        local = eod_quote(symbol)
        if local.get("price") is not None:
            return _enrich_from_eod_bars(symbol, name, local)
    except Exception as exc:
        logger.debug("overview_eod_local_miss", ticker=symbol, error=str(exc)[:120])

    try:
        from app.services.market_data.stooq_bulk_store import read_latest_quote

        local = read_latest_quote(symbol)
        if local.get("price") is not None:
            return {
                "symbol": symbol,
                "name": name,
                "price": local.get("price"),
                "change_pct": local.get("change_pct"),
                "volume": local.get("volume"),
                "prev_close": None,
                "day_high": None,
                "day_low": None,
                "source": "stooq_local",
            }
    except Exception as exc:
        logger.debug("overview_stooq_local_miss", ticker=symbol, error=str(exc)[:120])

    price, chg, _ = await _yahoo_chart(client, symbol, range_="5d")
    if price is None:
        # Soft fallback — short timeout so one lagging provider cannot empty the board.
        try:
            from app.services.market_data.client import get_latest_quote_resolved
            from app.services.market_data.quote_utils import enrich_quote_fields, extract_quote_price

            quote = enrich_quote_fields(
                dict(await asyncio.wait_for(get_latest_quote_resolved(symbol), timeout=4.0)),
                None,
            )
            price = extract_quote_price(quote) if isinstance(quote, dict) else None
            if isinstance(quote, dict):
                chg = _num(quote.get("change_pct") or quote.get("changePercent"))
            return {
                "symbol": symbol,
                "name": name,
                "price": price,
                "change_pct": chg,
                "volume": _num(quote.get("volume")) if isinstance(quote, dict) else None,
                "prev_close": None,
                "day_high": None,
                "day_low": None,
                "source": (quote or {}).get("source") if isinstance(quote, dict) else None,
            }
        except Exception as exc:
            logger.debug("overview_quote_fallback_failed", ticker=symbol, error=str(exc)[:160])
            return _empty_row(symbol, name)

    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "change_pct": chg,
        "volume": None,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "source": "yahoo_chart",
    }


async def _compare_series(client: httpx.AsyncClient, symbol: str) -> list[dict[str, Any]]:
    try:
        from app.services.market_data.equity_eod_store import read_bars as eod_bars

        local_bars = eod_bars(symbol)
        if len(local_bars) >= 2:
            closes = [
                (str(b.get("timestamp") or "")[:10], float(b["close"]))
                for b in local_bars[-90:]
                if b.get("close") is not None
            ]
            rebased = rebase_closes(closes)
            if rebased:
                return rebased
    except Exception as exc:
        logger.debug("overview_eod_bars_miss", ticker=symbol, error=str(exc)[:120])

    try:
        from app.services.market_data.stooq_bulk_store import read_bars

        local_bars = read_bars(symbol)
        if len(local_bars) >= 2:
            closes = [
                (str(b.get("timestamp") or "")[:10], float(b["close"]))
                for b in local_bars[-90:]
                if b.get("close") is not None
            ]
            rebased = rebase_closes(closes)
            if rebased:
                return rebased
    except Exception as exc:
        logger.debug("overview_stooq_local_bars_miss", ticker=symbol, error=str(exc)[:120])

    _, _, closes = await _yahoo_chart(client, symbol, range_="6mo")
    if len(closes) >= 2:
        return rebase_closes(closes[-90:])
    try:
        from app.services.market_data.client import get_bars_resolved

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=120)
        bars = await asyncio.wait_for(get_bars_resolved(symbol, "1d", start, end), timeout=8.0)
        out: list[tuple[str, float]] = []
        for bar in bars[-90:]:
            try:
                out.append((str(bar.get("timestamp") or bar.get("date") or ""), float(bar["close"])))
            except (KeyError, TypeError, ValueError):
                continue
        return rebase_closes(out)
    except Exception as exc:
        logger.debug("overview_bars_failed", ticker=symbol, error=str(exc)[:160])
        return []


async def _news_rows(client: httpx.AsyncClient, *, limit: int = 8) -> list[dict[str, Any]]:
    """Yahoo Finance RSS first (no key); soft fallback to free keyed feeds."""
    from xml.etree import ElementTree as ET

    out: list[dict[str, Any]] = []
    try:
        resp = await client.get(
            "https://feeds.finance.yahoo.com/rss/2.0/headline",
            params={"s": "SPY,QQQ,IWM", "region": "US", "lang": "en-US"},
        )
        if resp.status_code == 200 and "<item" in resp.text:
            root = ET.fromstring(resp.text)
            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title:
                    continue
                out.append(
                    {
                        "title": title,
                        "url": link or "#",
                        "source": "yahoo_rss",
                        "published_at": item.findtext("pubDate"),
                        "summary": (item.findtext("description") or "")[:240],
                    }
                )
    except Exception as exc:
        logger.debug("overview_yahoo_rss_failed", error=str(exc)[:160])

    if len(out) >= 3:
        return out[:limit]

    try:
        from app.services.news.free_feeds import fetch_gdelt

        extra = await asyncio.wait_for(
            fetch_gdelt("stock market OR S&P OR Nasdaq OR Fed", limit=limit),
            timeout=4.0,
        )
        seen = {str(r.get("url") or r.get("title") or "") for r in out}
        for row in extra:
            key = str(row.get("url") or row.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= limit:
                break
    except Exception as exc:
        logger.debug("overview_news_fallback_failed", error=str(exc)[:160])
    return out[:limit]


async def _macro_rows() -> list[dict[str, Any]]:
    """Prefer local FRED cache (nightly); live FRED API as fill-in."""
    rows: list[dict[str, Any]] = []
    try:
        from app.services.market_data.fred_bulk_store import overview_macro_rows

        rows = overview_macro_rows()
        if len(rows) >= 3:
            return rows
    except Exception as exc:
        logger.debug("overview_fred_local_miss", error=str(exc)[:160])

    try:
        from app.core.config import settings
        from app.services.macro_registry.fred_client import fetch_fred_series_json

        if not (settings.FRED_API_KEY or "").strip():
            return rows
        import json

        have = {str(r.get("id")) for r in rows}
        series = [
            ("UNRATE", "безработица США, %"),
            ("FEDFUNDS", "ставка ФРС, %"),
            ("VIXCLS", "индекс страха VIX"),
            ("DGS10", "доходность 10 лет, %"),
        ]
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=8.0)) as client:
            for sid, label in series:
                if sid in have:
                    continue
                try:
                    raw = await fetch_fred_series_json(client, sid, lookback_days=120)
                    payload = json.loads(raw)
                    obs = [o for o in (payload.get("observations") or []) if o.get("value") not in {".", "", None}]
                    if not obs:
                        continue
                    last = obs[-1]
                    rows.append(
                        {
                            "id": sid,
                            "label": label,
                            "value": float(last["value"]),
                            "date": last.get("date"),
                            "source": "fred",
                        }
                    )
                except Exception as exc:
                    logger.debug("overview_fred_failed", series=sid, error=str(exc)[:120])
    except Exception as exc:
        logger.debug("overview_macro_skipped", error=str(exc)[:160])
    return rows


def _coverage(groups: dict[str, list[dict[str, Any]]]) -> int:
    n = 0
    for rows in groups.values():
        for row in rows:
            if _num(row.get("price")) is not None:
                n += 1
    return n


async def build_market_overview() -> dict[str, Any]:
    from app.utils.cache import cache_get, cache_lock_acquire, cache_lock_release, cache_set

    global _LAST_GOOD_OVERVIEW
    cached = await cache_get(_OVERVIEW_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("groups") and _coverage(cached["groups"]) >= 5:
        _LAST_GOOD_OVERVIEW = cached
        return _tag_overview(cached)

    # Cold miss under load: serve last-good while one worker rebuilds (singleflight).
    if isinstance(_LAST_GOOD_OVERVIEW, dict) and _coverage(_LAST_GOOD_OVERVIEW.get("groups") or {}) >= 3:
        got_lock = await cache_lock_acquire(_OVERVIEW_LOCK_KEY, ttl=30)
        if not got_lock:
            return _stale_overview(_LAST_GOOD_OVERVIEW, rebuilding=True)
    else:
        got_lock = await cache_lock_acquire(_OVERVIEW_LOCK_KEY, ttl=30)
        if not got_lock:
            # Another worker is computing; brief wait then re-check cache.
            await asyncio.sleep(0.35)
            cached2 = await cache_get(_OVERVIEW_CACHE_KEY)
            if isinstance(cached2, dict) and _coverage(cached2.get("groups") or {}) >= 3:
                return _tag_overview(cached2)

    async def _compute() -> dict[str, Any]:
        local_groups = _board_from_local_only()
        if local_groups is not None:
            groups = local_groups
            compare: dict[str, Any] = {}
            for sym in COMPARE_SYMBOLS:
                try:
                    local_bars: list[dict[str, Any]] = []
                    try:
                        from app.services.market_data.equity_eod_store import read_bars as eod_bars

                        local_bars = eod_bars(sym) or []
                    except Exception:
                        local_bars = []
                    if len(local_bars) < 2:
                        try:
                            from app.services.market_data.stooq_bulk_store import read_bars as stooq_bars

                            local_bars = stooq_bars(sym) or []
                        except Exception:
                            local_bars = []
                    if len(local_bars) >= 2:
                        closes = [
                            (str(b.get("timestamp") or "")[:10], float(b["close"]))
                            for b in local_bars[-90:]
                            if b.get("close") is not None
                        ]
                        compare[sym] = rebase_closes(closes)
                    else:
                        compare[sym] = []
                except Exception:
                    compare[sym] = []
            try:
                async with httpx.AsyncClient(
                    **httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(8.0, connect=3.0)),
                    headers=_YAHOO_HEADERS,
                ) as client:
                    news = await asyncio.wait_for(_news_rows(client, limit=8), timeout=5.0)
            except Exception:
                news = []
            try:
                macro = await asyncio.wait_for(_macro_rows(), timeout=4.0)
            except Exception:
                macro = []
            fx_matrix: list[dict[str, Any]] = []
            fx_rows = groups.get("fx") or []
            for left in fx_rows:
                for right in fx_rows:
                    a = _num(left.get("change_pct"))
                    b = _num(right.get("change_pct"))
                    fx_matrix.append(
                        {
                            "row": left["symbol"],
                            "col": right["symbol"],
                            "delta": None if a is None or b is None else round(a - b, 3),
                        }
                    )
            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "regime": regime_from_board(groups),
                "groups": groups,
                "compare": compare,
                "news": news,
                "macro": macro,
                "fx_matrix": fx_matrix,
                "coverage": _coverage(groups),
                "source": "котировки",
                "data_layer": _data_layer_status(),
            }

        kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(10.0, connect=3.0))
        async with httpx.AsyncClient(**kwargs, headers=_YAHOO_HEADERS) as client:
            quote_jobs = [
                _quote_row(client, sym, name)
                for pairs in BOARD.values()
                for sym, name in pairs
            ]
            quotes = await _bounded_gather(quote_jobs, limit=_QUOTE_CONCURRENCY)
            by_symbol: dict[str, dict[str, Any]] = {}
            for item in quotes:
                if isinstance(item, dict) and item.get("symbol"):
                    by_symbol[str(item["symbol"])] = item

            groups = {}
            for key, pairs in BOARD.items():
                groups[key] = [
                    by_symbol.get(sym) or _empty_row(sym, name)
                    for sym, name in pairs
                ]

            compare_rows = await asyncio.gather(
                *[_compare_series(client, sym) for sym in COMPARE_SYMBOLS],
                return_exceptions=True,
            )
            compare = {}
            for sym, series in zip(COMPARE_SYMBOLS, compare_rows):
                compare[sym] = series if isinstance(series, list) else []

            try:
                news = await asyncio.wait_for(_news_rows(client, limit=8), timeout=6.0)
            except Exception as exc:
                logger.debug("overview_news_failed", error=str(exc)[:160])
                news = []

        fx_matrix = []
        fx_rows = groups.get("fx") or []
        for left in fx_rows:
            for right in fx_rows:
                a = _num(left.get("change_pct"))
                b = _num(right.get("change_pct"))
                fx_matrix.append(
                    {
                        "row": left["symbol"],
                        "col": right["symbol"],
                        "delta": None if a is None or b is None else round(a - b, 3),
                    }
                )

        try:
            macro = await asyncio.wait_for(_macro_rows(), timeout=6.0)
        except Exception:
            macro = []

        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "regime": regime_from_board(groups),
            "groups": groups,
            "compare": compare,
            "news": news,
            "macro": macro,
            "fx_matrix": fx_matrix,
            "coverage": _coverage(groups),
            "source": "котировки",
            "data_layer": _data_layer_status(),
        }

    try:
        # Re-check cache after acquiring lock (winner may have finished).
        cached3 = await cache_get(_OVERVIEW_CACHE_KEY)
        if isinstance(cached3, dict) and _coverage(cached3.get("groups") or {}) >= 5:
            _LAST_GOOD_OVERVIEW = cached3
            return _tag_overview(cached3)
        payload = await asyncio.wait_for(_compute(), timeout=_OVERVIEW_BUDGET_SEC)
    except Exception as exc:
        logger.warning("market_overview_failed", error=str(exc)[:200])
        if isinstance(_LAST_GOOD_OVERVIEW, dict) and _coverage(_LAST_GOOD_OVERVIEW.get("groups") or {}) >= 3:
            return _stale_overview(_LAST_GOOD_OVERVIEW)
        empty_groups = {
            key: [_empty_row(sym, name) for sym, name in pairs]
            for key, pairs in BOARD.items()
        }
        return _tag_overview({
            "as_of": datetime.now(timezone.utc).isoformat(),
            "regime": None,
            "groups": empty_groups,
            "compare": {},
            "news": [],
            "macro": [],
            "fx_matrix": [],
            "coverage": 0,
            "error": "quotes_unavailable",
            "data_layer": _data_layer_status(),
        })
    finally:
        await cache_lock_release(_OVERVIEW_LOCK_KEY)

    payload = _tag_overview(payload)
    if _coverage(payload.get("groups") or {}) >= 3:
        _LAST_GOOD_OVERVIEW = payload
        await cache_set(_OVERVIEW_CACHE_KEY, payload, ttl=_OVERVIEW_TTL)
    elif isinstance(_LAST_GOOD_OVERVIEW, dict):
        return _stale_overview(_LAST_GOOD_OVERVIEW)
    return payload


LIQUID_UNIVERSE: list[tuple[str, str, str]] = [
    ("AAPL", "Apple", "технологии"),
    ("MSFT", "Microsoft", "технологии"),
    ("NVDA", "NVIDIA", "технологии"),
    ("AMZN", "Amazon", "потребление"),
    ("GOOGL", "Alphabet", "связь"),
    ("META", "Meta", "связь"),
    ("BRK-B", "Berkshire", "финансы"),
    ("JPM", "JPMorgan", "финансы"),
    ("XOM", "Exxon", "энергия"),
    ("JNJ", "Johnson & Johnson", "здравоохранение"),
    ("UNH", "UnitedHealth", "здравоохранение"),
    ("PG", "Procter & Gamble", "товары первой необходимости"),
    ("HD", "Home Depot", "потребление"),
    ("SPY", "S&P 500", "индекс"),
    ("QQQ", "Nasdaq 100", "индекс"),
    ("XLK", "технологии", "сектор"),
    ("XLE", "энергия", "сектор"),
    ("GLD", "золото", "товар"),
]


async def fetch_free_screener(limit: int = 40) -> list[dict[str, Any]]:
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(12.0, connect=4.0))
    universe = LIQUID_UNIVERSE[:limit]
    async with httpx.AsyncClient(**kwargs, headers=_YAHOO_HEADERS) as client:
        jobs = [_quote_row(client, sym, name) for sym, name, _ in universe]
        rows = await _bounded_gather(jobs, limit=_QUOTE_CONCURRENCY)
    out: list[dict[str, Any]] = []
    for idx, (sym, name, sector) in enumerate(universe):
        row = rows[idx] if idx < len(rows) and isinstance(rows[idx], dict) else _empty_row(sym, name)
        item = dict(row)
        item["symbol"] = sym
        item["sector"] = sector
        item["name"] = row.get("name") or name
        item["exchange"] = "US"
        item["source"] = row.get("source") or "yahoo_chart"
        item.setdefault("pe", None)
        item.setdefault("market_cap", None)
        item.setdefault("beta", None)
        item.setdefault("volume", None)
        out.append(item)
    return out
