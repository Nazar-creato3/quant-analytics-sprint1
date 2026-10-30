"""Read side of the price-history store: closes, returns, FX, valuation inputs.

Everything here is synchronous and file-backed, so the risk engine, returns,
key-rate and liquidity code can call it from anywhere. When a ticker has no
history yet, ``want()`` asks for a background sync and the caller degrades
honestly (no invented numbers).
"""
from __future__ import annotations

import statistics
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from app.services.price_history import store

MIN_RETURNS = 60  # ~3 months of sessions before a series is used for risk


def _bars(ticker: str) -> list[list[Any]]:
    if not store.enabled():
        return []
    data = store.read(ticker) or {}
    return [b for b in data.get("bars") or [] if isinstance(b, list) and len(b) >= 2 and b[1]]


def info(ticker: str) -> dict[str, Any]:
    """Where the history came from: source, market, board, ccy, bond duration/yield."""
    if not store.enabled():
        return {}
    data = dict(store.read(ticker) or {})
    data.pop("bars", None)
    return data


def closes(ticker: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for b in _bars(ticker):
        try:
            out.append((date.fromisoformat(str(b[0])[:10]), float(b[1])))
        except (TypeError, ValueError):
            continue
    return out


def returns(ticker: str) -> list[float]:
    """Simple daily close-to-close returns, oldest first (price return, dividends not reinvested)."""
    px = [p for _, p in closes(ticker)]
    out = [px[i] / px[i - 1] - 1.0 for i in range(1, len(px)) if px[i - 1] > 0]
    return out if len(out) >= MIN_RETURNS else []


def dated_returns(ticker: str) -> dict[date, float]:
    rows = closes(ticker)
    return {rows[i][0]: rows[i][1] / rows[i - 1][1] - 1.0 for i in range(1, len(rows)) if rows[i - 1][1] > 0}


def last(ticker: str) -> tuple[date, float] | None:
    rows = closes(ticker)
    return rows[-1] if rows else None


def ccy_of(ticker: str) -> str | None:
    meta = info(ticker)
    return str(meta.get("ccy") or "").upper() or None


def fx_rate(ccy: str | None) -> float | None:
    """Roubles per one unit of ``ccy`` (Bank of Russia official rate, latest)."""
    code = (ccy or "RUB").upper().replace("SUR", "RUB")
    if code == "RUB":
        return 1.0
    hit = last(f"FX_{code}")
    return hit[1] if hit else None


def to_rub(amount: float, ccy: str | None) -> float | None:
    rate = fx_rate(ccy)
    return None if rate is None else float(amount) * rate


def adv_rub(ticker: str, window: int = 20) -> float | None:
    """Median daily traded value over the last ``window`` sessions, in roubles."""
    bars = _bars(ticker)[-window:]
    ccy = ccy_of(ticker)
    vals: list[float] = []
    for b in bars:
        value = b[2] if len(b) > 2 else None
        if value in (None, 0) and len(b) > 3 and b[3]:
            value = float(b[3]) * float(b[1])  # volume × close when the feed has no value
        if value:
            vals.append(float(value))
    if not vals:
        return None
    med = statistics.median(vals)
    return to_rub(med, ccy) if ccy and ccy != "RUB" else med


def turnovers_rub(ticker: str, window: int = 20) -> list[float]:
    """Daily traded value in roubles for the last ``window`` sessions (0 on no-trade days)."""
    ccy = ccy_of(ticker)
    fx = fx_rate(ccy) if ccy and ccy != "RUB" else 1.0
    out: list[float] = []
    for b in _bars(ticker)[-window:]:
        value = b[2] if len(b) > 2 else None
        if value in (None, 0) and len(b) > 3 and b[3]:
            value = float(b[3]) * float(b[1])
        out.append(float(value or 0.0) * float(fx or 0.0))
    return out


def last_high_low(ticker: str) -> tuple[float, float] | None:
    for b in reversed(_bars(ticker)[-5:]):
        if len(b) > 5 and b[4] and b[5] and b[4] >= b[5] > 0:
            return float(b[4]), float(b[5])
    return None


def zero_days(ticker: str, window: int = 60) -> int:
    bars = _bars(ticker)[-window:]
    return sum(1 for b in bars if not (len(b) > 3 and b[3]))


def daily_sigma(ticker: str, window: int = 60) -> float | None:
    r = returns(ticker)[-window:]
    return statistics.pstdev(r) if len(r) >= 20 else None


def eod_map(tickers: Iterable[str]) -> dict[str, Any]:
    """Latest official close per ticker as EodRow, for valuation (returns, book values)."""
    from app.services.market_data.eod import EodRow

    out: dict[str, Any] = {}
    for t in tickers:
        hit = last(t)
        if not hit:
            continue
        meta = info(t)
        day, px = hit
        out[t.upper()] = EodRow(
            instrument_id=t.upper(),
            session_date=day,
            official_close=Decimal(str(px)),
            last_close=Decimal(str(px)),
            volume=None,
            source=str(meta.get("source") or "price_history"),
            board=meta.get("board"),
            license_tag="delayed_eod",
            as_of=day,
        )
    return out


def want(tickers: Iterable[str]) -> None:
    """Ask for a background sync of tickers that have no history yet (best effort)."""
    if not store.enabled():
        return
    missing = [t for t in tickers if t and t.upper() != "CASH" and not _bars(t)]
    if not missing:
        return
    from app.services.price_history.sync import schedule

    schedule(missing)
