"""Onboarding: connect capital. Numbers stay in other services; this is flow only."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from app.services.event_bus.bus import publish_event
from app.services.qa.feature_flags import is_enabled

PathName = Literal["have_account", "partner", "try_demo"]
STAGES = ("accounts", "positions", "history", "prices", "calc")
ERROR_COPY = {
    "bad_key": "Ключ не принят площадкой. Проверьте ключ и секрет и повторите.",
    "extra_rights": "У ключа есть право вывода. Создайте ключ только для торговли, без withdraw.",
    "no_history": "Истории сделок нет. Аналитика будет частичной — сначала отчёт с тем, что есть.",
    "venue_down": "Площадка сейчас недоступна. Можно подождать или открыть демо-портфель.",
    "sync_slow": "Синхронизация идёт дольше обычного. Частичный отчёт уже доступен.",
}

_lock = Lock()
_sessions: dict[str, dict[str, Any]] = {}
_funnel: list[dict[str, str]] = []


def reset() -> None:
    with _lock:
        _sessions.clear()
        _funnel.clear()


def _require() -> None:
    if not is_enabled("qa_onboarding"):
        raise RuntimeError("qa_onboarding off")


def _sid(user_id: str) -> str:
    return hashlib.sha256(f"onboard:{user_id}".encode("utf-8")).hexdigest()[:16]


def _emit(name: str, user_id: str) -> None:
    row = {"name": name, "session": _sid(user_id), "at": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _funnel.append(row)
    try:
        publish_event("onboarding.funnel", {"name": name, "session": row["session"], "user_id": "system"})
    except Exception:
        pass


def start(user_id: str, path: PathName, venue: str | None = None) -> dict[str, Any]:
    _require()
    if path not in {"have_account", "partner", "try_demo"}:
        raise ValueError("unknown path")
    if path == "partner":
        if is_enabled("qa_partners"):
            from app.services.partners.service import public_view

            body = public_view()
            body["path"] = path
            body["user_id"] = user_id
            body["reason"] = None
            body["next"] = None
            _emit("connect_started", user_id)
            return body
        body = {
            "user_id": user_id,
            "path": path,
            "available": False,
            "reason": "после Промпта 25",
            "next": None,
            "disclose": "партнёрские отношения будут указаны явно, когда путь включится",
        }
        _emit("connect_started", user_id)
        return body
    session = {
        "user_id": user_id,
        "path": path,
        "venue": (venue or "").lower() or None,
        "stage_i": 0,
        "stages_done": [],
        "error": None,
        "partial": False,
        "ready_report": False,
        "mode": "paper",
    }
    with _lock:
        _sessions[user_id] = session
    _emit("registered" if path == "try_demo" else "connect_started", user_id)
    return status(user_id)


def connect_key(
    user_id: str,
    *,
    venue: str,
    accepted: bool,
    withdraw_allowed: bool = False,
    venue_up: bool = True,
    has_history: bool = True,
) -> dict[str, Any]:
    _require()
    if not venue_up:
        return _fail(user_id, "venue_down")
    if not accepted:
        return _fail(user_id, "bad_key")
    if withdraw_allowed:
        return _fail(user_id, "extra_rights")
    with _lock:
        session = _sessions.setdefault(user_id, {"user_id": user_id, "path": "have_account", "stages_done": []})
        session["venue"] = venue.lower()
        session["error"] = None if has_history else "no_history"
        session["partial"] = not has_history
        session["key_ok"] = True
    _emit("connect_ok", user_id)
    return status(user_id)


def sync_once(user_id: str, *, slow: bool = False) -> dict[str, Any]:
    _require()
    with _lock:
        session = _sessions.get(user_id)
        if session is None:
            raise KeyError("no session")
        i = int(session.get("stage_i") or 0)
        if i < len(STAGES):
            done = list(session.get("stages_done") or [])
            done.append(STAGES[i])
            session["stages_done"] = done
            session["stage_i"] = i + 1
        if session["stage_i"] >= len(STAGES):
            session["ready_report"] = True
            session["next"] = "/portfolio-report"
        if slow:
            session["error"] = "sync_slow"
            session["partial"] = True
            session["ready_report"] = True
            session["next"] = "/portfolio-report"
        snap = dict(session)
    if snap.get("ready_report"):
        _emit("report_opened", user_id)
    return status(user_id)


def try_demo(user_id: str) -> dict[str, Any]:
    start(user_id, "try_demo")
    with _lock:
        session = _sessions[user_id]
        session["stages_done"] = list(STAGES)
        session["stage_i"] = len(STAGES)
        session["ready_report"] = True
        session["next"] = "/portfolio-report"
        session["mode"] = "paper"
        session["demo"] = True
    _emit("connect_ok", user_id)
    _emit("report_opened", user_id)
    return status(user_id)


def status(user_id: str) -> dict[str, Any]:
    _require()
    with _lock:
        session = _sessions.get(user_id)
        if session is None:
            return {"user_id": user_id, "empty": True, "paths": ["have_account", "partner", "try_demo"]}
        out = dict(session)
    err = out.get("error")
    if err:
        out["error_text"] = ERROR_COPY.get(str(err), "нет данных")
    out["stages"] = list(STAGES)
    out["empty"] = False
    return out


def funnel_snapshot() -> list[dict[str, str]]:
    with _lock:
        return [dict(r) for r in _funnel]


def _fail(user_id: str, code: str) -> dict[str, Any]:
    with _lock:
        session = _sessions.setdefault(user_id, {"user_id": user_id, "path": "have_account", "stages_done": []})
        session["error"] = code
        session["key_ok"] = False
    body = status(user_id)
    body["ok"] = False
    return body
