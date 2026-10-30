"""Read-only T-Bank (Tinkoff) Invest portfolio snapshot."""
from __future__ import annotations

import os
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.services.integration.historical_data import _tinkoff_token, tinkoff_rpc

logger = get_logger(__name__)

_ALERT_COOLDOWN_SEC = 300
_last_alert_at: dict[str, float] = {}


async def _broker_alert(kind: str, detail: str) -> None:
    """Log + optional Telegram alert for broker auth/rate-limit failures (rate-limited)."""
    import time

    logger.error("tinkoff_broker_alert", kind=kind, detail=detail)
    now = time.monotonic()
    if now - _last_alert_at.get(kind, 0) < _ALERT_COOLDOWN_SEC:
        return
    _last_alert_at[kind] = now

    settings = get_settings()
    if not settings.telegram_configured:
        return
    try:
        from app.services.alerts.telegram import send_telegram_message

        text = f"⚠️ T-Bank broker: {kind}\n{detail[:500]}"
        await send_telegram_message(settings.TELEGRAM_CHAT_ID, text, settings=settings)
    except Exception as exc:
        logger.warning("tinkoff_telegram_alert_failed", error=str(exc))


def _classify_tinkoff_error(exc: Exception, status_code: int | None = None) -> str:
    if status_code == 401 or status_code == 403:
        return "auth_error"
    if status_code == 429:
        return "rate_limit"
    msg = str(exc).lower()
    if "401" in msg or "unauthorized" in msg or "unauthenticated" in msg:
        return "auth_error"
    if "429" in msg or "rate" in msg or "too many" in msg:
        return "rate_limit"
    return "api_error"


async def fetch_tinkoff_portfolio() -> dict[str, Any]:
    """
    Return portfolio positions + totals when TINKOFF_* token is configured.
    Raises RuntimeError when token missing; returns degraded payload on API errors.
    """
    token = _tinkoff_token()
    if not token:
        return {
            "configured": False,
            "source": "tinkoff",
            "detail": "missing TINKOFF_API_TOKEN",
            "positions": [],
            "total_amount": None,
        }

    account_id = os.getenv("TINKOFF_ACCOUNT_ID") or os.getenv("TINKOFF_ACCOUNT")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(
        **httpx_client_kwargs(foreign=False, timeout=httpx.Timeout(20.0, connect=5.0))
    ) as client:
        if not account_id:
            try:
                acc_resp = await client.post(
                    tinkoff_rpc("UsersService/GetAccounts"), headers=headers, json={}
                )
                if acc_resp.status_code in (401, 403, 429):
                    kind = _classify_tinkoff_error(Exception("GetAccounts"), acc_resp.status_code)
                    await _broker_alert(kind, f"GetAccounts HTTP {acc_resp.status_code}")
                acc_resp.raise_for_status()
                accounts = acc_resp.json().get("accounts") or []
                if accounts:
                    account_id = accounts[0].get("id")
            except httpx.HTTPStatusError as exc:
                kind = _classify_tinkoff_error(exc, exc.response.status_code)
                await _broker_alert(kind, f"GetAccounts: {exc}")
                logger.warning("Tinkoff GetAccounts failed", error=str(exc), status=exc.response.status_code)
            except Exception as exc:
                logger.warning("Tinkoff GetAccounts failed", error=str(exc))

        if not account_id:
            return {
                "configured": True,
                "source": "tinkoff",
                "detail": "no account_id (set TINKOFF_ACCOUNT_ID)",
                "positions": [],
                "total_amount": None,
            }

        try:
            resp = await client.post(
                tinkoff_rpc("OperationsService/GetPortfolio"),
                headers=headers,
                json={"account_id": account_id, "currency": "RUB"},
            )
            if resp.status_code in (401, 403, 429):
                kind = _classify_tinkoff_error(Exception("GetPortfolio"), resp.status_code)
                await _broker_alert(kind, f"GetPortfolio HTTP {resp.status_code}")
            resp.raise_for_status()
            raw = resp.json()
        except httpx.HTTPStatusError as exc:
            kind = _classify_tinkoff_error(exc, exc.response.status_code)
            await _broker_alert(kind, f"GetPortfolio: {exc}")
            logger.warning("Tinkoff GetPortfolio failed", error=str(exc), status=exc.response.status_code)
            return {
                "configured": True,
                "source": "tinkoff",
                "detail": f"api_error: {exc}",
                "account_id": account_id,
                "positions": [],
                "total_amount": None,
            }
        except Exception as exc:
            logger.warning("Tinkoff GetPortfolio failed", error=str(exc))
            return {
                "configured": True,
                "source": "tinkoff",
                "detail": f"api_error: {exc}",
                "account_id": account_id,
                "positions": [],
                "total_amount": None,
            }

    positions = []
    for pos in raw.get("positions") or []:
        positions.append(
            {
                "figi": pos.get("figi"),
                "ticker": pos.get("ticker"),
                "instrument_type": pos.get("instrumentType"),
                "quantity": _money_to_float(pos.get("quantity")),
                "average_price": _money_to_float(pos.get("averagePositionPrice")),
                "expected_yield": _money_to_float(pos.get("expectedYield")),
            }
        )

    total = raw.get("totalAmountPortfolio") or raw.get("totalAmountShares")
    return {
        "configured": True,
        "source": "tinkoff",
        "account_id": account_id,
        "positions": positions,
        "total_amount": _money_to_float(total),
        "detail": None,
    }


def _money_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        units = float(value.get("units") or 0)
        nano = float(value.get("nano") or 0)
        return units + nano / 1_000_000_000.0
    return None
