"""Subscription state for prompt 26.

Prices stay in config. Empty prices are «нет данных». This module does not
call YooKassa. Fixture events carry their own signature; that is not the
live notification scheme.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.partners.service import subscription_handoff
from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "subscription_billing.v1"
_MISSING = "нет данных"
_PLANS = {"personal", "professional"}
_PERIODS = {"month", "year"}
_CONFIG = Path(__file__).with_name("config.json")

_accounts: dict[str, dict[str, Any]] = {}
_events: dict[str, dict[str, Any]] = {}
_funnel: list[dict[str, str]] = []


def reset() -> None:
    _accounts.clear()
    _events.clear()
    _funnel.clear()


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _price_key(plan: str, period: str) -> str:
    return f"{plan}_{period}"


def listed_price(plan: str, period: str) -> str:
    if plan not in _PLANS or period not in _PERIODS:
        return _MISSING
    raw = _cfg().get(_price_key(plan, period))
    if raw in (None, ""):
        return _MISSING
    return format(Decimal(str(raw)), "f")


def quote(*, user_id: str, plan: str, period: str) -> dict[str, Any]:
    """Price from config only. Partner discount does not invent a missing price."""
    amount = listed_price(plan, period)
    handoff = subscription_handoff(user_id)
    discount = handoff.get("discount") if is_enabled("qa_partners") else None
    if amount != _MISSING and discount:
        pct = Decimal(str(discount["pct"]))
        amount = format(Decimal(amount) * (Decimal(1) - pct), "f")
    notice = _MISSING
    if is_enabled("qa_subscription_notice"):
        notice = _MISSING
    license_key = "license_personal" if plan == "personal" else "license_professional"
    license_text = _cfg().get(license_key) or _MISSING
    from app.services.legal.gates import payment_open

    # Fail-closed: drafts / empty rkn.notice keep payment_open() false.
    billed = is_enabled("qa_subscription") and payment_open()
    checkout = (
        "on"
        if is_enabled("qa_payment") and payment_open() and amount != _MISSING
        else "off"
    )
    return {
        "status": "on" if billed else "off",
        "plan": plan,
        "period": period,
        "amount": amount,
        "currency": str(_cfg().get("currency") or _MISSING),
        "discount": discount if discount else None,
        "checkout": checkout,
        "notice": notice,
        "license": license_text if license_text not in (None, "") else _MISSING,
        "model_version": MODEL_VERSION,
    }


def access_for(status: str) -> dict[str, Any]:
    """Read or full paper access. Live stays closed."""
    if not is_enabled("qa_subscription"):
        return {"status": "off", "mode": "off", "live": False}
    if status == "paid":
        mode = "full"
    elif status in {"trial", "overdue", "cancelled"}:
        mode = "read"
    else:
        mode = _MISSING
    return {"status": status, "mode": mode, "live": False}


def open_trial(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_subscription"):
        return {"status": "off", "user_id": user_id}
    row = {
        "user_id": user_id,
        "status": "trial",
        "plan": None,
        "autopay": False,
        "consent": False,
        "card_bound": False,
        "access": access_for("trial"),
    }
    _accounts[user_id] = row
    _funnel.append({"name": "subscription.trial", "user_id": user_id})
    return dict(row)


def sign_fixture(*, secret: str, event_id: str, status: str) -> str:
    payload = f"{event_id}.{status}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def apply_fixture(
    *,
    user_id: str,
    event_id: str,
    status: str,
    signature: str,
    secret: str,
    plan: str = "personal",
    period: str = "month",
    consent: bool = False,
    autopay: bool = False,
    fixture_amount: str | None = None,
) -> dict[str, Any]:
    """Apply one fixture payment. A repeated event id does not change state again.

    `fixture_amount` is the sandbox payload. It is not written into the price config.
    """
    if not is_enabled("qa_subscription"):
        return {"status": "off"}
    expected = sign_fixture(secret=secret, event_id=event_id, status=status)
    if not hmac.compare_digest(expected, signature):
        return {"status": "rejected", "reason": "подпись"}
    if event_id in _events:
        return dict(_events[event_id])
    row = _accounts.get(user_id) or open_trial(user_id)
    if autopay and not consent:
        raise ValueError("нет согласия на повторное списание")
    if status == "succeeded":
        if fixture_amount in (None, ""):
            result = {"status": "rejected", "reason": _MISSING, "event_id": event_id}
            _events[event_id] = result
            return dict(result)
        row["status"] = "paid"
        row["plan"] = plan
        row["period"] = period
        row["fixture_amount"] = str(fixture_amount)
        row["autopay"] = bool(autopay and consent)
        row["consent"] = bool(consent)
        row["card_bound"] = True
        _funnel.append({"name": "subscription.paid", "user_id": user_id})
    elif status == "canceled":
        _funnel.append({"name": "subscription.failed", "user_id": user_id})
    elif status == "refund":
        row["status"] = "cancelled"
        row["autopay"] = False
        _funnel.append({"name": "subscription.refund", "user_id": user_id})
    else:
        result = {"status": "rejected", "reason": _MISSING, "event_id": event_id}
        _events[event_id] = result
        return dict(result)
    row["access"] = access_for(row["status"])
    _accounts[user_id] = row
    result = {"status": row["status"], "event_id": event_id, "access": row["access"]}
    _events[event_id] = result
    return dict(result)


def cancel(user_id: str) -> dict[str, Any]:
    """One call stops the subscription and further charges."""
    row = _accounts.get(user_id)
    if row is None:
        raise KeyError(user_id)
    if not is_enabled("qa_subscription"):
        return {"status": "off"}
    row["status"] = "cancelled"
    row["autopay"] = False
    row["access"] = access_for("cancelled")
    _funnel.append({"name": "subscription.cancelled", "user_id": user_id})
    return dict(row)


def unbind_card(user_id: str) -> dict[str, Any]:
    row = _accounts.get(user_id)
    if row is None:
        raise KeyError(user_id)
    row["card_bound"] = False
    row["autopay"] = False
    return dict(row)


def charge_due(user_id: str) -> dict[str, str]:
    row = _accounts.get(user_id)
    if row is None or not row.get("autopay") or not row.get("card_bound"):
        return {"status": "off", "reason": "карта отвязана" if row and not row.get("card_bound") else _MISSING}
    if listed_price(str(row.get("plan") or ""), "month") == _MISSING:
        return {"status": _MISSING, "reason": _MISSING}
    return {"status": "off", "reason": "живой магазин не подключён"}


def account(user_id: str) -> dict[str, Any] | None:
    row = _accounts.get(user_id)
    return dict(row) if row else None


def funnel_names() -> list[str]:
    return [row["name"] for row in _funnel]
