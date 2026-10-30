"""Triple-barrier risk control per grid-level position (López de Prado pattern)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


class BarrierExit(str, Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME = "time"
    NONE = "none"


@dataclass
class TripleBarrierConfig:
    take_profit_pct: float = 0.015
    stop_loss_pct: float = 0.02
    max_hold_hours: float = 72.0

    def validate(self) -> None:
        if self.take_profit_pct <= 0 or self.stop_loss_pct <= 0:
            raise ValueError("barrier percentages must be positive")
        if self.max_hold_hours <= 0:
            raise ValueError("max_hold_hours must be positive")


@dataclass
class TripleBarrierPosition:
    """
    Wraps a single grid-level position with three simultaneous exit conditions.
    Whichever triggers first closes the position.
    """

    level_id: str
    side: str  # "buy" | "sell" (position direction after fill)
    entry_price: float
    quantity: float
    opened_at: datetime
    config: TripleBarrierConfig = field(default_factory=TripleBarrierConfig)
    is_closed: bool = False
    exit_reason: BarrierExit = BarrierExit.NONE
    exit_price: Optional[float] = None
    closed_at: Optional[datetime] = None
    realized_pnl: float = 0.0

    @property
    def take_profit_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1.0 + self.config.take_profit_pct)
        return self.entry_price * (1.0 - self.config.take_profit_pct)

    @property
    def stop_loss_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1.0 - self.config.stop_loss_pct)
        return self.entry_price * (1.0 + self.config.stop_loss_pct)

    @property
    def expires_at(self) -> datetime:
        return self.opened_at + timedelta(hours=self.config.max_hold_hours)

    def check_barriers(self, current_price: float, now: datetime | None = None) -> BarrierExit:
        """Evaluate all three barriers; return first triggered or NONE."""
        if self.is_closed:
            return self.exit_reason

        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Time barrier
        if ts >= self.expires_at:
            return BarrierExit.TIME

        if self.side == "buy":
            if current_price >= self.take_profit_price:
                return BarrierExit.TAKE_PROFIT
            if current_price <= self.stop_loss_price:
                return BarrierExit.STOP_LOSS
        else:
            if current_price <= self.take_profit_price:
                return BarrierExit.TAKE_PROFIT
            if current_price >= self.stop_loss_price:
                return BarrierExit.STOP_LOSS

        return BarrierExit.NONE

    def close(self, current_price: float, reason: BarrierExit, now: datetime | None = None) -> float:
        """Close position and compute realized PnL."""
        if self.is_closed:
            return self.realized_pnl

        ts = now or datetime.now(timezone.utc)
        self.is_closed = True
        self.exit_reason = reason
        self.exit_price = current_price
        self.closed_at = ts

        if self.side == "buy":
            self.realized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.realized_pnl = (self.entry_price - current_price) * self.quantity

        return self.realized_pnl

    def to_dict(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "side": self.side,
            "entry_price": round(self.entry_price, 6),
            "quantity": round(self.quantity, 6),
            "opened_at": self.opened_at.isoformat(),
            "take_profit_price": round(self.take_profit_price, 6),
            "stop_loss_price": round(self.stop_loss_price, 6),
            "expires_at": self.expires_at.isoformat(),
            "is_closed": self.is_closed,
            "exit_reason": self.exit_reason.value,
            "exit_price": round(self.exit_price, 6) if self.exit_price else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "realized_pnl": round(self.realized_pnl, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TripleBarrierPosition:
        cfg = TripleBarrierConfig(
            take_profit_pct=float(data.get("take_profit_pct", 0.015)),
            stop_loss_pct=float(data.get("stop_loss_pct", 0.02)),
            max_hold_hours=float(data.get("max_hold_hours", 72.0)),
        )
        pos = cls(
            level_id=str(data["level_id"]),
            side=str(data["side"]),
            entry_price=float(data["entry_price"]),
            quantity=float(data["quantity"]),
            opened_at=datetime.fromisoformat(data["opened_at"]),
            config=cfg,
            is_closed=bool(data.get("is_closed", False)),
            exit_reason=BarrierExit(data.get("exit_reason", "none")),
            exit_price=float(data["exit_price"]) if data.get("exit_price") else None,
            realized_pnl=float(data.get("realized_pnl", 0.0)),
        )
        if data.get("closed_at"):
            pos.closed_at = datetime.fromisoformat(data["closed_at"])
        return pos
