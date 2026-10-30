"""YooKassa checkout + server-side payment confirmation."""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API = "https://api.yookassa.ru/v3"


def checkout_configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID.strip() and settings.YOOKASSA_SECRET_KEY.strip())


def _auth() -> tuple[str, str]:
    return settings.YOOKASSA_SHOP_ID.strip(), settings.YOOKASSA_SECRET_KEY.strip()


def _return_url() -> str:
    if settings.YOOKASSA_RETURN_URL.strip():
        return settings.YOOKASSA_RETURN_URL.strip()
    if settings.DOMAIN.strip():
        return f"https://{settings.DOMAIN.strip()}/account"
    origin = (settings.WEBAUTHN_ORIGIN or "").rstrip("/")
    if origin:
        return f"{origin}/account"
    return "http://localhost:3000/account"


async def create_checkout(user_id: str, email: str) -> dict[str, Any]:
    if not checkout_configured():
        raise RuntimeError("yookassa_not_configured")
    amount = (settings.SUBSCRIPTION_AMOUNT_RUB or "9900.00").strip()
    payload = {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": _return_url()},
        "description": "Quant Analytics — полный доступ",
        "metadata": {"user_id": user_id, "email": email},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{_API}/payments",
            json=payload,
            auth=_auth(),
            headers={"Idempotence-Key": str(uuid.uuid4())},
        )
    if resp.status_code >= 400:
        logger.warning("YooKassa checkout failed", status=resp.status_code)
        raise RuntimeError("yookassa_checkout_failed")
    data = resp.json()
    url = (data.get("confirmation") or {}).get("confirmation_url")
    if not url:
        raise RuntimeError("yookassa_missing_confirmation")
    return {
        "checkout_url": url,
        "payment_id": data.get("id"),
        "amount_rub": amount,
        "currency": "RUB",
    }


async def fetch_succeeded_payment_user_id(payment_id: str) -> str | None:
    """Confirm status with YooKassa — never trust the inbound webhook body alone."""
    if not checkout_configured() or not payment_id:
        return None
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{_API}/payments/{payment_id}", auth=_auth())
    if resp.status_code >= 400:
        logger.warning("YooKassa payment lookup failed", status=resp.status_code)
        return None
    data = resp.json()
    if data.get("status") != "succeeded":
        return None
    user_id = str((data.get("metadata") or {}).get("user_id") or "").strip()
    return user_id or None
