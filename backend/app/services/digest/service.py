"""Weekly/monthly digest payload (Prompt 21). Delivery stays off until lawyer."""
from __future__ import annotations

from threading import Lock
from typing import Any

from app.services.qa.feature_flags import is_enabled

_lock = Lock()
_prefs: dict[str, dict[str, Any]] = {}


def reset() -> None:
    with _lock:
        _prefs.clear()


def _require() -> None:
    if not is_enabled("qa_digest"):
        raise RuntimeError("qa_digest off")


def set_prefs(*, user_id: str, cadence: str, channel: str) -> dict[str, Any]:
    _require()
    if cadence not in {"weekly", "monthly"}:
        raise ValueError("cadence")
    if channel not in {"email", "telegram"}:
        raise ValueError("channel")
    row = {"cadence": cadence, "channel": channel, "delivery": False}
    with _lock:
        _prefs[user_id] = row
    return {"user_id": user_id, **row}


def preview(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    _require()
    from app.services.personal_limits.service import evaluate_limits, get_limits
    from app.services.portfolio_report.service import assemble
    from app.services.risk_history.service import record_point, series

    report = assemble(user_id=user_id, mode=mode)
    first = report.get("first_screen") or {}
    record_point(user_id=user_id, var_95=first.get("var_95"), hhi=first.get("hhi"), twr=first.get("twr"))
    limits = {"data_status": "нет данных"}
    if is_enabled("qa_personal_limits"):
        limits = get_limits(user_id=user_id)
        if limits.get("limits"):
            limits = {**limits, **evaluate_limits(user_id=user_id, mode=mode)}
    with _lock:
        prefs = _prefs.get(user_id) or {"cadence": None, "channel": None, "delivery": False}
    return {
        "source": "digest",
        "user_id": user_id,
        "mode": mode,
        "changed": report.get("changed") or [],
        "first_screen": first,
        "limits": limits,
        "prefs": prefs,
        "delivery": False,
        "disclaimer": "Черновик регулярного отчёта. Канал не отправляет письма, пока флаг доставки выключен.",
        "risk_history": series(user_id=user_id),
    }
