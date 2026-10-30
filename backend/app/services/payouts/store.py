from __future__ import annotations

from threading import Lock
from typing import Any

_lock = Lock()
_dividends: list[dict[str, Any]] = []
_gaps: dict[str, dict[str, Any]] = {}
_prices: dict[str, float] = {}


def reset() -> None:
    with _lock:
        _dividends.clear()
        _gaps.clear()
        _prices.clear()


def put_dividends(rows: list[dict[str, Any]]) -> None:
    with _lock:
        _dividends.clear()
        _dividends.extend(dict(r) for r in rows)


def put_gap(ticker: str, payload: dict[str, Any]) -> None:
    with _lock:
        _gaps[ticker.upper()] = dict(payload)


def put_price(ticker: str, price: float) -> None:
    with _lock:
        _prices[ticker.upper()] = float(price)


def dividends() -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in _dividends]


def gap(ticker: str) -> dict[str, Any] | None:
    with _lock:
        row = _gaps.get(ticker.upper())
        return dict(row) if row else None


def price(ticker: str) -> float | None:
    with _lock:
        return _prices.get(ticker.upper())
