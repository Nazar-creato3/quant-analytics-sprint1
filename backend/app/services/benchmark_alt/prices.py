"""Dated official closes for K1 alternatives. Injected store first, then EOD cache."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from threading import Lock
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = Lock()
_prices: dict[str, dict[date, Decimal]] = {}
_meta: dict[str, dict[str, str]] = {}


def reset() -> None:
    with _lock:
        _prices.clear()
        _meta.clear()


def put_prices(
    ticker: str,
    points: dict[date, Decimal] | list[tuple[date, Decimal]],
    *,
    source: str,
    as_of: date | None = None,
) -> None:
    series: dict[date, Decimal] = {}
    if isinstance(points, dict):
        items = points.items()
    else:
        items = points
    for day, price in items:
        series[day] = price if isinstance(price, Decimal) else Decimal(str(price))
    key = ticker.upper()
    with _lock:
        _prices[key] = series
        last = max(series) if series else as_of
        _meta[key] = {
            "source": source,
            "as_of": (as_of or last).isoformat() if (as_of or last) else "",
        }


def get_meta(ticker: str) -> dict[str, str]:
    with _lock:
        return dict(_meta.get(ticker.upper(), {}))


def series_from_store(ticker: str) -> list[tuple[date, Decimal]]:
    with _lock:
        raw = dict(_prices.get(ticker.upper(), {}))
    return sorted(raw.items())


def series_from_eod_store(ticker: str) -> tuple[list[tuple[date, Decimal]], dict[str, str]]:
    from app.services.market_data.equity_eod_store import read_bars, read_latest_quote

    bars = read_bars(ticker)
    out: list[tuple[date, Decimal]] = []
    source = "equity_eod_store"
    last_day: date | None = None
    for bar in bars:
        ts = str(bar.get("timestamp") or "")[:10]
        close = bar.get("close")
        if len(ts) < 10 or close is None:
            continue
        try:
            day = date.fromisoformat(ts)
            price = Decimal(str(close))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append((day, price))
        last_day = day
        if bar.get("source"):
            source = str(bar["source"])
    quote: dict[str, Any] = read_latest_quote(ticker)
    if quote.get("source"):
        source = str(quote["source"])
    meta = {
        "source": source,
        "as_of": last_day.isoformat() if last_day else "",
    }
    return out, meta


def load_price_series(ticker: str) -> tuple[list[tuple[date, Decimal]], dict[str, str]]:
    stored = series_from_store(ticker)
    if stored:
        return stored, get_meta(ticker) or {"source": "injected", "as_of": stored[-1][0].isoformat()}
    try:
        return series_from_eod_store(ticker)
    except Exception as exc:
        logger.warning("k1 eod store read failed", ticker=ticker, error=str(exc)[:200])
        return [], {"source": "", "as_of": ""}
