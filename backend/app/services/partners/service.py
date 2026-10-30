"""Partner transitions, R5 discount, and broker reconciliation.

Reward rates and the disclosure sentence are not invented. An empty contract
field stays «нет данных».
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "partners.v1"
_MISSING = "нет данных"
_STEPS = ("clicked", "account_opened", "funded", "active")
_CONFIG = Path(__file__).with_name("config.json")

_partners: dict[str, dict[str, str]] = {}
_transitions: dict[str, dict[str, Any]] = {}


def reset() -> None:
    _partners.clear()
    _transitions.clear()


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def disclosure_text() -> str:
    cfg = _cfg()
    text = cfg.get("disclosure_text")
    if not cfg.get("contract_confirmed") or text in (None, ""):
        return _MISSING
    return str(text)


def public_view() -> dict[str, Any]:
    """Offer card without a user id. Flag off keeps the path closed."""
    if not is_enabled("qa_partners"):
        return {
            "status": "off",
            "available": False,
            "disclosure": disclosure_text(),
            "ad_mark": "off",
            "link": _MISSING,
            "model_version": MODEL_VERSION,
        }
    link = next((row["link"] for row in _partners.values()), _MISSING)
    return {
        "status": "on",
        "available": True,
        "disclosure": disclosure_text(),
        "ad_mark": "off" if not is_enabled("qa_partner_ads") else _MISSING,
        "link": link,
        "model_version": MODEL_VERSION,
    }


def register_partner(*, partner_id: str, link: str) -> dict[str, str]:
    if not is_enabled("qa_partners"):
        return {"status": "off", "partner_id": partner_id}
    if "user_id" in link or "email" in link.lower():
        raise ValueError("ссылка не должна содержать данные пользователя")
    _partners[partner_id] = {"partner_id": partner_id, "link": link}
    return {"status": "on", "partner_id": partner_id, "link": link}


def record_click(*, user_id: str, partner_id: str, source: str, consent: bool) -> dict[str, Any]:
    if not is_enabled("qa_partners"):
        return {"status": "off"}
    if not consent:
        raise ValueError("нет согласия")
    partner = _partners.get(partner_id)
    if partner is None:
        return {"status": _MISSING, "link": _MISSING}
    link = partner["link"]
    if user_id and user_id in link:
        raise ValueError("ссылка не должна содержать данные пользователя")
    code = uuid4().hex[:12]
    _transitions[code] = {
        "code": code,
        "user_id": user_id,
        "partner_id": partner_id,
        "source": source,
        "at": _now(),
        "status": "clicked",
        "consent": True,
        "discount": None,
        "expected_reward": _MISSING,
        "actual_reward": _MISSING,
    }
    return {"status": "clicked", "code": code, "link": link}


def apply_broker_event(*, code: str, status: str) -> dict[str, Any]:
    """Advance one step. The broker row must name the status. No inferred fees."""
    row = _transitions.get(code)
    if row is None:
        raise KeyError(code)
    if not is_enabled("qa_partners"):
        return {"status": "off", "code": code}
    current = _STEPS.index(row["status"])
    if status not in _STEPS or _STEPS.index(status) != current + 1:
        raise ValueError(f"illegal partner status {row['status']} -> {status}")
    row["status"] = status
    if status == "funded":
        cfg = _cfg()
        row["discount"] = {
            "pct": str(Decimal(str(cfg["discount_pct"]))),
            "months": int(cfg["discount_months"]),
            "source": "Р5",
        }
    return {"code": code, "status": row["status"], "discount": row["discount"]}


def subscription_handoff(user_id: str) -> dict[str, Any]:
    """Discount for prompt 26. The subscription charge itself is not built here."""
    if not is_enabled("qa_partners"):
        return {"status": "off", "subscription": _MISSING}
    found = [row for row in _transitions.values() if row["user_id"] == user_id and row.get("discount")]
    if not found:
        return {"status": _MISSING, "subscription": _MISSING, "discount": None}
    latest = found[-1]
    return {
        "status": "готово",
        "subscription": _MISSING,
        "discount": latest["discount"],
        "code": latest["code"],
    }


def reconcile(rows: list[dict[str, str]] | None) -> dict[str, Any]:
    if rows is None:
        return {"status": _MISSING, "discrepancies": [], "csv": _MISSING}
    cfg = _cfg()
    expected = _MISSING if cfg.get("reward_rate") in (None, "") else str(cfg["reward_rate"])
    discrepancies: list[dict[str, str]] = []
    for raw in rows:
        code = str(raw.get("code") or "")
        local = _transitions.get(code)
        actual = raw.get("reward") if raw.get("reward") not in (None, "") else _MISSING
        if local is None:
            discrepancies.append({"code": code or _MISSING, "note": "нет перехода", "expected_reward": expected, "actual_reward": actual})
            continue
        local["expected_reward"] = expected
        local["actual_reward"] = actual
        remote_status = str(raw.get("status") or "")
        if remote_status and remote_status != local["status"]:
            discrepancies.append(
                {
                    "code": code,
                    "note": "статус не совпал",
                    "expected_reward": expected,
                    "actual_reward": actual,
                }
            )
    return {"status": "сверено", "discrepancies": discrepancies, "csv": export_csv(discrepancies)}


def export_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["code", "note", "expected_reward", "actual_reward"])
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "code": row.get("code") or _MISSING,
                "note": row.get("note") or _MISSING,
                "expected_reward": row.get("expected_reward") or _MISSING,
                "actual_reward": row.get("actual_reward") or _MISSING,
            }
        )
    text = buf.getvalue()
    if "user_id" in text:
        raise ValueError("выгрузка содержит идентификатор пользователя")
    return text
