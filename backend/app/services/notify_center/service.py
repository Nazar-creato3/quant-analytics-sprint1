"""Notification center UX, Telegram bind, email unsub (Prompt 23). Inform only."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from app.services.event_bus.notifications import _FORBIDDEN, get_store, render
from app.services.explanations.service import filter_wording
from app.services.qa.feature_flags import is_enabled

CRITICAL = frozenset({"account.sync_failed", "risk.limit_breached", "live.near_liquidation"})
_CODE_TTL = timedelta(minutes=15)
_UNSUB_TTL = timedelta(days=7)
_lock = Lock()
_prefs: dict[str, dict[str, Any]] = {}
_codes: dict[str, tuple[str, datetime]] = {}
_tg: dict[str, str] = {}
_unsub_tokens: dict[str, tuple[str, datetime]] = {}
_unsub_users: set[str] = set()
_email_errors: list[dict[str, str]] = []
_retries: list[dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _prefs.clear()
        _codes.clear()
        _tg.clear()
        _unsub_tokens.clear()
        _unsub_users.clear()
        _email_errors.clear()
        _retries.clear()


def set_prefs(*, user_id: str, channels: list[str], types: list[str] | None, quiet_from: int | None, quiet_to: int | None) -> dict[str, Any]:
    row = {
        "channels": channels or ["in_app"],
        "types": types,
        "quiet_from": quiet_from,
        "quiet_to": quiet_to,
    }
    with _lock:
        _prefs[user_id] = row
    return prefs(user_id=user_id)


def prefs(*, user_id: str) -> dict[str, Any]:
    with _lock:
        row = _prefs.get(user_id) or {"channels": ["in_app"], "types": None, "quiet_from": None, "quiet_to": None}
    return {"user_id": user_id, **row}


def telegram_code(*, user_id: str, ttl: timedelta | None = None) -> dict[str, Any]:
    """One-time bind code from 16 cryptographic random bytes. It expires."""
    code = secrets.token_bytes(16).hex()
    expires = datetime.now(timezone.utc) + (_CODE_TTL if ttl is None else ttl)
    with _lock:
        stale = [key for key, (uid, _expires) in _codes.items() if uid == user_id]
        for key in stale:
            del _codes[key]
        _codes[code] = (user_id, expires)
    return {"code": code, "user_id": user_id, "expires_at": expires.isoformat()}


def bind_telegram(*, code: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with _lock:
        row = _codes.get(code)
        if row is None:
            return {"bound": False, "reason": "нет данных"}
        uid, expires = row
        if expires <= now:
            del _codes[code]
            return {"bound": False, "reason": "код истёк"}
        _tg[uid] = code
    return {"bound": True, "user_id": uid, "keys_stored": False}


def command(*, user_id: str, text: str, mode: str = "paper") -> dict[str, Any]:
    cmd = (text or "").strip().split()[0].lower()
    if cmd in {"/buy", "/sell", "/confirm", "/order"}:
        return {"ok": False, "text": "Подтверждение действий в боте запрещено. Бот только информирует."}
    if cmd == "/status":
        from app.services.portfolio_book.store import get_book

        n = len(get_book().positions(user_id=user_id, mode=mode))  # type: ignore[arg-type]
        body = f"Счетов/позиций в книге: {n}. Режим {mode}."
    elif cmd == "/risk":
        from app.services.risk_engine.service import compute_risk_for_user

        r = compute_risk_for_user(user_id, mode)
        body = f"VaR95 {r.get('var_95') if r.get('var_95') is not None else 'нет данных'}."
    elif cmd == "/report":
        from app.services.portfolio_report.service import assemble

        a = assemble(user_id=user_id, mode=mode)
        body = a.get("headline") or "нет данных"
    elif cmd == "/stop":
        with _lock:
            _tg.pop(user_id, None)
        body = "Отписка от Telegram-уведомлений принята."
    else:
        body = "Команды: /status /risk /report. Без ключей и без заявок."
    if filter_wording(body) or any(b in body.lower() for b in _FORBIDDEN):
        body = "Сводка недоступна в этой формулировке."
    if "key" in body.lower() or "token" in body.lower() or "секрет" in body.lower():
        raise AssertionError("secrets in telegram text")
    return {"ok": True, "text": body, "creates_order": False}


def issue_unsubscribe_token(*, user_id: str, ttl: timedelta | None = None) -> str:
    """Unsubscribe secret from cryptographic random bytes. It expires."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + (_UNSUB_TTL if ttl is None else ttl)
    with _lock:
        _unsub_tokens[token] = (user_id, expires)
    return token


def unsubscribe_email(*, token: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with _lock:
        row = _unsub_tokens.pop(token, None)
        if row is None:
            return {"unsubscribed": False, "reason": "нет данных"}
        uid, expires = row
        if expires <= now:
            return {"unsubscribed": False, "reason": "код истёк"}
        _unsub_users.add(uid)
    return {"unsubscribed": True, "user_id": uid}


def deliver(*, user_id: str, event_name: str, payload: dict[str, Any] | None = None, hour_utc: int | None = None) -> dict[str, Any]:
    payload = payload or {}
    pref = prefs(user_id=user_id)
    critical = event_name in CRITICAL
    if pref["types"] is not None and event_name not in pref["types"] and not critical:
        return {"delivered": [], "skipped": "type"}
    hour = datetime.now(timezone.utc).hour if hour_utc is None else hour_utc
    qf, qt = pref.get("quiet_from"), pref.get("quiet_to")
    quiet = False
    if qf is not None and qt is not None:
        quiet = qf <= hour < qt if qf < qt else hour >= qf or hour < qt
    if quiet and not critical:
        return {"delivered": [], "skipped": "quiet"}
    text = render(event_name, payload)
    channels = []
    store = get_store()
    if "in_app" in pref["channels"]:
        store.add(user_id, event_name, text, channel="in_app")
        channels.append("in_app")
    if "telegram" in pref["channels"] and user_id in _tg:
        channels.append("telegram")
    email_on = "email" in pref["channels"]
    with _lock:
        unsubscribed = user_id in _unsub_users
    unsub_token: str | None = None
    if email_on and not unsubscribed:
        channels.append("email")
        unsub_token = issue_unsubscribe_token(user_id=user_id)
    elif email_on:
        _email_errors.append({"user_id": user_id, "reason": "unsubscribed"})
    if critical:
        _retries.append({"user_id": user_id, "event_name": event_name, "priority": "high"})
        if "in_app" in pref["channels"]:
            store.add(user_id, event_name, text + " Повтор критичного события.", channel="in_app")
    out: dict[str, Any] = {
        "delivered": channels,
        "critical": critical,
        "retries": [r for r in _retries if r["user_id"] == user_id],
        "email_errors": [e for e in _email_errors if e.get("user_id") == user_id],
        "text": text,
    }
    if unsub_token is not None:
        out["unsubscribe_token"] = unsub_token
    return out
