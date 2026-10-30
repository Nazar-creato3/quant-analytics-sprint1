"""In-memory bond reference, cashflows, G-curve. SQL is filled by the daily task."""
from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock
from typing import Any

_lock = Lock()
_refs: dict[str, dict[str, Any]] = {}
_events: dict[str, list[dict[str, Any]]] = {}
_curve: list[dict[str, Any]] = []
_quality: list[dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _refs.clear()
        _events.clear()
        _curve.clear()
        _quality.clear()


def put_reference(row: dict[str, Any]) -> None:
    key = str(row.get("figi") or row.get("secid") or "").upper()
    if not key:
        raise ValueError("figi or secid required")
    payload = dict(row)
    payload["figi"] = key
    payload["as_of"] = payload.get("as_of") or datetime.now(timezone.utc).isoformat()
    with _lock:
        _refs[key] = payload


def put_events(figi: str, rows: list[dict[str, Any]]) -> None:
    with _lock:
        _events[figi.upper()] = [dict(r) for r in rows]


def put_curve(points: list[dict[str, Any]]) -> None:
    with _lock:
        _curve.clear()
        _curve.extend(dict(p) for p in points)


def log_quality(entry: dict[str, Any]) -> None:
    with _lock:
        _quality.append(dict(entry))


def get_reference(figi: str) -> dict[str, Any] | None:
    with _lock:
        return dict(_refs[figi.upper()]) if figi.upper() in _refs else None


def get_events(figi: str) -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in _events.get(figi.upper(), [])]


def curve_points() -> list[tuple[float, float]]:
    with _lock:
        return [(float(p["tenor_years"]), float(p["yield"])) for p in _curve]


def curve_as_of() -> str | None:
    with _lock:
        if not _curve:
            return None
        return str(_curve[0].get("as_of") or "")


def quality_log() -> list[dict[str, Any]]:
    with _lock:
        return [dict(x) for x in _quality]


def all_refs() -> dict[str, dict[str, Any]]:
    with _lock:
        return {k: dict(v) for k, v in _refs.items()}


def future_cashflows(figi: str, settlement: date) -> tuple[list[date], list[float], list[dict[str, Any]]]:
    rows = get_events(figi)
    dates: list[date] = []
    amts: list[float] = []
    meta: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: str(r.get("on_date") or "")):
        raw = row.get("on_date")
        if not raw:
            continue
        on = date.fromisoformat(str(raw)[:10])
        if on <= settlement:
            continue
        amt = row.get("amount_per_bond")
        if amt is None:
            continue
        dates.append(on)
        amts.append(float(amt))
        meta.append(row)
    return dates, amts, meta
