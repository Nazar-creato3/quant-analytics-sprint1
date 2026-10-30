"""Shared types for ExecutionProvider layer (broker-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Literal, Optional


class ProviderKind(str, Enum):
    MOCK = "mock"
    BYBIT_TOKENIZED = "bybit_tokenized"
    MEXC_TOKENIZED = "mexc_tokenized"
    # Future: ALPACA = "alpaca", IBKR = "ibkr"


OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "submitted", "filled", "partial", "cancelled", "rejected", "error"]


@dataclass
class ConnectionResult:
    ok: bool
    provider: ProviderKind
    account_display: str | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Balance:
    currency: str
    free: float
    locked: float
    total: float
    usd_value: float | None = None


@dataclass
class AccountBalance:
    balances: list[Balance]
    total_usd: float
    as_of: datetime
    mode: str = "live"
    source: str = ""


@dataclass
class Position:
    symbol: str
    execution_symbol: str
    qty: float
    avg_entry_price: float | None
    mark_price: float | None
    unrealized_pnl_usd: float | None
    side: Literal["long", "short"] = "long"


@dataclass
class ProviderOrder:
    id: str
    client_order_id: str | None
    symbol: str
    execution_symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    price: float | None
    status: OrderStatus
    filled_qty: float
    filled_price: float | None
    submitted_at: datetime
    filled_at: datetime | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    ok: bool
    order: ProviderOrder | None = None
    error: str | None = None


@dataclass
class CancelResult:
    ok: bool
    order_id: str
    error: str | None = None


@dataclass
class PriceTick:
    symbol: str
    execution_symbol: str
    price: float
    ts: datetime


@dataclass
class PositionUpdate:
    symbol: str
    execution_symbol: str
    qty: float
    mark_price: float | None
    ts: datetime
