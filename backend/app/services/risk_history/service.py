"""VaR / HHI / TWR points over time (Prompt 21)."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.services.qa.feature_flags import is_enabled

_lock = Lock()
_points: dict[str, list[dict[str, Any]]] = {}


def reset() -> None:
    with _lock:
        _points.clear()


def record_point(*, user_id: str, var_95: Any, hhi: Any, twr: Any) -> dict[str, Any]:
    if not (is_enabled("qa_digest") or is_enabled("qa_sandbox") or is_enabled("qa_personal_limits")):
        raise RuntimeError("risk_history flag off")
    row = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "var_95": var_95,
        "hhi": hhi,
        "twr": twr,
    }
    with _lock:
        _points.setdefault(user_id, []).append(row)
        hist = list(_points[user_id])
    return {"n": len(hist), "last": row}


def series(*, user_id: str) -> dict[str, Any]:
    if not (is_enabled("qa_digest") or is_enabled("qa_sandbox") or is_enabled("qa_personal_limits")):
        raise RuntimeError("risk_history flag off")
    with _lock:
        rows = list(_points.get(user_id) or [])
    if not rows:
        return {"data_status": "нет данных", "points": []}
    return {"data_status": "ok", "points": rows}
