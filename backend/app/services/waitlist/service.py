"""Waitlist joins, one-step unsubscribe, and a preorder that cannot charge."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.qa.feature_flags import is_enabled
from app.services.subscription_billing.service import quote
from app.services.team_slack import notify_team

MODEL_VERSION = "waitlist.v1"
_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_rows: dict[str, dict[str, Any]] = {}
_notices: list[dict[str, str]] = []
_joins = 0


def reset() -> None:
    global _joins
    _rows.clear()
    _notices.clear()
    _joins = 0


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def consent_text() -> str:
    raw = _cfg().get("consent_text")
    if raw in (None, ""):
        return _MISSING
    return str(raw)


def _schedule_team_notice(kind: str, text: str) -> None:
    """Best-effort Slack via notify_team; no-op when webhooks are empty."""
    coro = notify_team("waitlist", text)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(coro)
        except (RuntimeError, OSError, ValueError):
            return
    else:
        loop.create_task(coro)


def _notice(kind: str) -> dict[str, str]:
    row = {"channel": "slack", "kind": kind, "text": "новая запись" if kind == "waitlist" else "предзаказ", "status": _MISSING}
    if _cfg().get("slack_webhook") in (None, ""):
        row["status"] = _MISSING
    _notices.append(row)
    _schedule_team_notice(kind, row["text"])
    return dict(row)


def join(*, email: str, name: str | None, broker: str, portfolio_range: str, consent: bool, honeypot: str) -> dict[str, Any]:
    global _joins
    from app.services.legal.gates import waitlist_open

    if not waitlist_open():
        return {"status": "rejected", "reason": "legal", "consent": consent_text()}
    if not is_enabled("qa_waitlist"):
        return {"status": "off"}
    if honeypot:
        return {"status": "rejected", "reason": "spam"}
    if not consent or consent_text() == _MISSING:
        return {"status": "rejected", "reason": _MISSING, "consent": _MISSING}
    if "@" not in email or " " in email:
        return {"status": "rejected", "reason": "email"}
    if _joins >= int(_cfg()["max_joins"]):
        return {"status": "rejected", "reason": "limit"}
    token = uuid4().hex
    row = {
        "id": uuid4().hex[:12],
        "email": email,
        "name": name or "",
        "broker": broker,
        "portfolio_range": portfolio_range,
        "status": "pending",
        "token": token,
        "created_at": datetime.now(timezone.utc),
        "model_version": MODEL_VERSION,
        "mail": _MISSING if _cfg().get("mail_transport") in (None, "") else str(_cfg()["mail_transport"]),
        "storage_region": _MISSING if _cfg().get("storage_region") in (None, "") else str(_cfg()["storage_region"]),
    }
    _rows[token] = row
    _joins += 1
    _notice("waitlist")
    public = dict(row)
    return public


def open_fixture(*, email: str, name: str | None, broker: str, portfolio_range: str, consent: bool, honeypot: str) -> dict[str, Any]:
    """State machine only. Does not publish a consent text and does not send mail."""
    global _joins
    if honeypot:
        return {"status": "rejected", "reason": "spam"}
    if not consent:
        return {"status": "rejected", "reason": "consent"}
    if "@" not in email or " " in email:
        return {"status": "rejected", "reason": "email"}
    if _joins >= int(_cfg()["max_joins"]):
        return {"status": "rejected", "reason": "limit"}
    token = uuid4().hex
    row = {
        "id": uuid4().hex[:12],
        "email": email,
        "name": name or "",
        "broker": broker,
        "portfolio_range": portfolio_range,
        "status": "pending",
        "token": token,
        "created_at": datetime.now(timezone.utc),
        "model_version": MODEL_VERSION,
        "mail": _MISSING,
        "storage_region": _MISSING,
        "fixture": True,
    }
    _rows[token] = row
    _joins += 1
    _notice("waitlist")
    return dict(row)


def confirm(token: str) -> dict[str, Any]:
    row = _rows.get(token)
    if row is None:
        return {"status": "rejected", "reason": _MISSING}
    if row["status"] == "unsubscribed":
        return {"status": "unsubscribed"}
    if row["status"] == "pending":
        row["status"] = "confirmed"
    return {"id": row["id"], "status": row["status"]}


def unsubscribe(token: str) -> dict[str, str]:
    row = _rows.get(token)
    if row is None:
        return {"status": "rejected", "reason": _MISSING}
    row["status"] = "unsubscribed"
    from app.services.product_analytics.service import record_event

    record_event(
        name="unsubscribe",
        side="server",
        subject=row["id"],
        properties={},
        consent=False,
        do_not_track=False,
    )
    return {"id": row["id"], "status": "unsubscribed"}


def founder_export() -> list[dict[str, str]]:
    return [
        {"id": row["id"], "email": row["email"], "status": row["status"]}
        for row in _rows.values()
    ]


def public_status() -> dict[str, str]:
    return {
        "pending": str(sum(1 for row in _rows.values() if row["status"] == "pending")),
        "confirmed": str(sum(1 for row in _rows.values() if row["status"] == "confirmed")),
        "unsubscribed": str(sum(1 for row in _rows.values() if row["status"] == "unsubscribed")),
        "consent": consent_text(),
        "storage_region": _MISSING if _cfg().get("storage_region") in (None, "") else str(_cfg()["storage_region"]),
        "preorder": "off",
    }


def notices() -> list[dict[str, str]]:
    return [dict(row) for row in _notices]


def retention_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _rows.values():
        kind = "waitlist_unsubscribed" if row.get("status") == "unsubscribed" else "waitlist_after_launch"
        created = row.get("created_at") or datetime.now(timezone.utc)
        rows.append({"id": str(row["id"]), "kind": kind, "created_at": created})
    return rows


def purge_by_ids(ids: list[str]) -> int:
    wanted = set(ids)
    removed = 0
    for token, row in list(_rows.items()):
        if str(row.get("id")) in wanted:
            del _rows[token]
            removed += 1
    return removed


def request_preorder(*, plan: str, token: str) -> dict[str, str]:
    row = _rows.get(token)
    if row is None or row["status"] != "confirmed":
        return {"status": "rejected", "reason": _MISSING, "amount": _MISSING}
    price_key = "personal_price" if plan == "personal" else "professional_price"
    amount = _cfg().get(price_key)
    price = _MISSING if amount in (None, "") else str(amount)
    sub = quote(user_id=row["id"], plan=plan if plan in {"personal", "professional"} else "personal", period="month")
    if not is_enabled("qa_preorder") or price == _MISSING:
        return {"status": "off", "amount": price, "subscription": sub["amount"], "provider": "off"}
    return {"status": "rejected", "amount": price, "subscription": sub["amount"], "provider": "off", "reason": "поставщик не выбран"}
