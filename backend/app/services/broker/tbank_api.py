"""T-Bank Invest REST client bound to one user token.

One client per token and per mode: ``sandbox=True`` talks to the sandbox host,
``sandbox=False`` to the production host. The platform market-data token is
never used here; every call carries the user's own token.

Contracts: https://github.com/RussianInvestments/investAPI (REST gateway over
the gRPC API). JSON in camelCase, int64 values arrive as strings, money as
``{"currency", "units", "nano"}``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

PROD_HOST = "invest-public-api.tbank.ru"
SANDBOX_HOST = "sandbox-invest-public-api.tbank.ru"
_CONTRACT = "tinkoff.public.invest.api.contract.v1"

# gRPC status codes returned by the REST gateway in the error body.
_GRPC_MESSAGES: dict[int, tuple[str, str]] = {
    3: ("invalid_argument", "Брокер отклонил запрос: неверные параметры"),
    5: ("not_found", "Брокер не нашёл счёт или инструмент"),
    7: ("permission_denied", "У токена нет прав на это действие"),
    8: ("rate_limit", "Превышен лимит запросов к брокеру, повторите через минуту"),
    9: ("failed_precondition", "Брокер не может выполнить действие сейчас"),
    13: ("internal", "Внутренняя ошибка брокера, повторите позже"),
    14: ("unavailable", "Брокер временно недоступен"),
    16: ("auth_error", "Токен недействителен или отозван"),
}


class TBankApiError(Exception):
    """Broker call failed. ``message`` is safe to show to the user (Russian)."""

    def __init__(self, kind: str, message: str, *, detail: str = "", http_status: int | None = None) -> None:
        self.kind = kind
        self.message = message
        self.detail = detail
        self.http_status = http_status
        super().__init__(f"{kind}: {message}")


def money(value: Any) -> Decimal | None:
    """MoneyValue / Quotation → Decimal. None when absent."""
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    if isinstance(value, dict):
        units = Decimal(str(value.get("units") or 0))
        nano = Decimal(int(value.get("nano") or 0)) / Decimal(1_000_000_000)
        return units + nano
    return None


def money_ccy(value: Any) -> str:
    if isinstance(value, dict) and value.get("currency"):
        return str(value["currency"]).upper()
    return "RUB"


def to_quotation(value: Decimal | float | str) -> dict[str, Any]:
    d = Decimal(str(value))
    units = int(d)  # truncates toward zero, same sign rule as the API
    nano = int(((d - units) * Decimal(1_000_000_000)).to_integral_value())
    return {"units": str(units), "nano": nano}


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class TBankAccount:
    id: str
    name: str
    type: str
    status: str
    access_level: str
    opened_date: datetime | None

    @property
    def is_open(self) -> bool:
        return self.status == "ACCOUNT_STATUS_OPEN"

    @property
    def can_trade(self) -> bool:
        return self.access_level == "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS"

    @property
    def readable(self) -> bool:
        return self.access_level in {"ACCOUNT_ACCESS_LEVEL_FULL_ACCESS", "ACCOUNT_ACCESS_LEVEL_READ_ONLY"}

    @property
    def is_brokerage(self) -> bool:
        return self.type in {"ACCOUNT_TYPE_TINKOFF", "ACCOUNT_TYPE_TINKOFF_IIS"}


@dataclass(frozen=True)
class TBankInstrument:
    figi: str
    uid: str
    ticker: str
    class_code: str
    lot: int
    currency: str
    name: str
    instrument_type: str
    min_price_increment: Decimal | None
    api_trade_available: bool
    buy_available: bool
    sell_available: bool


def _instrument_from(raw: dict[str, Any]) -> TBankInstrument:
    return TBankInstrument(
        figi=str(raw.get("figi") or ""),
        uid=str(raw.get("uid") or ""),
        ticker=str(raw.get("ticker") or "").upper(),
        class_code=str(raw.get("classCode") or ""),
        lot=max(1, int(raw.get("lot") or 1)),
        currency=str(raw.get("currency") or "rub").upper(),
        name=str(raw.get("name") or ""),
        instrument_type=str(raw.get("instrumentType") or ""),
        min_price_increment=money(raw.get("minPriceIncrement")),
        api_trade_available=bool(raw.get("apiTradeAvailableFlag")),
        buy_available=bool(raw.get("buyAvailableFlag")),
        sell_available=bool(raw.get("sellAvailableFlag")),
    )


# Instrument metadata changes rarely; cache per process across clients.
_INSTRUMENT_CACHE: dict[tuple[str, str], TBankInstrument] = {}


class TBankClient:
    def __init__(
        self,
        token: str,
        *,
        sandbox: bool,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        token = (token or "").strip()
        if not token:
            raise TBankApiError("auth_error", "Токен не задан")
        self._token = token
        self.sandbox = sandbox
        self._timeout = timeout
        self._transport = transport

    @property
    def host(self) -> str:
        return SANDBOX_HOST if self.sandbox else PROD_HOST

    def _url(self, method: str) -> str:
        return f"https://{self.host}/rest/{_CONTRACT}.{method}"

    async def call(self, method: str, body: dict[str, Any] | None = None, *, retries: int = 2) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-app-name": settings.TINKOFF_APP_NAME,
        }
        kwargs = httpx_client_kwargs(foreign=False, timeout=httpx.Timeout(self._timeout, connect=5.0))
        if self._transport is not None:
            kwargs["transport"] = self._transport
        attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(**kwargs) as client:
                    resp = await client.post(self._url(method), headers=headers, json=body or {})
            except httpx.HTTPError as exc:
                if attempt <= retries:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise TBankApiError("unavailable", "Брокер временно недоступен", detail=str(exc)[:200]) from exc
            if resp.status_code < 400:
                try:
                    return resp.json() or {}
                except ValueError as exc:
                    raise TBankApiError("internal", "Брокер вернул некорректный ответ") from exc
            err = self._error(resp)
            if err.kind in {"rate_limit", "unavailable", "internal"} and attempt <= retries:
                await asyncio.sleep(1.0 * attempt)
                continue
            logger.warning(
                "tbank_call_failed",
                method=method,
                status=resp.status_code,
                kind=err.kind,
                detail=err.detail[:200],
                sandbox=self.sandbox,
            )
            raise err

    @staticmethod
    def _error(resp: httpx.Response) -> TBankApiError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        code = body.get("code") if isinstance(body, dict) else None
        detail = ""
        if isinstance(body, dict):
            detail = " ".join(str(body.get(k) or "") for k in ("message", "description")).strip()
        if isinstance(code, int) and code in _GRPC_MESSAGES:
            kind, text = _GRPC_MESSAGES[code]
        elif resp.status_code in (401,):
            kind, text = _GRPC_MESSAGES[16]
        elif resp.status_code == 403:
            kind, text = _GRPC_MESSAGES[7]
        elif resp.status_code == 429:
            kind, text = _GRPC_MESSAGES[8]
        elif resp.status_code >= 500:
            kind, text = _GRPC_MESSAGES[14]
        else:
            kind, text = "api_error", "Брокер отклонил запрос"
        return TBankApiError(kind, text, detail=detail or resp.text[:200], http_status=resp.status_code)

    # ── accounts ────────────────────────────────────────────────────────
    async def get_accounts(self) -> list[TBankAccount]:
        raw = await self.call("UsersService/GetAccounts", {})
        out: list[TBankAccount] = []
        for a in raw.get("accounts") or []:
            out.append(
                TBankAccount(
                    id=str(a.get("id") or ""),
                    name=str(a.get("name") or ""),
                    type=str(a.get("type") or ""),
                    status=str(a.get("status") or ""),
                    access_level=str(a.get("accessLevel") or ""),
                    opened_date=parse_ts(a.get("openedDate")),
                )
            )
        return [a for a in out if a.id]

    async def open_sandbox_account(self, name: str = "Quant Analytics") -> str:
        raw = await self.call("SandboxService/OpenSandboxAccount", {"name": name})
        return str(raw.get("accountId") or "")

    async def sandbox_pay_in(self, account_id: str, amount_rub: Decimal | float) -> None:
        q = to_quotation(amount_rub)
        await self.call(
            "SandboxService/SandboxPayIn",
            {"accountId": account_id, "amount": {"currency": "rub", "units": q["units"], "nano": q["nano"]}},
        )

    # ── portfolio ───────────────────────────────────────────────────────
    async def get_portfolio(self, account_id: str) -> dict[str, Any]:
        return await self.call(
            "OperationsService/GetPortfolio",
            {"accountId": account_id, "currency": "RUB"},
        )

    async def get_positions(self, account_id: str) -> dict[str, Any]:
        return await self.call("OperationsService/GetPositions", {"accountId": account_id})

    async def iter_operations(
        self,
        account_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page_limit: int = 1000,
        max_pages: int = 200,
    ) -> AsyncIterator[dict[str, Any]]:
        """Executed operations, oldest pages last (broker order). Stops after ``max_pages``."""
        cursor: str | None = None
        for _ in range(max_pages):
            body: dict[str, Any] = {
                "accountId": account_id,
                "limit": page_limit,
                "state": "OPERATION_STATE_EXECUTED",
                "withoutCommissions": False,
                "withoutTrades": True,
                "withoutOvernights": True,
            }
            if start is not None:
                body["from"] = iso(start)
            if end is not None:
                body["to"] = iso(end)
            if cursor:
                body["cursor"] = cursor
            raw = await self.call("OperationsService/GetOperationsByCursor", body)
            for item in raw.get("items") or []:
                yield item
            if not raw.get("hasNext"):
                return
            cursor = str(raw.get("nextCursor") or "") or None
            if not cursor:
                return
        logger.warning("tbank_operations_page_cap", account_id=account_id[-4:], pages=max_pages)

    # ── instruments ─────────────────────────────────────────────────────
    async def instrument_by_ticker(self, ticker: str, class_code: str) -> TBankInstrument:
        key = (class_code.upper(), ticker.upper())
        hit = _INSTRUMENT_CACHE.get(key)
        if hit:
            return hit
        raw = await self.call(
            "InstrumentsService/GetInstrumentBy",
            {"idType": "INSTRUMENT_ID_TYPE_TICKER", "classCode": class_code.upper(), "id": ticker.upper()},
        )
        inst = _instrument_from(raw.get("instrument") or {})
        if not inst.figi and not inst.uid:
            raise TBankApiError("not_found", f"Инструмент {ticker} не найден у брокера")
        _INSTRUMENT_CACHE[key] = inst
        _INSTRUMENT_CACHE[("FIGI", inst.figi)] = inst
        return inst

    async def instrument_by_figi(self, figi: str) -> TBankInstrument:
        key = ("FIGI", figi)
        hit = _INSTRUMENT_CACHE.get(key)
        if hit:
            return hit
        raw = await self.call(
            "InstrumentsService/GetInstrumentBy",
            {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi},
        )
        inst = _instrument_from(raw.get("instrument") or {})
        if not inst.figi:
            raise TBankApiError("not_found", "Инструмент не найден у брокера")
        _INSTRUMENT_CACHE[key] = inst
        _INSTRUMENT_CACHE[(inst.class_code.upper(), inst.ticker)] = inst
        return inst

    # ── orders ──────────────────────────────────────────────────────────
    async def post_order(
        self,
        *,
        account_id: str,
        instrument_id: str,
        lots: int,
        direction: str,
        order_type: str,
        request_id: str,
        price: Decimal | None = None,
    ) -> dict[str, Any]:
        if lots < 1:
            raise TBankApiError("invalid_argument", "Количество меньше одного лота")
        body: dict[str, Any] = {
            "instrumentId": instrument_id,
            "quantity": str(int(lots)),
            "direction": direction,
            "accountId": account_id,
            "orderType": order_type,
            "orderId": request_id[:36],
        }
        if price is not None and order_type == "ORDER_TYPE_LIMIT":
            body["price"] = to_quotation(price)
        # Never retry an order placement automatically: the idempotency key
        # protects a resend, but a duplicate is still worse than a visible error.
        return await self.call("OrdersService/PostOrder", body, retries=0)

    async def get_order_state(self, account_id: str, order_id: str) -> dict[str, Any]:
        return await self.call(
            "OrdersService/GetOrderState",
            {"accountId": account_id, "orderId": order_id},
        )

    async def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        return await self.call(
            "OrdersService/CancelOrder",
            {"accountId": account_id, "orderId": order_id},
            retries=0,
        )

    async def post_stop_order(
        self,
        *,
        account_id: str,
        instrument_id: str,
        lots: int,
        direction: str,
        stop_order_type: str,
        stop_price: Decimal,
        request_id: str,
        price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Good-till-cancel stop-loss / take-profit / stop-limit on the exchange side."""
        if lots < 1:
            raise TBankApiError("invalid_argument", "Количество меньше одного лота")
        body: dict[str, Any] = {
            "instrumentId": instrument_id,
            "quantity": str(int(lots)),
            "direction": direction,
            "accountId": account_id,
            "expirationType": "STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL",
            "stopOrderType": stop_order_type,
            "stopPrice": to_quotation(stop_price),
            "orderId": request_id[:36],
        }
        if price is not None:
            body["price"] = to_quotation(price)
        return await self.call("StopOrdersService/PostStopOrder", body, retries=0)

    # ── market data / lookup ────────────────────────────────────────────
    async def last_price(self, instrument_id: str) -> Decimal | None:
        raw = await self.call("MarketDataService/GetLastPrices", {"instrumentId": [instrument_id]})
        for row in raw.get("lastPrices") or []:
            px = money(row.get("price"))
            if px is not None and px > 0:
                return px
        return None

    async def find_instrument(self, query: str) -> list[dict[str, Any]]:
        raw = await self.call(
            "InstrumentsService/FindInstrument",
            {"query": query, "apiTradeAvailableFlag": True},
        )
        return list(raw.get("instruments") or [])

    async def cash_available(self, account_id: str, currency: str = "RUB") -> Decimal:
        """Free cash in one currency: money minus what open orders have blocked."""
        raw = await self.get_positions(account_id)
        ccy = currency.lower()
        free = Decimal("0")
        for m in raw.get("money") or []:
            if str(m.get("currency") or "").lower() == ccy:
                free += money(m) or Decimal("0")
        for m in raw.get("blocked") or []:
            if str(m.get("currency") or "").lower() == ccy:
                free -= money(m) or Decimal("0")
        return free
