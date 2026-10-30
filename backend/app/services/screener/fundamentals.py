"""Live screener fields: market cap, P/E, beta, dividend yield, volume, volatility, ES.

Sources, best first, each field filled once:
1. xFinLink metrics (``XFINLINK_API_KEY``; free tier = 1 ticker/request, 100/day) —
   filing-based market cap and P/E.
2. Yahoo via yfinance ``Ticker.info`` (free, no key) — market cap, P/E, beta,
   dividend yield, average volume.
3. Computed from daily closes (yfinance history): annualised volatility,
   historical ES 97.5 %, and beta vs SPY when no vendor beta exists.

Results are cached per symbol (12 h) so the free quotas are not burned on every
page view; a field nobody can supply stays None (UI shows «нет данных», never 0).
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

XFINLINK_BASE = "https://api.xfinlink.com/v1"
_CACHE_TTL = 12 * 3600
_CACHE_PREFIX = "screener:live:v1:"
_FIELDS = ("market_cap", "pe", "beta", "dividend", "volume", "volatility", "es_975")
_CONCURRENCY = asyncio.Semaphore(4)


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _yahoo_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


# ── xFinLink ───────────────────────────────────────────────────────────────
def parse_xfinlink_metrics(payload: dict[str, Any]) -> dict[str, float | None]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[0] if isinstance(rows[0], dict) else {}
    units = ((payload.get("meta") or {}).get("units") or "millions_usd").lower()
    mcap = _num(row.get("market_cap"))
    if mcap is not None and "million" in units:
        mcap *= 1_000_000
    return {"market_cap": mcap, "pe": _num(row.get("pe_ratio"))}


async def fetch_xfinlink(client: httpx.AsyncClient, symbol: str) -> dict[str, float | None]:
    key = (settings.XFINLINK_API_KEY or "").strip()
    if not key:
        return {}
    resp = await client.get(
        f"{XFINLINK_BASE}/metrics/{symbol.upper()}",
        params={"fields": "market_cap,pe_ratio", "period": "ttm", "limit": 1},
        headers={"X-API-Key": key, "Accept": "application/json"},
        timeout=15.0,
    )
    if resp.status_code != 200:
        logger.info("xfinlink_metrics_skip", symbol=symbol, status=resp.status_code)
        return {}
    return parse_xfinlink_metrics(resp.json())


# ── Yahoo (yfinance) ───────────────────────────────────────────────────────
def parse_yahoo_info(info: dict[str, Any]) -> dict[str, float | None]:
    dividend = _num(info.get("trailingAnnualDividendYield"))
    if dividend is not None:
        dividend *= 100.0  # fraction → %
    return {
        "market_cap": _num(info.get("marketCap")),
        "pe": _num(info.get("trailingPE")) or _num(info.get("forwardPE")),
        "beta": _num(info.get("beta")),
        "dividend": dividend,
        "volume": _num(info.get("averageVolume")) or _num(info.get("volume")),
    }


def risk_from_closes(closes: list[float], bench: list[float] | None = None) -> dict[str, float | None]:
    """Annualised vol, historical ES 97.5 % (as a positive loss fraction), beta vs bench."""
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a and b and a > 0 and b > 0]
    if len(rets) < 40:
        return {}
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(252)
    tail_n = max(1, int(len(rets) * 0.025))
    tail = sorted(rets)[:tail_n]
    es = -sum(tail) / len(tail)
    out: dict[str, float | None] = {"volatility": vol, "es_975": es}
    if bench and len(bench) == len(closes):
        b = [math.log(y / x) for x, y in zip(bench, bench[1:]) if x and y and x > 0 and y > 0]
        if len(b) == len(rets):
            bm = sum(b) / len(b)
            cov = sum((r - mean) * (q - bm) for r, q in zip(rets, b)) / (len(rets) - 1)
            bvar = sum((q - bm) ** 2 for q in b) / (len(b) - 1)
            if bvar > 0:
                out["beta"] = cov / bvar
    return out


def _yahoo_sync(symbol: str) -> tuple[dict[str, Any], list[float]]:
    import yfinance as yf

    t = yf.Ticker(_yahoo_symbol(symbol))
    try:
        info = t.info or {}
    except Exception:  # noqa: BLE001 - Yahoo throttles info harder than history
        info = {}
    try:
        hist = t.history(period="1y", interval="1d", auto_adjust=True)
        closes = [float(x) for x in hist["Close"].tolist()] if not hist.empty else []
    except Exception:  # noqa: BLE001
        closes = []
    return info, closes


async def _spy_closes() -> list[float]:
    cached = await cache_get(f"{_CACHE_PREFIX}__SPY_CLOSES")
    if isinstance(cached, list) and cached:
        return [float(x) for x in cached]
    _, closes = await asyncio.to_thread(_yahoo_sync, "SPY")
    if closes:
        await cache_set(f"{_CACHE_PREFIX}__SPY_CLOSES", closes, ttl=_CACHE_TTL)
    return closes


# ── Orchestration ──────────────────────────────────────────────────────────
async def _build_one(symbol: str, client: httpx.AsyncClient) -> dict[str, Any]:
    async with _CONCURRENCY:
        out: dict[str, Any] = {k: None for k in _FIELDS}
        sources: list[str] = []
        try:
            xf = await fetch_xfinlink(client, symbol)
        except Exception as exc:  # noqa: BLE001
            logger.info("xfinlink_metrics_failed", symbol=symbol, error=str(exc)[:120])
            xf = {}
        for k, v in xf.items():
            if v is not None:
                out[k] = v
        if any(v is not None for v in xf.values()):
            sources.append("xfinlink")

        info, closes = await asyncio.to_thread(_yahoo_sync, symbol)
        yh = parse_yahoo_info(info)
        filled = False
        for k, v in yh.items():
            if out.get(k) is None and v is not None:
                out[k] = v
                filled = True
        if filled:
            sources.append("yahoo")

        if closes:
            bench = await _spy_closes()
            n = min(len(closes), len(bench)) if bench else 0
            risk = risk_from_closes(closes[-n:], bench[-n:]) if n >= 41 else risk_from_closes(closes)
            for k, v in risk.items():
                if out.get(k) is None and v is not None:
                    out[k] = v
            if risk:
                sources.append("computed_1y")

        out["fundamentals_source"] = "+".join(sources) or None
        out["fundamentals_as_of"] = datetime.now(timezone.utc).date().isoformat()
        return out


async def live_fields(symbols: list[str], *, budget_sec: float = 20.0) -> dict[str, dict[str, Any]]:
    """Cached live fields per symbol. Symbols not ready within the budget keep loading
    in the background and appear on the next request."""
    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for sym in symbols:
        cached = await cache_get(f"{_CACHE_PREFIX}{sym.upper()}")
        if isinstance(cached, dict):
            result[sym.upper()] = cached
        else:
            missing.append(sym.upper())
    if not missing:
        return result

    client = httpx.AsyncClient()

    async def run(sym: str) -> None:
        try:
            row = await _build_one(sym, client)
            got_any = any(row.get(k) is not None for k in _FIELDS)
            # Empty answers (Yahoo throttled, no key) are retried in 30 min, not 12 h.
            await cache_set(f"{_CACHE_PREFIX}{sym}", row, ttl=_CACHE_TTL if got_any else 1800)
            result[sym] = row
        except Exception as exc:  # noqa: BLE001
            logger.warning("screener_live_failed", symbol=sym, error=str(exc)[:160])

    tasks = [asyncio.create_task(run(s)) for s in missing]
    _done, pending = await asyncio.wait(tasks, timeout=budget_sec)

    async def _close_later() -> None:
        if pending:
            await asyncio.wait(pending)
        await client.aclose()

    asyncio.create_task(_close_later())
    return dict(result)


def merge_live(row: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    """Fill only the fields the catalog row lacks; keep status flags consistent."""
    if not live:
        return row
    out = dict(row)
    for k in _FIELDS:
        if out.get(k) is None and live.get(k) is not None:
            out[k] = live[k]
    if live.get("fundamentals_source") and not out.get("fundamentals_source"):
        out["fundamentals_source"] = live["fundamentals_source"]
        out["fundamentals_as_of"] = live.get("fundamentals_as_of")
    for field, status in (("pe", "pe_status"), ("beta", "beta_status"), ("es_975", "es_status")):
        if status in out:
            out[status] = "ok" if out.get(field) is not None else "нет данных"
    return out
