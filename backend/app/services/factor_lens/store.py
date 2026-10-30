"""Daily factor returns cache. Table factor_returns is the durable owner."""
from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock
from typing import Any

_lock = Lock()
_returns: dict[str, list[float]] = {}
_dates: list[date] = []
_as_of: datetime | None = None
_source: str | None = None
_missing: list[str] = []


def reset() -> None:
    with _lock:
        _returns.clear()
        _dates.clear()
        global _as_of, _source, _missing
        _as_of = None
        _source = None
        _missing = []


def put_factor_panel(
    panel: dict[str, list[float]],
    *,
    dates: list[date] | None = None,
    source: str,
    missing: list[str] | None = None,
) -> None:
    with _lock:
        _returns.clear()
        for name, values in panel.items():
            _returns[str(name)] = [float(v) for v in values]
        _dates.clear()
        if dates:
            _dates.extend(dates)
        global _as_of, _source, _missing
        _as_of = datetime.now(timezone.utc)
        _source = source
        _missing = list(missing or [])


def get_panel() -> dict[str, list[float]]:
    with _lock:
        return {k: list(v) for k, v in _returns.items()}


def _user_source(raw: str | None) -> str:
    """Hide fixture and table names. The screen only needs a plain label."""
    if not raw:
        return "нет данных"
    return "оценка"


def snapshot(*, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    with _lock:
        panel = {k: list(v) for k, v in _returns.items()}
        dates = list(_dates)
        as_of = _as_of
        source = _source
        missing = list(_missing)
    if dates and panel:
        keep = [
            i
            for i, day in enumerate(dates)
            if (start is None or day >= start) and (end is None or day <= end)
        ]
        if keep:
            dates = [dates[i] for i in keep]
            panel = {k: [v[i] for i in keep if i < len(v)] for k, v in panel.items()}
    if not panel:
        return {
            "data_status": "нет данных",
            "reason": "нет рядов",
            "factors": {},
            "dates": [],
            "as_of": None,
            "source": _user_source(source),
            "missing": missing,
            "methodology": "/methodology/factor-lens",
        }
    status = "частично" if missing else "ok"
    return {
        "data_status": status,
        "reason": None if not missing else "пропущено: " + ", ".join(missing),
        "factors": panel,
        "dates": [d.isoformat() for d in dates],
        "as_of": as_of.isoformat() if as_of else None,
        "source": _user_source(source),
        "missing": missing,
        "methodology": "/methodology/factor-lens",
    }
