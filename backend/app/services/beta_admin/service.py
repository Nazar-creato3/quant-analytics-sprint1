"""Beta admin roles. Live and lawyer flags stay off. Secrets are not shown."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.ops_observe.service import admin_view
from app.services.product_analytics.metrics import metrics
from app.services.qa.feature_flags import is_enabled, set_global

_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_ROLES = frozenset({"founder", "support", "analyst"})
_LOCKED = frozenset({"qa_act_live", "qa_subscription_notice", "qa_partner_ads", "qa_partners", "qa_preorder"})
LEGAL_LOCKED = _LOCKED
_actors: dict[str, dict[str, Any]] = {}
_users: dict[str, dict[str, str]] = {}
_invites: list[dict[str, str]] = []
_log: list[dict[str, str]] = []
_seat_limit: int | None = None


def reset_beta_admin() -> None:
    global _seat_limit
    _actors.clear()
    _users.clear()
    _invites.clear()
    _log.clear()
    _seat_limit = None


def register_actor_for_tests(*, actor_id: str, role: str, mfa: bool) -> None:
    _actors[actor_id] = {"role": role, "mfa": mfa}


def add_user_for_tests(*, user_id: str, status: str) -> None:
    _users[user_id] = {"id": user_id, "status": status}


def set_seat_limit_for_tests(limit: int | None) -> None:
    global _seat_limit
    _seat_limit = limit


def _pseudo(actor_id: str) -> str:
    return hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:24]


def _note(actor_id: str, action: str, result: str) -> None:
    _log.append({"actor_pseudo": _pseudo(actor_id), "action": action, "result": result})


def admin_log() -> list[dict[str, str]]:
    return [dict(row) for row in _log]


def _gate(actor_id: str, *roles: str) -> dict[str, str] | None:
    if not is_enabled("qa_beta_admin"):
        return {"status": "off"}
    actor = _actors.get(actor_id)
    if actor is None or actor.get("mfa") is not True:
        return {"status": "rejected", "reason": "mfa"}
    if actor.get("role") not in roles:
        return {"status": "rejected", "reason": "role"}
    return None


def list_users(actor_id: str) -> dict[str, Any]:
    blocked = _gate(actor_id, "founder", "support")
    if blocked:
        _note(actor_id, "list_users", blocked["status"])
        return blocked
    _note(actor_id, "list_users", "ok")
    return {"status": "ok", "users": [{"id": row["id"], "status": row["status"]} for row in _users.values()]}


def block_user(actor_id: str, user_id: str) -> dict[str, str]:
    blocked = _gate(actor_id, "founder", "support")
    if blocked:
        _note(actor_id, "block_user", blocked["status"])
        return blocked
    row = _users.get(user_id)
    if row is None:
        _note(actor_id, "block_user", "missing")
        return {"status": "rejected", "reason": _MISSING}
    row["status"] = "blocked"
    _note(actor_id, "block_user", "ok")
    return {"status": "ok", "id": user_id, "user_status": "blocked"}


def create_invite(actor_id: str) -> dict[str, str]:
    blocked = _gate(actor_id, "founder", "support")
    if blocked:
        _note(actor_id, "invite", blocked["status"])
        return blocked
    limit = _seat_limit
    if limit is None:
        raw = json.loads(_CONFIG.read_text(encoding="utf-8")).get("max_seats")
        limit = raw if isinstance(raw, int) else None
    if limit is None or len(_invites) >= limit:
        _note(actor_id, "invite", "seats")
        return {"status": "rejected", "reason": _MISSING}
    code = hashlib.sha256(f"invite:{len(_invites)}".encode()).hexdigest()[:12]
    _invites.append({"code": code})
    _note(actor_id, "invite", "ok")
    return {"status": "ok", "code": code}


def analyst_snapshot(actor_id: str) -> dict[str, Any]:
    blocked = _gate(actor_id, "founder", "support", "analyst")
    if blocked:
        _note(actor_id, "snapshot", blocked["status"])
        return blocked
    if _actors[actor_id]["role"] == "analyst":
        current = metrics()
        _note(actor_id, "snapshot", "ok")
        return {
            "status": "ok",
            "activation": current.get("activation", _MISSING),
            "funnel": current.get("funnel", _MISSING),
        }
    _note(actor_id, "snapshot", "ok")
    return {"status": "ok", "users": str(len(_users))}


def toggle_flag(actor_id: str, name: str, enabled: bool, *, confirm: bool, confirm_again: bool) -> dict[str, str]:
    blocked = _gate(actor_id, "founder", "support")
    if blocked:
        _note(actor_id, "flag", blocked["status"])
        return blocked
    if confirm is not True:
        _note(actor_id, "flag", "confirm")
        return {"status": "rejected", "reason": "confirm"}
    role = _actors[actor_id]["role"]
    if name in _LOCKED:
        if role != "founder" or confirm_again is not True:
            _note(actor_id, "flag", "locked")
            return {"status": "rejected", "reason": "role"}
        _note(actor_id, "flag", "legal")
        return {"status": "rejected", "reason": _MISSING}
    set_global(name, enabled)
    _note(actor_id, "flag", "ok")
    return {"status": "ok", "name": name, "enabled": "true" if enabled else "false"}


def system_state(actor_id: str) -> dict[str, Any]:
    blocked = _gate(actor_id, "founder", "support", "analyst")
    if blocked:
        _note(actor_id, "health", blocked["status"])
        return blocked
    view = admin_view()
    _note(actor_id, "health", "ok")
    return {
        "status": "ok",
        "services": view.get("status", _MISSING),
        "queues": _MISSING,
        "providers": _MISSING,
        "quotas": _MISSING,
        "live": False,
    }


def known_roles() -> list[str]:
    return sorted(_ROLES)
