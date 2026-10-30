"""Backtest trade classification — clean_exit vs non_clean_exit."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

# Planned / strategy-driven exits
_CLEAN_EXIT_REASONS = frozenset({
    "rsi_overbought",
    "below_sma",
    "mid_bb",
    "rsi_exit",
    "take_profit",
    "scale_out",
    "time_expiry",
    "strategy_unwind",
    "planned_exit",
    "end_of_data",  # backtest horizon — analytical, not panic
})

# Emergency / forced exits
_NON_CLEAN_EXIT_REASONS = frozenset({
    "stop_loss",
    "stop",
    "emergency_stop",
    "kill_switch",
    "forced_liquidation",
    "manual_panic",
    "platform_interruption",
    "margin_call",
})


class ExitClassification(StrEnum):
    CLEAN_EXIT = "clean_exit"
    NON_CLEAN_EXIT = "non_clean_exit"
    UNCLASSIFIED = "unclassified"


def classify_trade_exit(exit_reason: str, *, pnl: float | None = None) -> ExitClassification:
    """Tag a closed trade by exit reason."""
    reason = (exit_reason or "").strip().lower()
    if reason in _NON_CLEAN_EXIT_REASONS:
        return ExitClassification.NON_CLEAN_EXIT
    if reason in _CLEAN_EXIT_REASONS:
        return ExitClassification.CLEAN_EXIT
    # Heuristic: generic 'stop' substring
    if "stop" in reason and reason not in _CLEAN_EXIT_REASONS:
        return ExitClassification.NON_CLEAN_EXIT
    if "panic" in reason or "kill" in reason or "liquidat" in reason:
        return ExitClassification.NON_CLEAN_EXIT
    return ExitClassification.UNCLASSIFIED


def classify_trade_log(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich trade dicts with exit_classification field."""
    enriched: list[dict[str, Any]] = []
    for trade in trades:
        row = dict(trade)
        row["exit_classification"] = classify_trade_exit(
            row.get("exit_reason", ""),
            pnl=row.get("pnl"),
        ).value
        enriched.append(row)
    return enriched


def filter_clean_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only clean_exit trades (default analysis set)."""
    classified = classify_trade_log(trades)
    return [t for t in classified if t.get("exit_classification") == ExitClassification.CLEAN_EXIT.value]
