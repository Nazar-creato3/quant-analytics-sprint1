"""Broker-agnostic execution interface (Task 1)."""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

from app.services.execution.providers.types import (
    AccountBalance,
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


@runtime_checkable
class ExecutionProvider(Protocol):
    """All platform execution flows MUST use this interface only."""

    kind: ProviderKind

    async def connect(self, credentials: dict[str, Any]) -> ConnectionResult: ...

    async def get_account_balance(self) -> AccountBalance: ...

    async def get_positions(self) -> list[Position]: ...

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        order_type: OrderType = "market",
        price: float | None = None,
        *,
        client_order_id: str | None = None,
    ) -> OrderResult: ...

    async def cancel_order(self, order_id: str) -> CancelResult: ...

    async def get_order_history(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ProviderOrder]: ...

    async def stream_prices(self, symbols: list[str]) -> AsyncIterator[PriceTick]: ...

    async def stream_position_updates(self) -> AsyncIterator[PositionUpdate]: ...
