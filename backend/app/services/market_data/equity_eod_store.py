"""Nightly equity EOD cache for Markets board — Tiingo + Yahoo (Stooq complement).

Stooq nightly ZIP remains the full-universe path. This store covers the curated
BOARD / liquid universe with overwrite-only JSON bars so /markets and charts
stay populated when Stooq bandwidth/CAPTCHA fails.

Layout under EQUITY_EOD_DIR (default ``backend/data/equity_eod``)::

    current/{SYMBOL}.json
    manifest.json
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QuantAnalytics/1.0; +https://quantanalyticsclub.ru)",
    "Accept": "application/json",
}


def board_symbols() -> list[str]:
    from app.services.market_data.market_overview import BOARD, LIQUID_UNIVERSE

    seen: set[str] = set()
    out: list[str] = []
    for pairs in BOARD.values():
        for sym, _ in pairs:
            key = sym.upper()
            if key not in seen:
                seen.add(key)
                out.append(sym)
    for sym, _, _ in LIQUID_UNIVERSE:
        key = sym.upper()
        if key not in seen:
            seen.add(key)
            out.append(sym)
    return out


def bulk_root() -> Path:
    raw = (settings.EQUITY_EOD_DIR or "").strip()
    if raw:
        return Path(raw)
    stooq = (settings.STOOQ_BULK_DIR or "").strip()
    if stooq:
        return Path(stooq).resolve().parent / "equity_eod"
    return Path(settings.EUROSTAT_STORE_DIR).resolve().parent / "equity_eod"


def ensure_layout(root: Path | None = None) -> Path:
    base = root or bulk_root()
    (base / "current").mkdir(parents=True, exist_ok=True)
    return base


def _manifest_path(root: Path | None = None) -> Path:
    return (root or bulk_root()) / "manifest.json"


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        return {"symbols": {}, "synced_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"symbols": {}, "synced_at": None}


def save_manifest(payload: dict[str, Any], root: Path | None = None) -> None:
    base = ensure_layout(root)
    path = _manifest_path(base)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def symbol_path(ticker: str, root: Path | None = None) -> Path:
    safe = ticker.upper().replace("/", "_")
    return ensure_layout(root) / "current" / f"{safe}.json"


def _normalize_bars(rows: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            ts = str(row.get("timestamp") or row.get("date") or "")[:10]
            if len(ts) < 10:
                continue
            close = float(row["close"])
            out.append(
                {
                    "timestamp": f"{ts}T00:00:00+00:00",
                    "open": float(row["open"]) if row.get("open") is not None else close,
                    "high": float(row["high"]) if row.get("high") is not None else close,
                    "low": float(row["low"]) if row.get("low") is not None else close,
                    "close": close,
                    "volume": float(row["volume"]) if row.get("volume") not in (None, "") else 0.0,
                    "source": source,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda b: b["timestamp"])
    return out


async def _fetch_tiingo(ticker: str, *, days: int = 400) -> list[dict[str, Any]]:
    if ticker.upper() in {"BTC-USD", "BTCUSDT", "BTC"}:
        return []
    if not (settings.TIINGO_API_KEY or "").strip():
        return []
    from app.services.market_data.http_providers import TiingoClient

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    bars = await TiingoClient().get_bars(ticker, "1d", start, end)
    return _normalize_bars(bars, source="tiingo")


async def _fetch_yahoo(ticker: str, *, range_: str = "2y") -> list[dict[str, Any]]:
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(20.0, connect=5.0))
    async with httpx.AsyncClient(**kwargs, headers=_YAHOO_HEADERS) as client:
        resp = await client.get(
            _YAHOO_CHART.format(symbol=ticker),
            params={"range": range_, "interval": "1d"},
        )
        if resp.status_code != 200:
            return []
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return []
        block = result[0]
        timestamps = block.get("timestamp") or []
        quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        vols = quote.get("volume") or []
        rows: list[dict[str, Any]] = []
        for i, ts in enumerate(timestamps):
            try:
                if i >= len(closes) or closes[i] is None:
                    continue
                day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append(
                    {
                        "timestamp": day,
                        "open": opens[i] if i < len(opens) else closes[i],
                        "high": highs[i] if i < len(highs) else closes[i],
                        "low": lows[i] if i < len(lows) else closes[i],
                        "close": closes[i],
                        "volume": vols[i] if i < len(vols) else 0,
                    }
                )
            except (TypeError, ValueError, OSError, IndexError):
                continue
        return _normalize_bars(rows, source="yahoo_chart")


async def fetch_symbol_bars(ticker: str) -> tuple[list[dict[str, Any]], str]:
    try:
        bars = await _fetch_tiingo(ticker)
        if len(bars) >= 5:
            return bars, "tiingo"
    except Exception as exc:
        logger.debug("eod_tiingo_failed", ticker=ticker, error=str(exc)[:160])
    try:
        bars = await _fetch_yahoo(ticker)
        if bars:
            return bars, "yahoo_chart"
    except Exception as exc:
        logger.debug("eod_yahoo_failed", ticker=ticker, error=str(exc)[:160])
    return [], "none"


def read_bars(
    ticker: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    path = symbol_path(ticker, root=root)
    if not path.is_file():
        # try without hyphen variants
        alt = ticker.upper().replace("-", "")
        if alt != ticker.upper():
            path = symbol_path(alt, root=root)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    bars = payload.get("bars") or []
    start_s = start.date().isoformat() if start else None
    end_s = end.date().isoformat() if end else None
    out: list[dict[str, Any]] = []
    for bar in bars:
        ts = str(bar.get("timestamp") or "")[:10]
        if start_s and ts < start_s:
            continue
        if end_s and ts > end_s:
            continue
        out.append(bar)
    return out


def read_latest_quote(ticker: str, *, root: Path | None = None) -> dict[str, Any]:
    bars = read_bars(ticker, root=root)
    if not bars:
        return {"ticker": ticker.upper(), "price": None, "source": "eod_local"}
    last = bars[-1]
    prev = bars[-2]["close"] if len(bars) > 1 else last["close"]
    close = float(last["close"])
    change = ((close - float(prev)) / float(prev) * 100.0) if prev else None
    return {
        "ticker": ticker.upper(),
        "price": close,
        "change_pct": change,
        "volume": last.get("volume"),
        "source": last.get("source") or "eod_local",
    }


class EquityEodLocalClient:
    """File-backed daily bars/quotes from nightly Tiingo/Yahoo board sync."""

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        if timeframe not in {"1d", "1w", "1wk"}:
            return []
        return read_bars(ticker, start=start, end=end)

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        return read_latest_quote(ticker)


async def sync_equity_eod(
    *,
    symbols: list[str] | None = None,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Overwrite-sync curated equity daily bars."""
    base = ensure_layout()
    tickers = symbols or board_symbols()
    sem = asyncio.Semaphore(concurrency)
    synced: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    async def _one(sym: str) -> None:
        async with sem:
            try:
                bars, source = await fetch_symbol_bars(sym)
                if len(bars) < 2:
                    errors.append({"symbol": sym, "error": "empty"})
                    return
                payload = {
                    "symbol": sym.upper(),
                    "source": source,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "bars": bars,
                }
                path = symbol_path(sym, root=base)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
                synced[sym.upper()] = {
                    "bars": len(bars),
                    "last": str(bars[-1].get("timestamp") or "")[:10],
                    "source": source,
                }
            except Exception as exc:
                errors.append({"symbol": sym, "error": str(exc)[:160]})

    await asyncio.gather(*[_one(s) for s in tickers])

    if not synced:
        existing = load_manifest(base)
        return {
            "ok": False,
            "status": "sync_failed",
            "kept_previous": bool(existing.get("symbols")),
            "errors": errors,
            "root": str(base),
            "synced_at": existing.get("synced_at"),
        }

    prev = load_manifest(base)
    symbols_meta = dict(prev.get("symbols") or {})
    symbols_meta.update(synced)
    manifest = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols_meta,
        "errors": errors,
        "overwrite": True,
    }
    save_manifest(manifest, base)
    return {
        "ok": True,
        "status": "synced",
        "symbol_count": len(synced),
        "symbols": synced,
        "errors": errors,
        "synced_at": manifest["synced_at"],
        "root": str(base),
        "overwrite": True,
    }


def store_status(root: Path | None = None) -> dict[str, Any]:
    base = root or bulk_root()
    manifest = load_manifest(base)
    return {
        "root": str(base),
        "synced_at": manifest.get("synced_at"),
        "symbol_count": len(manifest.get("symbols") or {}),
        "tiingo_configured": bool((settings.TIINGO_API_KEY or "").strip()),
        "overwrite": True,
    }
