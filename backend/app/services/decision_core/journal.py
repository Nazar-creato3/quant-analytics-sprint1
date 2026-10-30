"""Shown signals, user action, and 1/3/6 month outcome from prompt 59."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

HORIZONS = {"m1": 1, "m3": 3, "m6": 6}
ACTIONS = {"opened", "noted", "dismissed"}

_path: Path | None = None
_entries: list[dict[str, Any]] = []
_founder_reviewed = False


def configure(path: Path | None = None) -> None:
    global _path, _entries, _founder_reviewed
    _path = path
    _entries = []
    _founder_reviewed = False
    if path and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        _entries = list(data.get("entries") or [])
        _founder_reviewed = bool(data.get("founder_reviewed"))


def reset_for_tests() -> None:
    configure(None)


def founder_reviewed() -> bool:
    return _founder_reviewed


def mark_founder_reviewed() -> None:
    """Not exposed over HTTP. Founder review is a local state change."""
    global _founder_reviewed
    _founder_reviewed = True
    _flush()


def entries_for(user_id: str) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in _entries if row["user_id"] == user_id]


def _flush() -> None:
    if _path is None:
        return
    _path.parent.mkdir(parents=True, exist_ok=True)
    _path.write_text(
        json.dumps({"founder_reviewed": _founder_reviewed, "entries": _entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _today(as_of: date | None) -> date:
    return as_of or datetime.now(UTC).date()


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    lengths = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(day.day, lengths[month - 1]))


def record_shown(user_id: str, signals: list[dict[str, Any]], *, as_of: date | None = None) -> list[dict[str, Any]]:
    day = _today(as_of)
    shown: list[dict[str, Any]] = []
    for signal in signals:
        existing = next(
            (
                row
                for row in _entries
                if row["user_id"] == user_id and row["signal_id"] == signal["signal_id"] and row["shown_on"] == day.isoformat()
            ),
            None,
        )
        if existing is None:
            existing = {
                "id": uuid4().hex,
                "user_id": user_id,
                "signal_id": signal["signal_id"],
                "module": signal["module"],
                "source": signal["source"],
                "figure": signal["figure"],
                "shown_on": day.isoformat(),
                "action": None,
                "outcomes": {
                    key: {"due": add_months(day, months).isoformat(), "data_status": "нет данных", "total_rubles": None}
                    for key, months in HORIZONS.items()
                },
            }
            _entries.append(existing)
        else:
            existing["figure"] = signal["figure"]
        shown.append(deepcopy(existing))
    _flush()
    return shown


def record_action(user_id: str, entry_id: str, action: str) -> dict[str, Any] | None:
    if action not in ACTIONS:
        raise ValueError("неизвестное действие")
    for row in _entries:
        if row["id"] == entry_id and row["user_id"] == user_id:
            row["action"] = action
            _flush()
            return deepcopy(row)
    return None


def _price_of_decisions(user_id: str, mode: str, *, as_of: date) -> dict[str, Any]:
    from app.services.decisions_report.service import analyze_decisions

    payload = analyze_decisions(user_id=user_id, mode=mode, date_to=as_of)
    rubles = payload.get("total_rubles")
    status = "ok" if rubles is not None else "нет данных"
    return {
        "data_status": status,
        "total_rubles": None if rubles is None else str(rubles),
        "source": "decisions_report.analyze_decisions",
        "as_of": as_of.isoformat(),
    }


def settle(user_id: str, *, mode: str = "paper", as_of: date | None = None) -> list[dict[str, Any]]:
    day = _today(as_of)
    updated: list[dict[str, Any]] = []
    for row in _entries:
        if row["user_id"] != user_id:
            continue
        changed = False
        for key in HORIZONS:
            slot = row["outcomes"][key]
            due = date.fromisoformat(slot["due"])
            if day < due:
                slot["data_status"] = "нет данных"
                slot["reason"] = "срок не наступил"
                slot["total_rubles"] = None
                changed = True
                continue
            if slot.get("data_status") == "ok" and slot.get("total_rubles") is not None:
                continue
            try:
                price = _price_of_decisions(user_id, mode, as_of=due)
            except Exception:  # noqa: BLE001 — цена решений не должна ронять журнал
                price = {
                    "data_status": "нет данных",
                    "total_rubles": None,
                    "reason": "нет данных",
                    "source": "decisions_report.analyze_decisions",
                }
            slot["data_status"] = price["data_status"]
            slot["total_rubles"] = price.get("total_rubles")
            slot["source"] = price.get("source")
            slot["reason"] = price.get("reason")
            slot["priced_on"] = price.get("as_of") or due.isoformat()
            changed = True
        if changed:
            updated.append(deepcopy(row))
    _flush()
    return updated
