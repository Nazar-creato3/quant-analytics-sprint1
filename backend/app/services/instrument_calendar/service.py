"""Corporate-event calendar (Prompt 21). No invented coupons or cutoffs."""
from __future__ import annotations

from threading import Lock
from typing import Any

from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled

_lock = Lock()
_subs: dict[str, list[str]] = {}


def reset() -> None:
    with _lock:
        _subs.clear()


def _require() -> None:
    if not is_enabled("qa_calendar"):
        raise RuntimeError("qa_calendar off")


def subscribe(*, user_id: str, ticker: str) -> dict[str, Any]:
    _require()
    t = ticker.upper()
    with _lock:
        rows = _subs.setdefault(user_id, [])
        if t not in rows:
            rows.append(t)
        watch = list(rows)
    return {"user_id": user_id, "tickers": watch}


def events_for_user(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    _require()
    book = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    held = [p.ticker.upper() for p in book if p.ticker != "CASH"]
    with _lock:
        extra = list(_subs.get(user_id) or [])
    tickers = sorted(set(held + extra))
    return {
        "source": "instrument_calendar",
        "user_id": user_id,
        "tickers": tickers,
        "events": [],
        "data_status": "нет данных",
        "reason": "нет лицензированного календаря отсечек и купонов",
    }
