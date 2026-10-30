"""Pydantic grid configuration — spec-aligned GridConfig model."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GridType(str, Enum):
    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"


class GridExecutorState(str, Enum):
    GRID_ACTIVE = "grid_active"
    DCA_MODE = "dca_mode"


RiskLevel = Literal["low", "medium", "high"]


class GridConfigModel(BaseModel):
    """Grid bot configuration (Pydantic — API + executor)."""

    symbol: str = Field(..., min_length=1, max_length=24)
    upper_bound: float = Field(..., gt=0)
    lower_bound: float = Field(..., gt=0)
    num_levels: int = Field(10, ge=2, le=100)
    grid_type: GridType = GridType.GEOMETRIC
    capital_allocated: float = Field(..., gt=0)
    take_profit: float | None = None
    stop_loss: float | None = None
    mode: str = "paper"
    trailing_enabled: bool = False
    trailing_offset_pct: float = Field(0.02, ge=0.001, le=0.5)
    dca_enabled: bool = True
    dca_step_pct: float = Field(0.01, ge=0.001, le=0.2)
    dca_take_profit_pct: float = Field(0.03, ge=0.001, le=0.5)
    # Per-level triple-barrier defaults (fraction of entry price)
    level_take_profit_pct: float = Field(0.015, ge=0.0001, le=0.5)
    level_stop_loss_pct: float = Field(0.02, ge=0.0001, le=0.5)
    level_max_hold_hours: float = Field(72.0, ge=1.0, le=8760.0)
    fee_bps: float = Field(10.0, ge=0.0, le=100.0)
    slippage_bps: float = Field(5.0, ge=0.0, le=100.0)
    leverage: float = Field(1.0, ge=1.0, le=125.0)

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _bounds(self) -> GridConfigModel:
        if self.lower_bound >= self.upper_bound:
            raise ValueError("lower_bound must be less than upper_bound")
        return self

    def to_engine_dict(self) -> dict:
        """Map to legacy engine field names."""
        return {
            "ticker": self.symbol,
            "lower_price": self.lower_bound,
            "upper_price": self.upper_bound,
            "grid_count": self.num_levels,
            "total_capital": self.capital_allocated,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "grid_type": self.grid_type.value,
            "trailing_enabled": self.trailing_enabled,
            "trailing_offset_pct": self.trailing_offset_pct,
            "dca_enabled": self.dca_enabled,
            "dca_step_pct": self.dca_step_pct,
            "dca_take_profit_pct": self.dca_take_profit_pct,
            "level_take_profit_pct": self.level_take_profit_pct,
            "level_stop_loss_pct": self.level_stop_loss_pct,
            "level_max_hold_hours": self.level_max_hold_hours,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "leverage": self.leverage,
            "mode": self.mode,
        }

    @classmethod
    def from_engine_dict(cls, data: dict) -> GridConfigModel:
        return cls(
            symbol=data.get("ticker") or data.get("symbol", ""),
            upper_bound=float(data.get("upper_price") or data.get("upper_bound", 0)),
            lower_bound=float(data.get("lower_price") or data.get("lower_bound", 0)),
            num_levels=int(data.get("grid_count") or data.get("num_levels", 10)),
            grid_type=GridType(data.get("grid_type", GridType.GEOMETRIC.value)),
            capital_allocated=float(data.get("total_capital") or data.get("capital_allocated", 0)),
            take_profit=data.get("take_profit"),
            stop_loss=data.get("stop_loss"),
            mode=data.get("mode", "paper"),
            trailing_enabled=bool(data.get("trailing_enabled", False)),
            trailing_offset_pct=float(data.get("trailing_offset_pct", 0.02)),
            dca_enabled=bool(data.get("dca_enabled", True)),
            dca_step_pct=float(data.get("dca_step_pct", 0.01)),
            dca_take_profit_pct=float(data.get("dca_take_profit_pct", 0.03)),
            level_take_profit_pct=float(data.get("level_take_profit_pct", 0.015)),
            level_stop_loss_pct=float(data.get("level_stop_loss_pct", 0.02)),
            level_max_hold_hours=float(data.get("level_max_hold_hours", 72.0)),
            fee_bps=float(data.get("fee_bps", 10.0)),
            slippage_bps=float(data.get("slippage_bps", 5.0)),
            leverage=float(data.get("leverage", 1.0)),
        )


class AutoGridRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    capital_allocated: float = Field(..., gt=0)
    risk_level: RiskLevel = "medium"
    grid_type: GridType | None = None


class AutoGridResponse(BaseModel):
    config: GridConfigModel
    current_price: float
    realized_volatility: float
    volatility_regime: str
    num_levels: int
    grid_type: GridType
