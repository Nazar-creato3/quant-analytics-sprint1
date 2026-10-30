"""Manual order module schemas (spec B.1–B.3)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

OrderSide = Literal["buy", "sell"]
OrderType = Literal[
    "market",
    "limit",
    "stop",
    "stop_limit",
    "oco",
    "trailing_stop",
]
TimeInForce = Literal["gtc", "ioc", "fok", "day", "gtd"]
OrderStatus = Literal[
    "pending",
    "submitted",
    "partial",
    "filled",
    "cancelled",
    "rejected",
    "watching",
]


class BracketLeg(BaseModel):
    stop_loss: Optional[float] = Field(None, gt=0)
    take_profit: Optional[float] = Field(None, gt=0)


class ManualOrderCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)
    side: OrderSide
    order_type: OrderType
    quantity: float = Field(..., gt=0)
    limit_price: Optional[float] = Field(None, gt=0)
    stop_price: Optional[float] = Field(None, gt=0)
    time_in_force: TimeInForce = "gtc"
    gtd_expires_at: Optional[datetime] = None
    bracket: Optional[BracketLeg] = None
    trailing_stop_pct: Optional[float] = Field(None, gt=0, le=50)
    oco_sibling_price: Optional[float] = Field(None, gt=0)
    maneuver_id: Optional[str] = Field(None, description="Prefill source maneuver (informational)")
    position_time_horizon: Optional[str] = Field(
        None,
        max_length=50,
        description="Position duration to store on the linked maneuver, e.g. '6 hours'.",
    )
    position_expiry_at: Optional[datetime] = Field(
        None,
        description="Exact position expiry to store on the linked maneuver.",
    )
    note: Optional[str] = None
    risk_confirm: bool = False
    trading_mode: Optional[str] = Field(
        None,
        pattern="^(paper|live)$",
        description="Mode chosen in the header. Live is checked on the server; default paper.",
    )

    @model_validator(mode="after")
    def _validate_prices(self) -> "ManualOrderCreate":
        if self.order_type == "limit" and not self.limit_price:
            raise ValueError("limit_price required for limit orders")
        if self.order_type in ("stop", "stop_limit", "trailing_stop") and not self.stop_price:
            if self.order_type != "trailing_stop" or not self.trailing_stop_pct:
                raise ValueError("stop_price required for stop orders")
        if self.order_type == "stop_limit" and not self.limit_price:
            raise ValueError("limit_price required for stop_limit orders")
        if self.order_type == "oco" and not self.oco_sibling_price:
            raise ValueError("oco_sibling_price required for OCO orders")
        return self


class ManualOrderModify(BaseModel):
    limit_price: Optional[float] = Field(None, gt=0)
    quantity: Optional[float] = Field(None, gt=0)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ManualOrderModify":
        if self.limit_price is None and self.quantity is None:
            raise ValueError("limit_price or quantity required")
        return self


class OrderPrefillFromManeuver(BaseModel):
    maneuver_id: str


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    ticker: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    mid_price: float | None = None
    spread_bps: float | None = None
    source: str | None = None
    as_of: datetime | None = None
    depth_available: bool = True
    session_label: str | None = None
    # Honest provider/session explanation when L2 ladder is missing (separate from CLOSED banner).
    depth_unavailable_reason: str | None = None
    exchange_id: str | None = None
    exchange_name_ru: str | None = None
    session_status: Literal["open", "closed", "pre", "post"] | None = None
    session_message_ru: str | None = None


class RecentTrade(BaseModel):
    id: str
    price: float
    size: float
    side: Literal["buy", "sell"] | None = None
    ts: datetime
    source: str


class SymbolTradingRulesOut(BaseModel):
    ticker: str
    venue: str
    tick_size: float
    lot_size: float
    min_qty: float
    min_notional_usd: float = 0.0
    price_decimals: int = 2
    qty_decimals: int = 6
    data_only: bool = False
    execution_enabled: bool = True
    feed_label_ru: str | None = None
    bybit_tokenized_listed: bool | None = None
    execution_block_type: Literal["unavailable", "connect_provider"] | None = None
    globally_tradeable: bool | None = None
    required_providers_ru: list[str] | None = None


class SlippageEstimate(BaseModel):
    estimated_slippage_bps: float
    estimated_avg_fill: float | None
    warning: str | None = None
    visible_liquidity_usd: float = 0.0


class ManualOrderOut(BaseModel):
    id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce
    status: OrderStatus
    bracket: BracketLeg | None = None
    trailing_stop_pct: float | None = None
    maneuver_id: str | None = None
    broker_order_id: str | None = None
    fill_price: float | None = None
    fill_quantity: float | None = None
    estimated_fees_usd: float | None = None
    slippage_warning: str | None = None
    sibling_order_id: str | None = None
    submitted_at: datetime
    filled_at: datetime | None = None
    error_message: str | None = None


class OrderTicketPrefill(BaseModel):
    ticker: str
    side: OrderSide
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    position_size_usd: float
    position_pct: float
    maneuver_id: str
    direction: str
    time_horizon: str | None = None
    expiry_at: datetime | None = None
    bracket: BracketLeg | None = None
