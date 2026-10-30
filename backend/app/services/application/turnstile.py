"""Cloudflare Turnstile verification."""
from __future__ import annotations

import ipaddress

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _public_remote_ip(remote_ip: str | None) -> str | None:
    """Turnstile rejects verification if remoteip is a private/proxy address."""
    if not remote_ip:
        return None
    try:
        addr = ipaddress.ip_address(remote_ip.strip())
    except ValueError:
        return None
    if addr.is_global:
        return str(addr)
    return None


async def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    if not settings.TURNSTILE_SECRET_KEY:
        # Documented as optional: OTP + rate limits still apply.
        logger.warning("Turnstile secret not configured — skipping verification")
        return True

    if not (token or "").strip():
        return False

    payload: dict[str, str] = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token,
    }
    public_ip = _public_remote_ip(remote_ip)
    if public_ip:
        payload["remoteip"] = public_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Turnstile siteverify request failed")
        return False

    ok = bool(data.get("success"))
    if not ok:
        logger.warning("Turnstile siteverify rejected: %s", data.get("error-codes"))
    return ok
