"""Russian mobile number confirmation by SMS code (sms.ru).

Sign-in on the site is tied to a verified Russian mobile number (149-FZ
art. 10.6, KoAP 13.55). Only a keyed hash and the last four digits are
stored; the full number lives in memory while the code is sent.

Abuse limits (SMS costs money): per number 3 codes / 10 min and 6 / day,
per IP 10 / hour, 5 wrong codes burn the current code.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.utils.cache import cache_delete, cache_get, cache_set, rate_limit_check

logger = get_logger(__name__)

CODE_TTL_SEC = 600
MAX_ATTEMPTS = 5
_RU_MOBILE = re.compile(r"^79\d{9}$")


class PhoneError(Exception):
    def __init__(self, message: str, *, status: int = 400) -> None:
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Phone:
    digits: str  # 79XXXXXXXXX

    @property
    def last4(self) -> str:
        return self.digits[-4:]

    @property
    def hash(self) -> str:
        return phone_hash(self.digits)

    @property
    def masked(self) -> str:
        d = self.digits
        return f"+7 {d[1:4]} ***-**-{d[-4:-2]}-{d[-2:]}"


def normalize(raw: str) -> Phone:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    if not _RU_MOBILE.match(digits):
        raise PhoneError("Укажите российский мобильный номер в формате +7 9XX XXX-XX-XX")
    return Phone(digits)


def phone_hash(digits: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"phone:{digits}".encode(), hashlib.sha256).hexdigest()


def _code_key(h: str) -> str:
    return f"phone_code:{h}"


def _code_digest(h: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{h}:{code}".encode(), hashlib.sha256).hexdigest()


async def _limit(key: str, n: int, window: int, message: str) -> None:
    allowed, _ = await rate_limit_check(key, n, window, fail_closed=True)
    if not allowed:
        raise PhoneError(message, status=429)


async def send_code(raw_phone: str, *, ip: str) -> dict[str, Any]:
    phone = normalize(raw_phone)
    await _limit(f"sms_ip:{ip}", 10, 3600, "Слишком много запросов кода. Повторите через час.")
    await _limit(f"sms_phone10m:{phone.hash}", 3, 600, "Код уже отправлен. Повторите через 10 минут.")
    await _limit(f"sms_phoneday:{phone.hash}", 6, 86_400, "Лимит кодов на сегодня исчерпан.")
    code = f"{secrets.randbelow(900_000) + 100_000:06d}"
    await cache_set(_code_key(phone.hash), {"d": _code_digest(phone.hash, code), "n": 0}, ttl=CODE_TTL_SEC)
    await _dispatch(phone, f"Quant Analytics: код {code}. Никому не сообщайте его.")
    out: dict[str, Any] = {"sent": True, "phone": phone.masked, "ttl_sec": CODE_TTL_SEC}
    if settings.is_development and (settings.SMS_PROVIDER or "stub").lower() == "stub":
        out["dev_code"] = code
    return out


async def check_code(raw_phone: str, code: str) -> Phone:
    """Verify and consume the code. Raises PhoneError on any mismatch."""
    phone = normalize(raw_phone)
    stored = await cache_get(_code_key(phone.hash))
    if not isinstance(stored, dict) or not stored.get("d"):
        raise PhoneError("Код истёк или не запрашивался. Запросите новый.")
    attempts = int(stored.get("n") or 0) + 1
    if not hmac.compare_digest(str(stored["d"]), _code_digest(phone.hash, (code or "").strip())):
        if attempts >= MAX_ATTEMPTS:
            await cache_delete(_code_key(phone.hash))
            raise PhoneError("Слишком много неверных попыток. Запросите новый код.")
        await cache_set(_code_key(phone.hash), {"d": stored["d"], "n": attempts}, ttl=CODE_TTL_SEC)
        raise PhoneError("Неверный код")
    await cache_delete(_code_key(phone.hash))
    return phone


async def _dispatch(phone: Phone, text: str) -> None:
    provider = (settings.SMS_PROVIDER or "stub").lower()
    if provider == "smsru":
        await _send_smsru(phone, text)
        return
    if provider == "stub" and (settings.is_development or settings.QA_E2E_DEMO):
        logger.info("sms_stub", phone_last4=phone.last4)
        return
    raise PhoneError("Отправка СМС временно недоступна. Попробуйте позже.", status=503)


async def _send_smsru(phone: Phone, text: str) -> None:
    if not settings.SMSRU_API_KEY:
        raise PhoneError("Отправка СМС временно недоступна. Попробуйте позже.", status=503)
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=15.0)) as client:
            resp = await client.post(
                "https://sms.ru/sms/send",
                data={"api_id": settings.SMSRU_API_KEY, "to": phone.digits, "msg": text, "json": 1},
            )
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("smsru_failed", error=str(exc)[:200])
        raise PhoneError("Не удалось отправить СМС. Попробуйте позже.", status=503) from exc
    row = (body.get("sms") or {}).get(phone.digits) or {}
    if body.get("status") != "OK" or row.get("status") != "OK":
        logger.error(
            "smsru_rejected",
            status=body.get("status"),
            code=row.get("status_code") or body.get("status_code"),
            text=str(row.get("status_text") or body.get("status_text") or "")[:120],
        )
        raise PhoneError("Не удалось отправить СМС на этот номер. Проверьте номер.", status=502)
    logger.info("sms_sent", phone_last4=phone.last4, balance=body.get("balance"))
