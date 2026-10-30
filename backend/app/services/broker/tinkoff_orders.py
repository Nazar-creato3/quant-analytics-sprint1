"""T-Bank (Tinkoff Invest) order gateway — MOEX equities, funds, bonds and currency.

Orders always use the *user's* token (never the platform market-data token).
On a real account the executor enforces its own hard limits after every
upstream sizing step: live trading switched on, instrument tradable via API,
whole lots only, order value against account equity and free cash, a daily
order count, and no short sales unless explicitly allowed.
"""
from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.broker.tbank_api import (
    TBankAccount,
    TBankApiError,
    TBankClient,
    TBankInstrument,
    money,
)
from app.services.execution.adapter import OrderRequest, OrderResult
from app.services.market_data.moex_currency import (
    is_moex_currency_ticker,
    normalize_moex_currency_symbol,
)
from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

logger = get_logger(__name__)

_DIRECTION = {"buy": "ORDER_DIRECTION_BUY", "sell": "ORDER_DIRECTION_SELL"}
_STOP_DIRECTION = {"buy": "STOP_ORDER_DIRECTION_BUY", "sell": "STOP_ORDER_DIRECTION_SELL"}
# Board order to try for a MOEX ticker: shares, funds, OFZ, corporate bonds.
_CLASS_CODES = ("TQBR", "TQTF", "TQOB", "TQCB", "TQIR", "SPBRU")
_FILLED = "EXECUTION_REPORT_STATUS_FILL"
_PARTIAL = "EXECUTION_REPORT_STATUS_PARTIALLYFILL"
_REJECTED = {"EXECUTION_REPORT_STATUS_REJECTED", "EXECUTION_REPORT_STATUS_CANCELLED"}
_POLL_ATTEMPTS = 4
_POLL_DELAY_SEC = 0.75


def is_tinkoff_routable_ticker(ticker: str) -> bool:
    """MOEX equities and CETS currency pairs share the T-Bank gateway."""
    raw = ticker.strip().upper()
    return is_moex_currency_ticker(raw) or is_moex_ticker(raw)


def _normalize_tinkoff_symbol(ticker: str) -> str:
    if is_moex_currency_ticker(ticker):
        return normalize_moex_currency_symbol(ticker)
    return normalize_moex_symbol(ticker)


def shares_to_lots(qty: float, lot: int) -> int:
    """Whole lots only, never rounding up into a bigger order than asked."""
    if lot < 1 or not math.isfinite(qty) or qty <= 0:
        return 0
    return int(Decimal(str(qty)) / Decimal(lot))


def round_to_tick(price: Decimal, tick: Decimal | None, *, side: str) -> Decimal:
    """Buy limits round down, sell limits round up: never a worse price than asked."""
    if not tick or tick <= 0:
        return price
    steps = price / tick
    mode = ROUND_DOWN if side == "buy" else ROUND_UP
    return (steps.quantize(Decimal("1"), rounding=mode) * tick).quantize(tick, rounding=ROUND_HALF_UP)


def _fmt(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", "\u00a0")


def _ccy(code: str) -> str:
    return {"RUB": "₽", "USD": "$", "EUR": "€", "CNY": "¥"}.get(code.upper(), code.upper())


def _reject(now: datetime, message: str, **raw: Any) -> OrderResult:
    return OrderResult(
        broker_order_id=None,
        status="rejected",
        filled_price=None,
        filled_qty=None,
        submitted_at=now,
        error=message,
        raw={"source": "tinkoff", **raw},
    )


async def resolve_instrument(client: TBankClient, ticker: str) -> TBankInstrument:
    sym = _normalize_tinkoff_symbol(ticker)
    if is_moex_currency_ticker(sym):
        return await client.instrument_by_ticker(sym, "CETS")
    for code in _CLASS_CODES:
        try:
            return await client.instrument_by_ticker(sym, code)
        except TBankApiError as exc:
            if exc.kind not in {"not_found", "invalid_argument"}:
                raise
    for row in await client.find_instrument(sym):
        if str(row.get("ticker") or "").upper() == sym and row.get("figi"):
            return await client.instrument_by_figi(str(row["figi"]))
    raise TBankApiError("not_found", f"Бумага {sym} не найдена у брокера")


class TinkoffExecutor:
    """Submit orders via the user's T-Bank token on the sandbox or the real account."""

    def __init__(
        self,
        token: str | None = None,
        account_id: str | None = None,
        *,
        sandbox: bool = False,
        user_id: str | None = None,
        client: TBankClient | None = None,
    ) -> None:
        self._token = (token or "").strip() or None
        self._account_id = (account_id or "").strip() or None
        self._sandbox = sandbox
        self._user_id = user_id
        self._client = client

    def _get_client(self) -> TBankClient:
        if self._client is None:
            self._client = TBankClient(self._token or "", sandbox=self._sandbox)
        return self._client

    async def _trade_account(self, client: TBankClient) -> TBankAccount:
        accounts = await client.get_accounts()
        usable = [a for a in accounts if a.is_open and a.can_trade and (self._sandbox or a.is_brokerage)]
        if self._account_id:
            usable = [a for a in usable if a.id == self._account_id]
        if not usable:
            if any(a.is_open and a.readable for a in accounts):
                raise TBankApiError(
                    "permission_denied",
                    "Токен подключён только для чтения. Для сделок выпустите токен с полным доступом",
                )
            raise TBankApiError("not_found", "Нет открытого брокерского счёта для сделок")
        # Prefer the ordinary brokerage account over an IIS.
        usable.sort(key=lambda a: 0 if a.type == "ACCOUNT_TYPE_TINKOFF" else 1)
        return usable[0]

    async def _live_guard(
        self,
        client: TBankClient,
        account: TBankAccount,
        inst: TBankInstrument,
        *,
        side: str,
        lots: int,
        price: Decimal,
    ) -> str | None:
        """Hard limits on a real account. Returns a Russian refusal or None."""
        if not settings.live_trading_unlocked:
            return "Реальная торговля на платформе выключена"
        value = price * lots * inst.lot
        portfolio = await client.get_portfolio(account.id)
        equity = money(portfolio.get("totalAmountPortfolio")) or Decimal("0")
        if equity <= 0:
            return "На счёте нет средств"
        pct_cap = Decimal(str(settings.LIVE_MAX_ORDER_PCT_OF_EQUITY))
        if pct_cap > 0 and value > equity * pct_cap / 100:
            return (
                f"Заявка на {_fmt(value)} {_ccy(inst.currency)} больше лимита "
                f"{pct_cap.normalize():f}% от счёта ({_fmt(equity * pct_cap / 100)} {_ccy(inst.currency)})"
            )
        abs_cap = Decimal(str(settings.LIVE_MAX_ORDER_RUB))
        if abs_cap > 0 and inst.currency == "RUB" and value > abs_cap:
            return f"Заявка на {_fmt(value)} ₽ больше лимита {_fmt(abs_cap)} ₽"
        held = Decimal("0")
        for p in portfolio.get("positions") or []:
            if str(p.get("figi") or "") == inst.figi or str(p.get("instrumentUid") or "") == inst.uid:
                held += money(p.get("quantity")) or Decimal("0")
        if side == "buy":
            cash = await client.cash_available(account.id, inst.currency)
            if value > cash:
                return (
                    f"Недостаточно свободных средств: нужно {_fmt(value)} {_ccy(inst.currency)}, "
                    f"доступно {_fmt(cash)} {_ccy(inst.currency)}"
                )
        elif not settings.LIVE_ALLOW_SHORT and held < lots * inst.lot:
            return "Продажа больше, чем есть на счёте: короткие продажи на реальном счёте отключены"
        if self._user_id and settings.LIVE_MAX_ORDERS_PER_DAY > 0:
            from app.utils.cache import rate_limit_check

            allowed, _ = await rate_limit_check(
                f"live_orders:{self._user_id}",
                settings.LIVE_MAX_ORDERS_PER_DAY,
                86_400,
                fail_closed=True,
            )
            if not allowed:
                return f"Достигнут дневной лимит заявок на реальном счёте ({settings.LIVE_MAX_ORDERS_PER_DAY})"
        return None

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        from app.services.execution.guard import ExecutionGate

        ExecutionGate.require_executing_intent(
            req.execution_context,
            maneuver_context=req.maneuver_context,
            manual_order_context=req.manual_order_context,
        )
        now = datetime.now(timezone.utc)
        if not self._token and self._client is None:
            return _reject(now, "Подключите счёт Т-Банка в настройках. Ключи платформы для сделок не используются", configured=False)
        side = req.side.lower()
        if side not in _DIRECTION:
            return _reject(now, f"Неизвестное направление сделки: {req.side}")
        client = self._get_client()
        try:
            inst = await resolve_instrument(client, req.ticker)
            if not inst.api_trade_available:
                return _reject(now, f"{inst.ticker}: брокер не разрешает сделки по этой бумаге через API", ticker=inst.ticker)
            if (side == "buy" and not inst.buy_available) or (side == "sell" and not inst.sell_available):
                return _reject(now, f"{inst.ticker}: брокер сейчас не принимает такие заявки", ticker=inst.ticker)
            lots = shares_to_lots(float(req.qty), inst.lot)
            if lots < 1:
                return _reject(
                    now,
                    f"{inst.ticker}: минимальная заявка — 1 лот ({inst.lot} шт.), запрошено {req.qty:g} шт.",
                    ticker=inst.ticker,
                    lot=inst.lot,
                )
            account = await self._trade_account(client)
            ref = Decimal(str(req.limit_price)) if req.limit_price else None
            if ref is None or ref <= 0:
                ref = await client.last_price(inst.uid or inst.figi)
            if ref is None or ref <= 0:
                return _reject(now, f"{inst.ticker}: нет текущей цены, заявка не отправлена", ticker=inst.ticker)
            if not self._sandbox:
                refusal = await self._live_guard(client, account, inst, side=side, lots=lots, price=ref)
                if refusal:
                    logger.warning("tbank_live_order_refused", ticker=inst.ticker, reason=refusal)
                    return _reject(now, refusal, ticker=inst.ticker, lots=lots)
            request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, req.client_order_id)) if req.client_order_id else str(uuid.uuid4())
            order_type = (req.order_type or "market").lower()
            if order_type in {"stop", "stop_limit"}:
                return await self._submit_stop(client, account, inst, req, side=side, lots=lots, request_id=request_id, now=now)
            price = None
            api_type = "ORDER_TYPE_MARKET"
            if order_type == "limit":
                api_type = "ORDER_TYPE_LIMIT"
                price = round_to_tick(ref, inst.min_price_increment, side=side)
            raw = await client.post_order(
                account_id=account.id,
                instrument_id=inst.uid or inst.figi,
                lots=lots,
                direction=_DIRECTION[side],
                order_type=api_type,
                request_id=request_id,
                price=price,
            )
            raw = await self._await_fill(client, account.id, raw, market=api_type == "ORDER_TYPE_MARKET")
        except TBankApiError as exc:
            logger.warning("tbank_order_failed", ticker=req.ticker, kind=exc.kind, detail=exc.detail[:200])
            status = "rejected" if exc.kind in {"invalid_argument", "permission_denied", "failed_precondition", "not_found"} else "error"
            return OrderResult(
                broker_order_id=None,
                status=status,
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=exc.message,
                raw={"source": "tinkoff", "kind": exc.kind},
            )

        result = self._to_result(raw, inst, now=now)
        result.raw["account_id"] = account.id
        result.raw["request_id"] = request_id
        result.raw["sandbox"] = self._sandbox
        logger.info(
            "tbank_order",
            ticker=inst.ticker,
            side=side,
            lots=lots,
            lot=inst.lot,
            status=result.status,
            sandbox=self._sandbox,
            broker_order_id=result.broker_order_id,
        )
        if result.status == "filled" and side == "buy" and not self._sandbox:
            await self._place_brackets(client, account.id, inst, req, lots=int((result.filled_qty or 0) // inst.lot))
        return result

    async def _await_fill(self, client: TBankClient, account_id: str, raw: dict[str, Any], *, market: bool) -> dict[str, Any]:
        """Market orders usually fill in milliseconds; read the final state briefly."""
        status = str(raw.get("executionReportStatus") or "")
        order_id = str(raw.get("orderId") or "")
        if not market or not order_id or status == _FILLED or status in _REJECTED:
            return raw
        for _ in range(_POLL_ATTEMPTS):
            await asyncio.sleep(_POLL_DELAY_SEC)
            try:
                state = await client.get_order_state(account_id, order_id)
            except TBankApiError:
                break
            raw = {**raw, **state}
            status = str(state.get("executionReportStatus") or "")
            if status == _FILLED or status in _REJECTED:
                break
        return raw

    @staticmethod
    def _to_result(raw: dict[str, Any], inst: TBankInstrument, *, now: datetime) -> OrderResult:
        status_raw = str(raw.get("executionReportStatus") or "")
        lots_done = int(raw.get("lotsExecuted") or 0)
        shares_done = float(lots_done * inst.lot)
        avg = money(raw.get("executedOrderPrice")) or money(raw.get("averagePositionPrice"))
        fill_price = float(avg) if avg is not None and avg > 0 else None
        if status_raw == _FILLED:
            status = "filled"
        elif status_raw in _REJECTED:
            status = "rejected"
        elif status_raw == _PARTIAL:
            status = "partially_filled"
        else:
            status = "submitted"
        commission = money(raw.get("executedCommission")) or money(raw.get("initialCommission"))
        return OrderResult(
            broker_order_id=str(raw.get("orderId") or "") or None,
            status=status,
            filled_price=fill_price,
            filled_qty=shares_done if lots_done else None,
            submitted_at=now,
            filled_at=now if status == "filled" else None,
            error=str(raw.get("message") or status_raw) if status == "rejected" else None,
            raw={
                "source": "tinkoff",
                "ticker": inst.ticker,
                "lot": inst.lot,
                "lots_requested": int(raw.get("lotsRequested") or 0),
                "lots_executed": lots_done,
                "commission": float(commission) if commission is not None else None,
                "currency": inst.currency,
                "status": status_raw,
            },
        )

    async def _submit_stop(
        self,
        client: TBankClient,
        account: TBankAccount,
        inst: TBankInstrument,
        req: OrderRequest,
        *,
        side: str,
        lots: int,
        request_id: str,
        now: datetime,
    ) -> OrderResult:
        if not req.stop_price or req.stop_price <= 0:
            return _reject(now, "Для стоп-заявки нужна стоп-цена", ticker=inst.ticker)
        stop_px = round_to_tick(Decimal(str(req.stop_price)), inst.min_price_increment, side=side)
        limit_px = None
        kind = "STOP_ORDER_TYPE_STOP_LOSS"
        if (req.order_type or "").lower() == "stop_limit":
            if not req.limit_price:
                return _reject(now, "Для стоп-лимита нужна цена исполнения", ticker=inst.ticker)
            kind = "STOP_ORDER_TYPE_STOP_LIMIT"
            limit_px = round_to_tick(Decimal(str(req.limit_price)), inst.min_price_increment, side=side)
        raw = await client.post_stop_order(
            account_id=account.id,
            instrument_id=inst.uid or inst.figi,
            lots=lots,
            direction=_STOP_DIRECTION[side],
            stop_order_type=kind,
            stop_price=stop_px,
            request_id=request_id,
            price=limit_px,
        )
        return OrderResult(
            broker_order_id=str(raw.get("stopOrderId") or "") or None,
            status="submitted",
            filled_price=None,
            filled_qty=None,
            submitted_at=now,
            raw={"source": "tinkoff", "ticker": inst.ticker, "stop_order": True, "lots": lots},
        )

    async def _place_brackets(
        self,
        client: TBankClient,
        account_id: str,
        inst: TBankInstrument,
        req: OrderRequest,
        *,
        lots: int,
    ) -> None:
        """Exchange-side stop-loss and take-profit for a filled long entry."""
        if lots < 1:
            return
        legs = (
            ("STOP_ORDER_TYPE_STOP_LOSS", req.stop_loss, "sl"),
            ("STOP_ORDER_TYPE_TAKE_PROFIT", req.take_profit, "tp"),
        )
        for kind, level, tag in legs:
            if not level or level <= 0:
                continue
            seed = f"{req.client_order_id or uuid.uuid4()}:{tag}"
            try:
                await client.post_stop_order(
                    account_id=account_id,
                    instrument_id=inst.uid or inst.figi,
                    lots=lots,
                    direction="STOP_ORDER_DIRECTION_SELL",
                    stop_order_type=kind,
                    stop_price=round_to_tick(Decimal(str(level)), inst.min_price_increment, side="sell"),
                    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, seed)),
                )
            except TBankApiError as exc:
                # The entry is filled; a missing bracket must be visible, not silent.
                logger.error("tbank_bracket_failed", ticker=inst.ticker, leg=tag, error=exc.message)


async def find_tinkoff_instrument(query: str) -> dict[str, Any] | None:
    """Lookup instrument metadata with the platform market-data token (diagnostics)."""
    from app.services.integration.historical_data import _tinkoff_token

    token = _tinkoff_token()
    if not token:
        return None
    try:
        inst = await resolve_instrument(TBankClient(token, sandbox=False), query)
    except TBankApiError as exc:
        logger.debug("FindInstrument failed", query=query, error=exc.message)
        return None
    return {
        "figi": inst.figi,
        "uid": inst.uid,
        "ticker": inst.ticker,
        "classCode": inst.class_code,
        "lot": inst.lot,
        "currency": inst.currency,
        "name": inst.name,
    }
