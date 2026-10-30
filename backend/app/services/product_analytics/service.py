"""Product events in this process. No third-party collector and no personal data."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled

_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_PII = frozenset(
    {
        "email",
        "name",
        "phone",
        "token",
        "password",
        "address",
        "api_key",
        "secret",
        "authorization",
        "user_id",
        "ip",
    }
)
_ENUMS: dict[str, frozenset[str]] = {
    "venue": frozenset({"moex", "tbank", "finam", "other"}),
    "reason": frozenset({"rejected", "unavailable", "missing"}),
    "result": frozenset({"ok", "block"}),
    "mode": frozenset({"paper", "live"}),
}
_PLAN: tuple[dict[str, Any], ...] = (
    {"name": "registration", "side": "server", "properties": ()},
    {"name": "account_connect_success", "side": "server", "properties": ("venue",)},
    {"name": "account_connect_error", "side": "server", "properties": ("venue", "reason")},
    {"name": "first_report_shown", "side": "client", "properties": ()},
    {"name": "risk_view", "side": "client", "properties": ()},
    {"name": "trade_check", "side": "server", "properties": ("result",)},
    {"name": "maneuver_proposed", "side": "server", "properties": ()},
    {"name": "maneuver_viewed", "side": "client", "properties": ()},
    {"name": "maneuver_edited", "side": "client", "properties": ()},
    {"name": "maneuver_approved", "side": "server", "properties": ()},
    {"name": "maneuver_rejected", "side": "server", "properties": ()},
    {"name": "maneuver_executed", "side": "server", "properties": ("mode",)},
    {"name": "paper_live_switch", "side": "server", "properties": ("mode",)},
    {"name": "profile_questionnaire_completed", "side": "client", "properties": ()},
    {"name": "user_return", "side": "client", "properties": ()},
    {"name": "unsubscribe", "side": "server", "properties": ()},
)
_BY_NAME = {row["name"]: row for row in _PLAN}
_rows: list[dict[str, str]] = []
_consent_override: str | None = None


def reset_analytics() -> None:
    global _consent_override
    _rows.clear()
    _consent_override = None


def set_analytics_consent_for_tests(text: str | None) -> None:
    global _consent_override
    _consent_override = text


def analytics_consent_text() -> str:
    if _consent_override not in (None, ""):
        return str(_consent_override)
    raw = json.loads(_CONFIG.read_text(encoding="utf-8")).get("consent_text")
    if raw in (None, ""):
        return _MISSING
    return str(raw)


def plan() -> list[dict[str, Any]]:
    return [
        {"name": row["name"], "side": row["side"], "properties": list(row["properties"])}
        for row in _PLAN
    ]


def table_ddl() -> str:
    return (
        "CREATE TABLE product_events ("
        "id bigserial primary key, "
        "name text not null, "
        "side text not null, "
        "subject_pseudo text not null, "
        "properties jsonb not null, "
        "recorded_at timestamptz not null)"
    )


def stored_events() -> list[dict[str, str]]:
    return [dict(row) for row in _rows]


def _pseudo(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]


def _properties(spec: tuple[str, ...], properties: dict[str, Any], subject: str) -> dict[str, str] | None:
    if set(properties) & _PII:
        return None
    if set(properties) != set(spec):
        return None
    clean: dict[str, str] = {}
    for key in spec:
        value = properties[key]
        if not isinstance(value, str) or "@" in value or subject in value or len(value) > 32:
            return None
        allowed = _ENUMS.get(key)
        if allowed is not None and value not in allowed:
            return None
        clean[key] = value
    return clean


def record_event(
    *,
    name: str,
    side: str,
    subject: str,
    properties: dict[str, Any],
    consent: bool,
    do_not_track: bool,
) -> dict[str, str]:
    if not is_enabled("qa_product_analytics"):
        return {"status": "off"}
    if do_not_track:
        return {"status": "dropped", "reason": "dnt"}
    if consent is not True or analytics_consent_text() == _MISSING:
        return {"status": "dropped", "reason": "consent"}
    spec = _BY_NAME.get(name)
    if spec is None or spec["side"] != side or not subject or not isinstance(properties, dict):
        return {"status": "rejected", "reason": "schema"}
    clean = _properties(spec["properties"], properties, subject)
    if clean is None:
        return {"status": "rejected", "reason": "schema"}
    _rows.append(
        {
            "name": name,
            "side": side,
            "subject_pseudo": _pseudo(subject),
            "properties": json.dumps(clean, sort_keys=True),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    return {"status": "stored"}
