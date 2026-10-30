"""Subject export and deletion. Legal deadlines stay unset until sourced."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.product_analytics.service import analytics_consent_text, record_event
from app.services.qa.feature_flags import is_enabled

_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_PII = ("email", "name", "phone", "token", "address")
_profiles: dict[str, dict[str, str]] = {}
_tokens: dict[str, str] = {}
_consents: dict[str, str] = {}
_events: list[dict[str, str]] = []
_retention: list[dict[str, str]] = []
_requests: list[dict[str, str]] = []


def reset_subject_rights() -> None:
    _profiles.clear()
    _tokens.clear()
    _consents.clear()
    _events.clear()
    _retention.clear()
    _requests.clear()


def hold_for_tests(
    *,
    user_id: str,
    email: str,
    name: str,
    token: str,
    consent: str,
) -> None:
    _profiles[user_id] = {"email": email, "name": name}
    _tokens[user_id] = token
    _consents[user_id] = consent
    _events.append({"subject": user_id, "email": email, "name": name})
    _retention.append({"user_id": user_id, "email": email, "name": name, "basis": ""})


def _cfg(key: str) -> str:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8")).get(key)
    if raw in (None, ""):
        return _MISSING
    return str(raw)


def _pseudo(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]


def _stores() -> dict[str, Any]:
    return {
        "profiles": _profiles,
        "tokens": _tokens,
        "consents": _consents,
        "events": _events,
        "retention": _retention,
        "requests": _requests,
    }


def scan(needle: str) -> list[str]:
    found: list[str] = []
    for name, value in _stores().items():
        if needle and needle in json.dumps(value, ensure_ascii=False):
            found.append(name)
    return found


def export_account(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_subject_rights"):
        return {"status": "off"}
    profile = _profiles.get(user_id, {})
    _requests.append({"kind": "export", "user_pseudo": _pseudo(user_id), "deadline": _cfg("response_deadline")})
    return {
        "status": "ok",
        "format": "json",
        "email": profile.get("email", _MISSING),
        "name": profile.get("name", _MISSING),
        "consent": _consents.get(user_id, _MISSING),
        "token_present": "true" if user_id in _tokens else "false",
        "deadline": _cfg("response_deadline"),
    }


def revoke_consent(user_id: str) -> dict[str, str]:
    if not is_enabled("qa_subject_rights"):
        return {"status": "off"}
    _consents[user_id] = "revoked"
    _requests.append({"kind": "revoke", "user_pseudo": _pseudo(user_id), "deadline": _cfg("response_deadline")})
    return {"status": "ok", "consent": "revoked"}


def disconnect_token(user_id: str) -> dict[str, str]:
    if not is_enabled("qa_subject_rights"):
        return {"status": "off"}
    _tokens.pop(user_id, None)
    _requests.append({"kind": "token", "user_pseudo": _pseudo(user_id), "deadline": _cfg("response_deadline")})
    return {"status": "ok", "token": "removed", "broker_instruction": _cfg("broker_revoke_instructions")}


def delete_account(user_id: str) -> dict[str, str]:
    if not is_enabled("qa_subject_rights"):
        return {"status": "off"}
    profile = _profiles.pop(user_id, {})
    email = profile.get("email", "")
    _tokens.pop(user_id, None)
    _consents.pop(user_id, None)
    pseudo = _pseudo(user_id)
    for row in _events:
        owned = row.get("subject") == user_id or (email != "" and row.get("email") == email)
        if not owned:
            continue
        row["subject"] = pseudo
        for key in _PII:
            row.pop(key, None)
    kept: list[dict[str, str]] = []
    for row in _retention:
        if row.get("user_id") != user_id:
            kept.append(row)
            continue
        kept.append({"user_id": pseudo, "email": "", "name": "", "basis": _cfg("legal_basis"), "state": "обезличено"})
    _retention.clear()
    _retention.extend(kept)
    _requests.append({"kind": "delete", "user_pseudo": pseudo, "deadline": _cfg("response_deadline")})
    record_event(
        name="unsubscribe",
        side="server",
        subject=pseudo,
        properties={},
        consent=analytics_consent_text() != _MISSING,
        do_not_track=False,
    )
    return {
        "status": "ok",
        "backup": _cfg("backup_retention"),
        "deadline": _cfg("response_deadline"),
        "basis": _cfg("legal_basis"),
    }
