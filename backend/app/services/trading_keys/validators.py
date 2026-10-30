"""Validate venue credentials before persisting (Step 3)."""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass
class ValidationResult:
    ok: bool
    error: str | None = None
    account_display: str | None = None
    withdraw_allowed: bool | None = None
    permission_check_status: str = "skipped"
    permission_warning: str | None = None


async def validate_binance_key(
    *,
    api_key: str,
    api_secret: str,
    base_url: str = "https://api.binance.com",
) -> ValidationResult:
    base = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            ts_resp = await client.get(f"{base}/api/v3/time")
            ts_resp.raise_for_status()
            timestamp = int(ts_resp.json()["serverTime"])
            params = {"timestamp": timestamp, "recvWindow": 60000}
            query = urlencode(params)
            sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            signed = {**params, "signature": sig}
            acct = await client.get(
                f"{base}/api/v3/account",
                params=signed,
                headers={"X-MBX-APIKEY": api_key},
            )
            if acct.status_code >= 400:
                body = acct.json() if acct.headers.get("content-type", "").startswith("application/json") else {}
                msg = body.get("msg") if isinstance(body, dict) else acct.text
                return ValidationResult(ok=False, error=f"Binance: {msg or acct.status_code}")

            withdraw_allowed: bool | None = None
            perm_status = "skipped"
            perm_warning: str | None = None
            try:
                restr = await client.get(
                    f"{base}/sapi/v1/account/apiRestrictions",
                    params=signed,
                    headers={"X-MBX-APIKEY": api_key},
                )
                if restr.status_code == 200:
                    data = restr.json()
                    withdraw_allowed = bool(data.get("enableWithdrawals"))
                    perm_status = "checked"
                    if withdraw_allowed:
                        return ValidationResult(
                            ok=False,
                            error="Ключ имеет право на вывод средств. Пересоздайте ключ только с правом торговли.",
                            withdraw_allowed=True,
                            permission_check_status=perm_status,
                        )
            except Exception as exc:  # noqa: BLE001
                perm_warning = f"withdraw check unavailable: {exc}"
                logger.warning("Binance withdrawal permission check failed", error=str(exc))

            uid = None
            try:
                api_resp = await client.get(
                    f"{base}/sapi/v1/account/info",
                    params=signed,
                    headers={"X-MBX-APIKEY": api_key},
                )
                if api_resp.status_code == 200:
                    uid = api_resp.json().get("uid")
            except Exception:  # noqa: BLE001
                pass

            display = f"Binance UID {uid}" if uid else "Binance Spot"
            return ValidationResult(
                ok=True,
                account_display=display,
                withdraw_allowed=withdraw_allowed,
                permission_check_status=perm_status,
                permission_warning=perm_warning,
            )
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, error=f"Binance недоступен: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(ok=False, error=str(exc))


async def validate_alpaca_key(
    *,
    api_key: str,
    api_secret: str,
    base_url: str = "https://paper-api.alpaca.markets",
) -> ValidationResult:
    base = base_url.rstrip("/")
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{base}/v2/account", headers=headers)
            if resp.status_code >= 400:
                detail = resp.text[:200]
                return ValidationResult(ok=False, error=f"Alpaca: {detail or resp.status_code}")
            data = resp.json()
            acct_id = data.get("id") or data.get("account_number")
            status = data.get("status")
            display = f"Alpaca {acct_id} ({status})" if acct_id else "Alpaca account"
            return ValidationResult(ok=True, account_display=display, permission_check_status="checked")
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, error=f"Alpaca недоступен: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(ok=False, error=str(exc))


async def validate_tinkoff_token(*, token: str, sandbox: bool = True) -> ValidationResult:
    """Ask the broker which accounts this token sees and with what rights.

    Live mode: the token must see at least one open brokerage account.
    Sandbox: a sandbox account is opened (and funded) when none exists yet,
    so the paper book has somewhere to trade.
    """
    from app.services.broker.tbank_api import TBankApiError, TBankClient

    token = (token or "").strip()
    if not token:
        return ValidationResult(ok=False, error="Вставьте токен Т-Банка")
    try:
        client = TBankClient(token, sandbox=sandbox)
        accounts = await client.get_accounts()
        if sandbox and not [a for a in accounts if a.is_open]:
            account_id = await client.open_sandbox_account()
            if account_id:
                await client.sandbox_pay_in(account_id, 1_000_000)
            accounts = await client.get_accounts()
    except TBankApiError as exc:
        return ValidationResult(ok=False, error=exc.message, permission_check_status="failed")
    usable = [a for a in accounts if a.is_open and a.readable and (sandbox or a.is_brokerage)]
    if not usable:
        return ValidationResult(
            ok=False,
            error="Токен действителен, но открытых брокерских счетов по нему нет",
            permission_check_status="checked",
        )
    can_trade = any(a.can_trade for a in usable)
    names = ", ".join(a.name or "Брокерский счёт" for a in usable[:3])
    rights = "сделки разрешены" if can_trade else "только чтение"
    return ValidationResult(
        ok=True,
        account_display=f"{names} · {rights}",
        withdraw_allowed=False,  # the T-Invest API has no withdrawal methods at all
        permission_check_status="checked",
        permission_warning=None if can_trade else "read_only",
    )


async def validate_finam_secret(*, secret: str) -> ValidationResult:
    """Exchange the secret for a session and read the accounts it can see."""
    from app.services.broker.finam_api import FinamApiError, FinamClient

    secret = (secret or "").strip()
    if not secret:
        return ValidationResult(ok=False, error="Вставьте токен Финама")
    try:
        client = FinamClient(secret)
        details = await client.token_details()
        if not details.account_ids:
            return ValidationResult(ok=False, error="Токен действителен, но счетов по нему нет", permission_check_status="checked")
        await client.get_account(details.account_ids[0])
    except FinamApiError as exc:
        return ValidationResult(ok=False, error=exc.message, permission_check_status="failed")
    rights = "только чтение" if details.readonly else "сделки разрешены"
    ids = ", ".join(details.account_ids[:3])
    return ValidationResult(
        ok=True,
        account_display=f"Счёт {ids} · {rights}",
        withdraw_allowed=False,  # Trade API has no withdrawal methods
        permission_check_status="checked",
        permission_warning="read_only" if details.readonly else None,
    )


async def validate_venue_credentials(
    venue: str,
    credentials: dict[str, Any],
    *,
    account_mode: str = "live",
    provider_type: str | None = None,
) -> ValidationResult:
    v = venue.lower()
    if v == "binance":
        base = credentials.get("base_url") or (
            "https://testnet.binance.vision" if account_mode == "paper" else "https://api.binance.com"
        )
        return await validate_binance_key(
            api_key=credentials.get("api_key", ""),
            api_secret=credentials.get("api_secret", ""),
            base_url=base,
        )
    if v == "alpaca":
        base = credentials.get("base_url") or (
            "https://paper-api.alpaca.markets" if account_mode == "paper" else "https://api.alpaca.markets"
        )
        return await validate_alpaca_key(
            api_key=credentials.get("api_key", ""),
            api_secret=credentials.get("api_secret", ""),
            base_url=base,
        )
    if v in ("tinkoff", "tbank"):
        return await validate_tinkoff_token(
            token=credentials.get("token", credentials.get("api_key", "")),
            sandbox=account_mode == "paper",
        )

    from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider

    if v == TOKENIZED_EQUITY_VENUE or v in ("bybit", "mexc"):
        pt = TokenizedProvider.normalize(provider_type or credentials.get("provider_type") or v).value
        if pt == "mexc":
            from app.services.trading_keys.mexc_validator import validate_mexc_key

            return await validate_mexc_key(
                api_key=credentials.get("api_key", ""),
                api_secret=credentials.get("api_secret", ""),
                base_url=credentials.get("base_url"),
            )
        from app.core.config import settings
        from app.services.trading_keys.bybit_validator import validate_bybit_key

        base = credentials.get("base_url") or (
            "https://api-testnet.bybit.com"
            if account_mode == "paper"
            else (getattr(settings, "BYBIT_API_BASE_URL", None) or "https://api.bybit.com")
        )
        return await validate_bybit_key(
            api_key=credentials.get("api_key", ""),
            api_secret=credentials.get("api_secret", ""),
            base_url=base,
        )
    if v == "finam":
        return await validate_finam_secret(secret=credentials.get("token", credentials.get("api_key", "")))
    return ValidationResult(ok=False, error=f"Venue {venue} не поддерживается")
