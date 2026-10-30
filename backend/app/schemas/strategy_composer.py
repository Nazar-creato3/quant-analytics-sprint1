"""Strategy Composer API schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.strategy.composer.models import (
    ComposerConfig,
    ComposerSchemaOut,
    ComposerValidationResult,
    CompiledStrategyConfig,
)

ComposerConfigIn = ComposerConfig
ComposerConfigOut = ComposerConfig


class ComposerBacktestRequest(BaseModel):
    config: ComposerConfig
    symbol: str = Field(min_length=1, max_length=32)
    lookback_days: int = Field(default=504, ge=90, le=2500)


class ComposerBacktestPoint(BaseModel):
    date: str
    equity: float


class ComposerBacktestOut(BaseModel):
    symbol: str
    start: str = ""
    end: str = ""
    observations: int = 0
    in_market_days: int = 0
    win_rate: float | None = None
    max_drawdown: float | None = None
    total_return: float | None = None
    purged_cv_win_rate: float | None = None
    purged_folds: int = 0
    equity_curve: list[ComposerBacktestPoint] = Field(default_factory=list)
    insufficient_data: bool = False
    methodology: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "ComposerConfigIn",
    "ComposerConfigOut",
    "ComposerSchemaOut",
    "ComposerValidationResult",
    "CompiledStrategyConfig",
    "ComposerBacktestRequest",
    "ComposerBacktestOut",
]
