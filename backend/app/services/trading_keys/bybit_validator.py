"""Bybit API key validation (Task 2)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.trading_keys.validators import ValidationResult

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_RECV_WINDOW = "5000"
_BYBIT_TESTNET_HOST = "api-testnet.bybit.com"


def _bybit_sign(api_secret: str, api_key: str, payload: str, timestamp: str) -> str:
    param_str = f"{timestamp}{api_key}{_RECV_WINDOW}{payload}"
    return hmac.new(api_secret.encode(), param_str.encode(), hashlib.sha256).hexdigest()


def _is_testnet_base(base: str) -> bool:
    return _BYBIT_TESTNET_HOST in base.lower()


def _testnet_key_mismatch_error(*, status_code: int) -> "ValidationResult":
    from app.services.trading_keys.validators import ValidationResult

    return ValidationResult(
        ok=False,
        error=(
            "Bybit testnet отклонил ключ"
            f" (HTTP {status_code}). "
            "Testnet-ключи создаются только на https://testnet.bybit.com "
            "(отдельный аккаунт и API Management). "
            "Mainnet-ключ с https://www.bybit.com не работает на api-testnet.bybit.com."
        ),
    )


def _parse_bybit_response(resp: httpx.Response, *, base: str) -> tuple[dict | None, str | None]:
    text = (resp.text or "").strip()
    if not text:
        if resp.status_code == 401 and _is_testnet_base(base):
            return None, _testnet_key_mismatch_error(status_code=resp.status_code).error
        return None, f"Bybit: пустой ответ API (HTTP {resp.status_code})"
    try:
        return resp.json(), None
    except json.JSONDecodeError:
        if resp.status_code == 401 and _is_testnet_base(base):
            return None, _testnet_key_mismatch_error(status_code=resp.status_code).error
        return None, f"Bybit: не-JSON ответ API (HTTP {resp.status_code})"


async def validate_bybit_key(
    *,
    api_key: str,
    api_secret: str,
    base_url: str | None = None,
) -> "ValidationResult":
    from app.services.trading_keys.validators import ValidationResult

    base = (base_url or getattr(settings, "BYBIT_API_BASE_URL", None) or "https://api.bybit.com").rstrip("/")
    timestamp = str(int(time.time() * 1000))
    query = "accountType=UNIFIED"
    sign = _bybit_sign(api_secret, api_key, query, timestamp)
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": sign,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{base}/v5/account/wallet-balance",
                params={"accountType": "UNIFIED"},
                headers=headers,
            )
            data, parse_error = _parse_bybit_response(resp, base=base)
            if parse_error:
                return ValidationResult(ok=False, error=parse_error)
            assert data is not None
            if resp.status_code >= 400 or int(data.get("retCode", 0)) != 0:
                msg = data.get("retMsg") or resp.text[:200]
                hint = ""
                ret_code = int(data.get("retCode", 0))
                if ret_code in (10003, 10004) or "api key" in str(msg).lower():
                    if _is_testnet_base(base):
                        hint = (
                            " Проверьте, что ключ создан на https://testnet.bybit.com, "
                            "а не на mainnet."
                        )
                    else:
                        hint = " Проверьте, что ключ создан на https://www.bybit.com (mainnet)."
                if "permission" in str(msg).lower() or ret_code in (10003, 10004):
                    hint += (
                        " Нужны Read (баланс/позиции) и Spot Trade. "
                        "Withdrawal должен быть ВЫКЛЮЧЕН."
                    )
                return ValidationResult(ok=False, error=f"Bybit: {msg}{hint}")

            # Optional: inspect API key permissions
            perm_status = "checked"
            perm_warning = None
            withdraw_allowed = False
            try:
                ts2 = str(int(time.time() * 1000))
                sign2 = _bybit_sign(api_secret, api_key, "", ts2)
                perm_resp = await client.get(
                    f"{base}/v5/user/query-api",
                    headers={
                        "X-BAPI-API-KEY": api_key,
                        "X-BAPI-SIGN": sign2,
                        "X-BAPI-TIMESTAMP": ts2,
                        "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
                    },
                )
                if perm_resp.status_code == 200:
                    perm_data = perm_resp.json()
                    if int(perm_data.get("retCode", 0)) == 0:
                        perms = (perm_data.get("result") or {}).get("permissions") or {}
                        if isinstance(perms, dict):
                            if perms.get("Withdraw") or perms.get("Wallet"):
                                withdraw_allowed = True
                                return ValidationResult(
                                    ok=False,
                                    error=(
                                        "Ключ имеет право на вывод средств. "
                                        "Создайте новый ключ БЕЗ Withdrawal — это требование безопасности Apex Intel."
                                    ),
                                    withdraw_allowed=True,
                                    permission_check_status="rejected",
                                )
            except Exception as exc:  # noqa: BLE001
                perm_warning = f"permission introspection skipped: {exc}"
                logger.debug("Bybit permission check skipped", error=str(exc))

            result = data.get("result") or {}
            total_usd = 0.0
            for acct in result.get("list") or []:
                for coin in acct.get("coin") or []:
                    total_usd += float(coin.get("usdValue") or 0)
            display = f"Bybit Unified (${total_usd:,.2f})"
            return ValidationResult(
                ok=True,
                account_display=display,
                withdraw_allowed=withdraw_allowed,
                permission_check_status=perm_status,
                permission_warning=perm_warning,
            )
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, error=f"Bybit недоступен: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(ok=False, error=str(exc))
