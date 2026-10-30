"""Shared tradeable maneuver counting (poll toast, report GET, pending list)."""
from __future__ import annotations

from typing import Protocol

from app.schemas.schemas import StrategyType
from app.utils.json_safe import finite_float


class _ManeuverLike(Protocol):
    strategy_type: StrategyType | str
    ticker: str
    direction: str
    position_size_usd: float | None


def count_tradeable_persisted(maneuvers: list[_ManeuverLike]) -> int:
    """Same rule as pipeline post-save recount and frontend isTradeableManeuver."""
    n = 0
    for m in maneuvers:
        st = m.strategy_type.value if hasattr(m.strategy_type, "value") else str(m.strategy_type)
        if st == StrategyType.NO_TRADE.value:
            continue
        if m.ticker in ("—", "-") or not m.ticker:
            continue
        if m.direction == "neutral":
            continue
        size = finite_float(getattr(m, "position_size_usd", None))
        if size is None or size <= 0:
            continue
        n += 1
    return n


def analysis_list_counts_sync(
    *,
    status_tradeable: int | None,
    report_maneuvers: list[_ManeuverLike],
    list_tradeable: int | None = None,
) -> bool:
    """Prompt 90: poll/toast count must match persisted report rows (and optional list)."""
    persisted = count_tradeable_persisted(report_maneuvers)
    if status_tradeable is None:
        return False
    if status_tradeable != persisted:
        return False
    if list_tradeable is not None and list_tradeable != persisted:
        return False
    return True
