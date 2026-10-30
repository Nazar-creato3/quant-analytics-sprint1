"""In-memory total-return series store (Prompt 09)."""
from __future__ import annotations

from datetime import date
from threading import Lock

_lock = Lock()
_series: dict[str, list[float]] = {}
_dated_prices: dict[str, list[tuple[date, float]]] = {}


def reset() -> None:
    with _lock:
        _series.clear()
        _dated_prices.clear()


def put_series(ticker: str, returns: list[float]) -> None:
    with _lock:
        _series[ticker.upper()] = [float(x) for x in returns]


def get_series(ticker: str) -> list[float]:
    """Injected series first (tests, simulations), then the persistent price history."""
    with _lock:
        hit = _series.get(ticker.upper())
    if hit:
        return list(hit)
    from app.services.price_history import service as history

    out = history.returns(ticker)
    if not out:
        history.want([ticker])
    return out


def put_dated_prices(ticker: str, rows: list[tuple[date, float]]) -> None:
    """Official closes by session date — required for decision timing metrics."""
    with _lock:
        _dated_prices[ticker.upper()] = [(d, float(p)) for d, p in rows]


def get_dated_prices(ticker: str) -> list[tuple[date, float]]:
    with _lock:
        hit = _dated_prices.get(ticker.upper())
    if hit:
        return list(hit)
    from app.services.price_history import service as history

    return history.closes(ticker)


def snapshot() -> dict[str, list[float]]:
    with _lock:
        return {k: list(v) for k, v in _series.items()}
