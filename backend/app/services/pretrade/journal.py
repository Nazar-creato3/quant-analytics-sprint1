"""Decision log for the pre-trade gate."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

_lock = Lock()
_rows: list[dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _rows.clear()


def append(row: dict[str, Any]) -> None:
    item = dict(row)
    item["ts"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _rows.append(item)


def history(*, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_rows)
    if user_id:
        rows = [r for r in rows if r.get("user_id") == user_id]
    return rows[-limit:]
