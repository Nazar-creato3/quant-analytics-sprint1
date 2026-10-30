"""Finam order gateway (Moscow Exchange) with the same hard limits as T-Bank.

Finam takes the quantity in shares, which must be a multiple of the lot.
On a real account: live trading on, order value against account equity and
free cash, no short sales unless allowed, daily order count.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.broker.finam_api import FinamApiError, FinamAsset, FinamClient, bare_ticker, dec, money
from app.services.execution.adapter import OrderRequest, OrderResult

logger = get_logger(__name__)

_SIDE = {"buy": "SIDE_BUY", "sell": "SIDE_SELL"}
_FILLED = {"ORDER_STATUS_FILLED"}
_PARTIAL = {"ORDER_STATUS_PARTIALLY_FILLED"}
_DEAD = {"ORDER_STATUS_CANCELED", "ORDER_STATUS_REJECTED", "ORDER_STATUS_EXPIRED", "ORDER_STATUS_FAILED"}
_POLL_ATTEMPTS = 4
_POLL_DELAY_SEC = 0.75


def finam_symbol(ticker: str) -> str:
    raw = (ticker or "").strip().upper()
    return raw if "@" in raw else f"{raw}@MISX"


def whole_lots(qty: Decimal, lot: Decimal) -> Decimal:
    if lot <= 0 or qty <= 0:
        return Decimal("0")
    return (qty / lot).to_integral_value(rounding=ROUND_DOWN) * lot


def round_step(price: Decimal, asset: FinamAsset, *, side: str) -> Decimal:
    """min_step is in units of 10^-decimals. Buy rounds down, sell rounds up."""
    if asset.min_step <= 0:
        return price
    tick = Decimal(asset.min_step) / (Decimal(10) ** asset.decimals)
    mode = ROUND_DOWN if side == "buy" else ROUND_UP
    # quantize: the price goes out with the instrument's decimals (280.00, not 280.0 or 2.8E+2)
    return ((price / tick).to_integral_value(rounding=mode) * tick).quantize(tick)


def _client_id(seed: str | None) -> str:
    """Finam allows 20 characters; derive a stable id so a resend is the same order."""
    base = seed or datetime.now(timezone.utc).isoformat()
    return hashlib.sha1(base.encode()).hexdigest()[:20]


def _plain(value: Decimal) -> str:
    """Decimal as a plain string: 20, not 2E+1 (normalize() alone gives exponents)."""
    return format(value.normalize(), "f")


def _fmt(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _reject(now: datetime, message: str, **raw: Any) -> OrderResult:
    return OrderResult(
        broker_order_id=None, status="rejected", filled_price=None, filled_qty=None,
        submitted_at=now, error=message, raw={"source": "finam", **raw},
    )


class FinamExecutor:
    def __init__(
        self,
        secret: str | None = None,
        *,
        sandbox: bool = False,
        user_id: str | None = None,
        client: FinamClient | None = None,
    ) -> None:
        self._secret = (secret or "").strip()
        self._sandbox = sandbox  # Finam demo accounts live on the same host
        self._user_id = user_id
        self._client = client

    def _get_client(self) -> FinamClient:
        if self._client is None:
            self._client = FinamClient(self._secret)
        return self._client

    async def _account_id(self, client: FinamClient) -> str:
        details = await client.token_details()
        if details.readonly:
            raise FinamApiError("permission_denied", "Токен Финама только для чтения. Для сделок нужен токен с правом торговли")
        if not details.account_ids:
            raise FinamApiError("not_found", "По токену Финама нет счетов")
        return details.account_ids[0]

    async def _live_guard(
        self, client: FinamClient, account_id: str, asset: FinamAsset, *, side: str, qty: Decimal, price: Decimal
    ) -> str | None:
        if not settings.live_trading_unlocked:
            return "Реальная торговля на платформе выключена"
        account = await client.get_account(account_id)
        equity = dec(account.get("equity")) or Decimal("0")
        if equity <= 0:
            return "На счёте нет средств"
        value = qty * price
        pct = Decimal(str(settings.LIVE_MAX_ORDER_PCT_OF_EQUITY))
        if pct > 0 and value > equity * pct / 100:
            return f"Заявка на {_fmt(value)} ₽ больше лимита {pct.normalize():f}% от счёта ({_fmt(equity * pct / 100)} ₽)"
        cap = Decimal(str(settings.LIVE_MAX_ORDER_RUB))
        if cap > 0 and value > cap:
            return f"Заявка на {_fmt(value)} ₽ больше лимита {_fmt(cap)} ₽"
        held = sum(
            (dec(p.get("quantity")) or Decimal("0"))
            for p in account.get("positions") or []
            if bare_ticker(str(p.get("symbol") or "")) == asset.ticker
        )
        if side == "buy":
            cash = Decimal("0")
            for c in account.get("cash") or []:
                amount, ccy = money(c)
                if ccy == asset.currency and amount is not None:
                    cash += amount
            if value > cash:
                return f"Недостаточно свободных средств: нужно {_fmt(value)} ₽, доступно {_fmt(cash)} ₽"
        elif not settings.LIVE_ALLOW_SHORT and held < qty:
            return "Продажа больше, чем есть на счёте: короткие продажи на реальном счёте отключены"
        if self._user_id and settings.LIVE_MAX_ORDERS_PER_DAY > 0:
            from app.utils.cache import rate_limit_check

            allowed, _ = await rate_limit_check(
                f"live_orders:{self._user_id}", settings.LIVE_MAX_ORDERS_PER_DAY, 86_400, fail_closed=True
            )
            if not allowed:
                return f"Достигнут дневной лимит заявок на реальном счёте ({settings.LIVE_MAX_ORDERS_PER_DAY})"
        return None

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        from app.services.execution.guard import ExecutionGate

        ExecutionGate.require_executing_intent(
            req.execution_context, maneuver_context=req.maneuver_context, manual_order_context=req.manual_order_context
        )
        now = datetime.now(timezone.utc)
        side = req.side.lower()
        if side not in _SIDE:
            return _reject(now, f"Неизвестное направление сделки: {req.side}")
        if not self._secret and self._client is None:
            return _reject(now, "Подключите счёт Финама в настройках")
        client = self._get_client()
        symbol = finam_symbol(req.ticker)
        try:
            account_id = await self._account_id(client)
            asset = await client.asset(symbol, account_id)
            qty = whole_lots(Decimal(str(req.qty)), asset.lot)
            if qty <= 0:
                return _reject(now, f"{asset.ticker}: минимальная заявка — 1 лот ({asset.lot.normalize():f} шт.)", ticker=asset.ticker)
            ref = Decimal(str(req.limit_price)) if req.limit_price else await client.last_price(symbol)
            if ref is None or ref <= 0:
                return _reject(now, f"{asset.ticker}: нет текущей цены, заявка не отправлена", ticker=asset.ticker)
            if not self._sandbox:
                refusal = await self._live_guard(client, account_id, asset, side=side, qty=qty, price=ref)
                if refusal:
                    logger.warning("finam_live_order_refused", ticker=asset.ticker, reason=refusal)
                    return _reject(now, refusal, ticker=asset.ticker)
            otype = (req.order_type or "market").lower()
            order: dict[str, Any] = {
                "account_id": account_id,
                "symbol": symbol,
                "quantity": {"value": _plain(qty)},
                "side": _SIDE[side],
                "time_in_force": "TIME_IN_FORCE_DAY",
                "client_order_id": _client_id(req.client_order_id),
            }
            if otype == "limit":
                order["type"] = "ORDER_TYPE_LIMIT"
                order["limit_price"] = {"value": str(round_step(ref, asset, side=side))}
            elif otype in {"stop", "stop_limit"}:
                if not req.stop_price:
                    return _reject(now, "Для стоп-заявки нужна стоп-цена", ticker=asset.ticker)
                order["type"] = "ORDER_TYPE_STOP" if otype == "stop" else "ORDER_TYPE_STOP_LIMIT"
                order["stop_price"] = {"value": str(round_step(Decimal(str(req.stop_price)), asset, side=side))}
                order["stop_condition"] = "STOP_CONDITION_LAST_UP" if side == "buy" else "STOP_CONDITION_LAST_DOWN"
                if otype == "stop_limit":
                    if not req.limit_price:
                        return _reject(now, "Для стоп-лимита нужна цена исполнения", ticker=asset.ticker)
                    order["limit_price"] = {"value": str(round_step(Decimal(str(req.limit_price)), asset, side=side))}
            else:
                order["type"] = "ORDER_TYPE_MARKET"
            state = await client.place_order(account_id, order)
            if order["type"] == "ORDER_TYPE_MARKET":
                state = await self._await_fill(client, account_id, state)
        except FinamApiError as exc:
            logger.warning("finam_order_failed", ticker=req.ticker, kind=exc.kind)
            status = "rejected" if exc.kind in {"invalid_argument", "permission_denied", "not_found"} else "error"
            return OrderResult(
                broker_order_id=None, status=status, filled_price=None, filled_qty=None,
                submitted_at=now, error=exc.message, raw={"source": "finam", "kind": exc.kind},
            )
        result = self._to_result(state, asset, now=now, ref=ref)
        result.raw.update({"account_id": account_id, "symbol": symbol, "sandbox": self._sandbox})
        if result.status == "filled" and side == "buy" and not self._sandbox and (req.stop_loss or req.take_profit):
            await self._brackets(client, account_id, asset, req, qty=Decimal(str(result.filled_qty or 0)))
        logger.info("finam_order", ticker=asset.ticker, side=side, qty=str(qty), status=result.status)
        return result

    async def _await_fill(self, client: FinamClient, account_id: str, state: dict[str, Any]) -> dict[str, Any]:
        order_id = str(state.get("order_id") or "")
        for _ in range(_POLL_ATTEMPTS):
            status = str(state.get("status") or "")
            if not order_id or status in _FILLED or status in _DEAD:
                break
            await asyncio.sleep(_POLL_DELAY_SEC)
            try:
                state = await client.get_order(account_id, order_id)
            except FinamApiError:
                break
        return state

    @staticmethod
    def _to_result(state: dict[str, Any], asset: FinamAsset, *, now: datetime, ref: Decimal) -> OrderResult:
        status_raw = str(state.get("status") or "")
        executed = dec(state.get("executed_quantity")) or Decimal("0")
        if status_raw in _FILLED:
            status = "filled"
        elif status_raw in _PARTIAL:
            status = "partially_filled"
        elif status_raw in _DEAD:
            status = "filled" if executed > 0 else "rejected"
        else:
            status = "submitted"
        desc = state.get("status_description")
        if isinstance(desc, dict):
            desc = desc.get("value")
        # Finam's order state carries no average fill price; the reference
        # price is reported and the broker sync books the exact trade prices.
        return OrderResult(
            broker_order_id=str(state.get("order_id") or "") or None,
            status=status,
            filled_price=float(ref) if executed > 0 else None,
            filled_qty=float(executed) if executed > 0 else None,
            submitted_at=now,
            filled_at=now if status == "filled" else None,
            error=str(desc or status_raw) if status == "rejected" else None,
            raw={"source": "finam", "ticker": asset.ticker, "lot": float(asset.lot), "status": status_raw,
                 "price_is_reference": True},
        )

    async def _brackets(self, client: FinamClient, account_id: str, asset: FinamAsset, req: OrderRequest, *, qty: Decimal) -> None:
        if qty <= 0:
            return
        body: dict[str, Any] = {
            "account_id": account_id,
            "symbol": asset.symbol,
            "side": "SIDE_SELL",
            "valid_before": "VALID_BEFORE_GOOD_TILL_CANCEL",
            "client_order_id": _client_id(f"{req.client_order_id}:sltp"),
        }
        if req.stop_loss:
            body["quantity_sl"] = {"value": _plain(qty)}
            body["sl_price"] = {"value": str(round_step(Decimal(str(req.stop_loss)), asset, side="sell"))}
        if req.take_profit:
            body["quantity_tp"] = {"value": _plain(qty)}
            body["tp_price"] = {"value": str(round_step(Decimal(str(req.take_profit)), asset, side="sell"))}
        try:
            await client.place_sltp(account_id, body)
        except FinamApiError as exc:
            logger.error("finam_bracket_failed", ticker=asset.ticker, error=exc.message)
