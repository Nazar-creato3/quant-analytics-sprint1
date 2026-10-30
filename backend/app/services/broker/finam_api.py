"""Finam Trade API (REST, api.finam.ru) bound to one user secret.

The user's API secret is exchanged for a JWT (POST /v1/sessions, ~15 min);
the JWT goes in ``Authorization`` without a scheme. Symbols are
``TICKER@MIC`` (SBER@MISX). Decimals arrive as ``{"value": "12.3"}`` and
money as ``{"currency_code", "units", "nano"}``.
Contracts: https://github.com/FinamWeb/finam-trade-api
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.finam.ru"
_JWT_TTL_SEC = 13 * 60  # JWT lives ~15 minutes; renew before that


class FinamApiError(Exception):
    def __init__(self, kind: str, message: str, *, detail: str = "", http_status: int | None = None) -> None:
        self.kind = kind
        self.message = message
        self.detail = detail
        self.http_status = http_status
        super().__init__(f"{kind}: {message}")


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raw = value.get("value")
        if raw in (None, ""):
            return None
        return Decimal(str(raw))
    if isinstance(value, (int, float, str)) and str(value) != "":
        return Decimal(str(value))
    return None


def money(value: Any) -> tuple[Decimal | None, str]:
    if not isinstance(value, dict):
        return None, "RUB"
    units = Decimal(str(value.get("units") or 0))
    nano = Decimal(int(value.get("nanos") or value.get("nano") or 0)) / Decimal(1_000_000_000)
    return units + nano, str(value.get("currency_code") or value.get("currencyCode") or "RUB").upper()


def bare_ticker(symbol: str) -> str:
    return (symbol or "").split("@", 1)[0].upper()


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class FinamTokenInfo:
    account_ids: tuple[str, ...]
    readonly: bool
    expires_at: datetime | None


@dataclass(frozen=True)
class FinamAsset:
    symbol: str
    ticker: str
    lot: Decimal
    min_step: int
    decimals: int
    currency: str
    name: str
    type: str


class FinamClient:
    def __init__(
        self,
        secret: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = (secret or "").strip()
        if not secret:
            raise FinamApiError("auth_error", "Токен Финама не задан")
        self._secret = secret
        self._timeout = timeout
        self._transport = transport
        self._jwt: str | None = None
        self._jwt_at = 0.0

    def _kwargs(self) -> dict[str, Any]:
        kwargs = httpx_client_kwargs(foreign=False, timeout=httpx.Timeout(self._timeout, connect=5.0))
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return kwargs

    @staticmethod
    def _error(resp: httpx.Response) -> FinamApiError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        detail = str(body.get("message") or body.get("details") or resp.text[:200]) if isinstance(body, dict) else resp.text[:200]
        if resp.status_code == 401:
            return FinamApiError("auth_error", "Токен Финама недействителен или истёк", detail=detail, http_status=401)
        if resp.status_code == 403:
            return FinamApiError("permission_denied", "У токена Финама нет прав на это действие", detail=detail, http_status=403)
        if resp.status_code == 404:
            return FinamApiError("not_found", "Финам не нашёл счёт или инструмент", detail=detail, http_status=404)
        if resp.status_code == 429:
            return FinamApiError("rate_limit", "Превышен лимит запросов к Финаму, повторите через минуту", detail=detail, http_status=429)
        if resp.status_code >= 500:
            return FinamApiError("unavailable", "Финам временно недоступен", detail=detail, http_status=resp.status_code)
        return FinamApiError("invalid_argument", "Финам отклонил запрос", detail=detail, http_status=resp.status_code)

    async def _auth(self) -> str:
        if self._jwt and time.monotonic() - self._jwt_at < _JWT_TTL_SEC:
            return self._jwt
        async with httpx.AsyncClient(**self._kwargs()) as client:
            try:
                resp = await client.post(f"{BASE_URL}/v1/sessions", json={"secret": self._secret})
            except httpx.HTTPError as exc:
                raise FinamApiError("unavailable", "Финам временно недоступен", detail=str(exc)[:200]) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        token = str((resp.json() or {}).get("token") or "")
        if not token:
            raise FinamApiError("auth_error", "Финам не выдал сессию по этому токену")
        self._jwt, self._jwt_at = token, time.monotonic()
        return token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            jwt = await self._auth()
            try:
                async with httpx.AsyncClient(**self._kwargs()) as client:
                    resp = await client.request(
                        method, f"{BASE_URL}{path}", params=params, json=json, headers={"Authorization": jwt}
                    )
            except httpx.HTTPError as exc:
                if attempt <= retries:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise FinamApiError("unavailable", "Финам временно недоступен", detail=str(exc)[:200]) from exc
            if resp.status_code == 401 and attempt <= retries:
                self._jwt = None  # session expired early: re-authenticate once
                continue
            if resp.status_code < 400:
                try:
                    return resp.json() or {}
                except ValueError as exc:
                    raise FinamApiError("internal", "Финам вернул некорректный ответ") from exc
            err = self._error(resp)
            if err.kind in {"rate_limit", "unavailable"} and attempt <= retries:
                await asyncio.sleep(1.0 * attempt)
                continue
            logger.warning("finam_call_failed", path=path.split("/accounts/")[0], status=resp.status_code, kind=err.kind)
            raise err

    # ── session / accounts ─────────────────────────────────────────────
    async def token_details(self) -> FinamTokenInfo:
        jwt = await self._auth()
        raw = await self.request("POST", "/v1/sessions/details", json={"token": jwt})
        return FinamTokenInfo(
            account_ids=tuple(str(a) for a in raw.get("account_ids") or raw.get("accountIds") or []),
            readonly=bool(raw.get("readonly")),
            expires_at=parse_ts(raw.get("expires_at") or raw.get("expiresAt")),
        )

    async def get_account(self, account_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/accounts/{account_id}")

    async def trades(self, account_id: str, start: datetime, end: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        raw = await self.request(
            "GET",
            f"/v1/accounts/{account_id}/trades",
            params={"limit": limit, "interval.start_time": iso(start), "interval.end_time": iso(end)},
        )
        return list(raw.get("trades") or [])

    async def transactions(self, account_id: str, start: datetime, end: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        raw = await self.request(
            "GET",
            f"/v1/accounts/{account_id}/transactions",
            params={"limit": limit, "interval.start_time": iso(start), "interval.end_time": iso(end)},
        )
        return list(raw.get("transactions") or [])

    # ── assets / quotes ─────────────────────────────────────────────────
    async def asset(self, symbol: str, account_id: str | None = None) -> FinamAsset:
        params = {"account_id": account_id} if account_id else None
        raw = await self.request("GET", f"/v1/assets/{symbol}", params=params)
        lot = dec(raw.get("lot_size") or raw.get("lotSize")) or Decimal("1")
        return FinamAsset(
            symbol=symbol,
            ticker=str(raw.get("ticker") or bare_ticker(symbol)).upper(),
            lot=lot if lot > 0 else Decimal("1"),
            min_step=int(raw.get("min_step") or raw.get("minStep") or 0),
            decimals=int(raw.get("decimals") or 0),
            currency=str(raw.get("quote_currency") or raw.get("quoteCurrency") or "RUB").upper(),
            name=str(raw.get("name") or ""),
            type=str(raw.get("type") or ""),
        )

    async def last_price(self, symbol: str) -> Decimal | None:
        raw = await self.request("GET", f"/v1/instruments/{symbol}/quotes/latest")
        quote = raw.get("quote") or {}
        for key in ("last", "ask", "bid"):
            px = dec(quote.get(key))
            if px is not None and px > 0:
                return px
        return None

    # ── orders ──────────────────────────────────────────────────────────
    async def place_order(self, account_id: str, order: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/v1/accounts/{account_id}/orders", json=order, retries=0)

    async def get_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/accounts/{account_id}/orders/{order_id}")

    async def place_sltp(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/v1/accounts/{account_id}/sltp-orders", json=body, retries=0)
