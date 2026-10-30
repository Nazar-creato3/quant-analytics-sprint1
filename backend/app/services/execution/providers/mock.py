"""Mock execution provider — default UX path for new users (Task 6)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.core.logging import get_logger
from app.services.execution.providers.types import (
    AccountBalance,
    Balance,
    CancelResult,
    ConnectionResult,
    OrderResult,
    OrderSide,
    OrderType,
    Position,
    PositionUpdate,
    PriceTick,
    ProviderKind,
    ProviderOrder,
)
from app.services.execution.symbol_mapping import data_ticker_for, resolve_symbol_route

logger = get_logger(__name__)


class MockExecutionProvider:
    kind = ProviderKind.MOCK

    def __init__(self, *, user_id: str | None = None) -> None:
        self._user_id = user_id
        self._positions: dict[str, Position] = {}
        self._orders: list[ProviderOrder] = []
        self._cash_usd = 100_000.0

    async def connect(self, credentials: dict[str, Any]) -> ConnectionResult:
        return ConnectionResult(
            ok=True,
            provider=ProviderKind.MOCK,
            account_display="Demo portfolio ($100,000)",
            meta={"mode": "mock"},
        )

    async def get_account_balance(self) -> AccountBalance:
        deployed = 0.0
        for p in self._positions.values():
            px = p.mark_price if p.mark_price is not None else p.avg_entry_price
            if px is None:
                logger.warning("Mock balance skipped position without price: нет данных", symbol=p.symbol)
                continue
            deployed += p.qty * float(px)
        free = max(0.0, self._cash_usd - deployed)
        now = datetime.now(timezone.utc)
        return AccountBalance(
            balances=[
                Balance(currency="USD", free=round(free, 2), locked=round(deployed, 2), total=round(self._cash_usd, 2), usd_value=round(self._cash_usd, 2))
            ],
            total_usd=round(self._cash_usd, 2),
            as_of=now,
            mode="mock",
            source="mock_execution_provider",
        )

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def _resolve_price(self, symbol: str) -> float | None:
        route = resolve_symbol_route(symbol)
        data_sym = data_ticker_for(route.data_source_ticker)
        try:
            from app.services.market_data.client import get_latest_quote_resolved

            quote = await get_latest_quote_resolved(data_sym)
            for key in ("price", "last", "ask", "bid", "close"):
                val = quote.get(key)
                if val is not None:
                    try:
                        f = float(val)
                        if f > 0:
                            return f
                    except (TypeError, ValueError):
                        continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("Mock price lookup failed", symbol=symbol, error=str(exc))
        return None

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        order_type: OrderType = "market",
        price: float | None = None,
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        route = resolve_symbol_route(symbol)
        fill_price = price
        if order_type == "market" or not fill_price:
            fill_price = await self._resolve_price(symbol)
        if fill_price is None or fill_price <= 0:
            return OrderResult(ok=False, error="нет данных")

        notional = qty * fill_price
        now = datetime.now(timezone.utc)
        order_id = f"mock-{uuid.uuid4().hex[:12]}"
        pos_key = route.ui_symbol

        if side == "buy":
            if notional > self._cash_usd:
                return OrderResult(ok=False, error="Insufficient demo buying power")
            self._cash_usd -= notional
            existing = self._positions.get(pos_key)
            if existing:
                if existing.avg_entry_price is None:
                    return OrderResult(ok=False, error="нет данных")
                new_qty = existing.qty + qty
                avg = (existing.avg_entry_price * existing.qty + fill_price * qty) / new_qty
                self._positions[pos_key] = Position(
                    symbol=route.ui_symbol,
                    execution_symbol=route.execution_provider_ticker,
                    qty=new_qty,
                    avg_entry_price=avg,
                    mark_price=fill_price,
                    unrealized_pnl_usd=round((fill_price - avg) * new_qty, 2),
                )
            else:
                self._positions[pos_key] = Position(
                    symbol=route.ui_symbol,
                    execution_symbol=route.execution_provider_ticker,
                    qty=qty,
                    avg_entry_price=fill_price,
                    mark_price=fill_price,
                    unrealized_pnl_usd=0.0,
                )
        else:
            existing = self._positions.get(pos_key)
            if not existing or existing.qty < qty:
                return OrderResult(ok=False, error="Insufficient demo position")
            self._cash_usd += notional
            new_qty = existing.qty - qty
            if new_qty <= 1e-9:
                self._positions.pop(pos_key, None)
            else:
                avg = existing.avg_entry_price or fill_price
                self._positions[pos_key] = Position(
                    symbol=route.ui_symbol,
                    execution_symbol=route.execution_provider_ticker,
                    qty=new_qty,
                    avg_entry_price=avg,
                    mark_price=fill_price,
                    unrealized_pnl_usd=round((fill_price - avg) * new_qty, 2),
                )

        order = ProviderOrder(
            id=order_id,
            client_order_id=client_order_id,
            symbol=route.ui_symbol,
            execution_symbol=route.execution_provider_ticker,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            status="filled",
            filled_qty=qty,
            filled_price=round(fill_price, 4),
            submitted_at=now,
            filled_at=now,
            raw={"simulated": True, "provider": "mock"},
        )
        self._orders.append(order)
        logger.info("Mock order filled", symbol=symbol, side=side, qty=qty, price=fill_price)
        return OrderResult(ok=True, order=order)

    async def cancel_order(self, order_id: str) -> CancelResult:
        for o in self._orders:
            if o.id == order_id and o.status in ("pending", "submitted"):
                o.status = "cancelled"
                return CancelResult(ok=True, order_id=order_id)
        return CancelResult(ok=False, order_id=order_id, error="Order not cancellable")

    async def get_order_history(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ProviderOrder]:
        items = self._orders
        if symbol:
            sym = symbol.upper()
            items = [o for o in items if o.symbol == sym]
        return list(reversed(items[-limit:]))

    async def stream_prices(self, symbols: list[str]) -> AsyncIterator[PriceTick]:
        import asyncio

        while True:
            now = datetime.now(timezone.utc)
            for sym in symbols:
                px = await self._resolve_price(sym)
                if px:
                    route = resolve_symbol_route(sym)
                    yield PriceTick(
                        symbol=route.ui_symbol,
                        execution_symbol=route.execution_provider_ticker,
                        price=px,
                        ts=now,
                    )
            await asyncio.sleep(2.0)

    async def stream_position_updates(self) -> AsyncIterator[PositionUpdate]:
        import asyncio

        while True:
            now = datetime.now(timezone.utc)
            for p in self._positions.values():
                yield PositionUpdate(
                    symbol=p.symbol,
                    execution_symbol=p.execution_symbol,
                    qty=p.qty,
                    mark_price=p.mark_price,
                    ts=now,
                )
            await asyncio.sleep(5.0)
