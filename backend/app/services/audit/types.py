"""Shared types for position audit pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ClosedTradeRecord:
    """Normalized closed maneuver for audit computations."""

    id: str
    ticker: str
    strategy_type: str
    direction: str
    entry_price: float
    stop_loss_price: float | None
    position_size_usd: float
    fill_price: float | None
    exit_price: float | None
    realized_pnl: float
    exit_reason: str
    signal_generated_price: float | None
    peak_unrealized_pnl: float | None
    factor_exposures: dict[str, float]
    regime_at_entry: str | None
    sector_at_entry: str | None
    filled_at: datetime | None
    closed_at: datetime | None
    hold_duration_seconds: float | None = None

    @property
    def is_win(self) -> bool:
        return self.realized_pnl > 0

    @property
    def return_pct(self) -> float:
        if self.position_size_usd <= 0:
            return 0.0
        return self.realized_pnl / self.position_size_usd

    @property
    def position_size(self) -> float:
        """Compatibility alias for the spec's position_size field."""
        return self.position_size_usd


def maneuver_to_trade_record(maneuver: Any) -> ClosedTradeRecord | None:
    """Convert a closed Maneuver ORM row into a ClosedTradeRecord."""
    from app.services.portfolio.position_analytics import _entry_reference, maneuver_stop_loss
    from app.utils.json_safe import finite_float

    entry = finite_float(getattr(maneuver, "entry_price", None)) or _entry_reference(maneuver)
    if entry is None or entry <= 0:
        return None

    stop = finite_float(getattr(maneuver, "stop_loss_price", None)) or maneuver_stop_loss(maneuver)
    realized = finite_float(getattr(maneuver, "realized_pnl", None))
    if realized is None:
        realized = 0.0

    filled_at = getattr(maneuver, "filled_at", None)
    closed_at = getattr(maneuver, "closed_at", None)
    hold_seconds: float | None = None
    if filled_at is not None and closed_at is not None:
        fa = filled_at if filled_at.tzinfo else filled_at.replace(tzinfo=closed_at.tzinfo)
        ca = closed_at if closed_at.tzinfo else closed_at.replace(tzinfo=fa.tzinfo)
        hold_seconds = max(0.0, (ca - fa).total_seconds())

    exposures = getattr(maneuver, "factor_exposures_at_entry", None) or {}
    if not isinstance(exposures, dict):
        exposures = {}

    strategy = getattr(maneuver, "strategy_type", "")
    if hasattr(strategy, "value"):
        strategy = strategy.value

    direction = getattr(maneuver, "direction", "")
    if hasattr(direction, "value"):
        direction = direction.value

    return ClosedTradeRecord(
        id=str(maneuver.id),
        ticker=str(maneuver.ticker).upper(),
        strategy_type=str(strategy),
        direction=str(direction),
        entry_price=float(entry),
        stop_loss_price=float(stop) if stop is not None else None,
        position_size_usd=float(getattr(maneuver, "position_size_usd", 0.0) or 0.0),
        fill_price=finite_float(getattr(maneuver, "fill_price", None)),
        exit_price=finite_float(getattr(maneuver, "exit_price", None)),
        realized_pnl=float(realized),
        exit_reason=str(getattr(maneuver, "exit_reason", "") or ""),
        signal_generated_price=finite_float(getattr(maneuver, "signal_generated_price", None)),
        peak_unrealized_pnl=finite_float(getattr(maneuver, "peak_unrealized_pnl", None)),
        factor_exposures={str(k): float(v) for k, v in exposures.items() if v is not None},
        regime_at_entry=getattr(maneuver, "regime_at_entry", None),
        sector_at_entry=getattr(maneuver, "sector_at_entry", None),
        filled_at=filled_at,
        closed_at=closed_at,
        hold_duration_seconds=hold_seconds,
    )
