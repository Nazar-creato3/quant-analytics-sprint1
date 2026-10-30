"""User notifications from the event bus. No buy/sell language."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

_FORBIDDEN = ("купите", "продайте", "buy now", "sell now")

TEMPLATES: dict[str, str] = {
    "bot.circuit_breaker": "Автоматическая защита остановила ботов: {reason}. Позиции не менялись по вашей команде.",
    "account.sync_failed": "Синхронизация счёта {venue} не удалась. Статус: ошибка.",
    "risk.limit_breached": "Превышен лимит риска {limit}. Автоматические действия ограничены.",
    "bot.paused": "Бот {bot_id} на паузе.",
    "regime.changed": "Режим рынка сменился на {label}. Автоматические размеры могут быть пересчитаны.",
}


@dataclass
class Notification:
    id: int
    user_id: str
    event_name: str
    text: str
    read: bool
    created_at: datetime
    channel: str


@dataclass
class NotificationStore:
    _rows: list[Notification] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def add(self, user_id: str, event_name: str, text: str, channel: str = "in_app") -> Notification:
        lowered = text.lower()
        if any(bad in lowered for bad in _FORBIDDEN):
            raise ValueError("template contains forbidden trade advice")
        with self._lock:
            row = Notification(
                id=len(self._rows) + 1,
                user_id=user_id,
                event_name=event_name,
                text=text,
                read=False,
                created_at=datetime.now(timezone.utc),
                channel=channel,
            )
            self._rows.append(row)
            return row

    def for_user(self, user_id: str) -> list[Notification]:
        with self._lock:
            return [r for r in self._rows if r.user_id == user_id]

    def mark_read(self, user_id: str, notif_id: int) -> None:
        with self._lock:
            for r in self._rows:
                if r.user_id == user_id and r.id == notif_id:
                    r.read = True

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()


_STORE = NotificationStore()
_PAUSED_BOTS: set[str] = set()
_ACCOUNT_STATUS: dict[str, str] = {}
_CHAT_CONTEXT: list[str] = []
_BANNERS: list[str] = []


def get_store() -> NotificationStore:
    return _STORE


def render(event_name: str, payload: dict[str, Any]) -> str:
    tmpl = TEMPLATES.get(event_name, "Событие {name} зафиксировано.")
    return tmpl.format(
        name=event_name,
        **{k: payload.get(k, "") for k in ("reason", "venue", "limit", "bot_id", "label")},
    )


def assert_templates_safe() -> None:
    blob = " ".join(TEMPLATES.values()).lower()
    for bad in _FORBIDDEN:
        if bad in blob:
            raise AssertionError(f"forbidden phrase in templates: {bad}")


def on_bus_event(message: dict[str, Any]) -> None:
    name = str(message.get("name") or "")
    payload = message.get("payload") or {}
    user_id = str(payload.get("user_id") or "system")
    text = render(name, payload)
    _STORE.add(user_id, name, text)
    if name == "bot.circuit_breaker":
        _PAUSED_BOTS.add(str(payload.get("bot_id") or "all"))
        _BANNERS.append("bot_circuit_breaker")
        _CHAT_CONTEXT.append(text)
    if name == "account.sync_failed":
        _ACCOUNT_STATUS[str(payload.get("account_id") or "")] = "error"
    if name == "risk.limit_breached":
        _BANNERS.append("risk_limit")
    if name == "regime.changed" and payload.get("label") == "crisis":
        _PAUSED_BOTS.add("regime-crisis")
        _BANNERS.append("regime_crisis")


def circuit_state() -> dict[str, Any]:
    return {
        "paused_bots": sorted(_PAUSED_BOTS),
        "banners": list(_BANNERS),
        "account_status": dict(_ACCOUNT_STATUS),
        "chat_context": list(_CHAT_CONTEXT),
    }


def reset_side_effects() -> None:
    _PAUSED_BOTS.clear()
    _ACCOUNT_STATUS.clear()
    _CHAT_CONTEXT.clear()
    _BANNERS.clear()
    _STORE.reset()


def weekly_user_note(user_id: str) -> str:
    from app.services.behavior.service import weekly_text

    return weekly_text(user_id=user_id, mode="paper")
