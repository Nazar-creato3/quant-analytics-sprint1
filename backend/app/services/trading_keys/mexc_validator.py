"""MEXC API key validation."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.trading_keys.validators import ValidationResult

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_RECV_WINDOW = 5000


def _mexc_sign(api_secret: str, params: dict) -> dict:
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    signed["recvWindow"] = _RECV_WINDOW
    query = urlencode(sorted((k, str(v)) for k, v in signed.items()))
    signed["signature"] = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return signed


async def validate_mexc_key(
    *,
    api_key: str,
    api_secret: str,
    base_url: str | None = None,
) -> "ValidationResult":
    from app.services.trading_keys.validators import ValidationResult

    base = (base_url or getattr(settings, "MEXC_API_BASE_URL", None) or "https://api.mexc.com").rstrip("/")
    try:
        signed = _mexc_sign(api_secret, {})
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{base}/api/v3/account",
                params=signed,
                headers={"X-MEXC-APIKEY": api_key},
            )
            data = resp.json()
            if resp.status_code >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 0, "0")):
                msg = data.get("msg") if isinstance(data, dict) else resp.text[:200]
                hint = ""
                if "permission" in str(msg).lower() or "signature" in str(msg).lower():
                    hint = " Check SPOT read/trade permissions; withdrawal must be OFF."
                return ValidationResult(ok=False, error=f"MEXC: {msg}{hint}")

            stables = {"USDT", "USDC", "USD", "BUSD"}
            total_usd = 0.0
            for row in (data.get("balances") if isinstance(data, dict) else []) or []:
                ccy = str(row.get("asset", "")).upper()
                if ccy in stables:
                    total_usd += float(row.get("free") or 0) + float(row.get("locked") or 0)
            display = f"MEXC Spot (${total_usd:,.2f})"
            return ValidationResult(
                ok=True,
                account_display=display,
                withdraw_allowed=False,
                permission_check_status="checked",
            )
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, error=f"MEXC unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(ok=False, error=str(exc))
