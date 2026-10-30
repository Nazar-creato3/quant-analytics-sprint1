"""Pure liquidity scoring from order book depth, spread, and volume."""
from __future__ import annotations

from typing import Any


def total_depth_qty(depth: list[dict[str, Any]], levels: int) -> float:
    """Sum quantity on the top ``levels`` of one side of the book."""
    total = 0.0
    for level in depth[:levels]:
        try:
            total += float(level.get("qty", 0))
        except (TypeError, ValueError):
            continue
    return max(0.0, total)


def compute_depth_ratio(
    bid_depth: list[dict[str, Any]],
    ask_depth: list[dict[str, Any]],
    baseline_bid_depth: list[dict[str, Any]],
    baseline_ask_depth: list[dict[str, Any]],
    *,
    levels: int,
) -> float:
    """Relative depth vs baseline on top N levels (1.0 = at or above baseline)."""
    current = total_depth_qty(bid_depth, levels) + total_depth_qty(ask_depth, levels)
    baseline = total_depth_qty(baseline_bid_depth, levels) + total_depth_qty(
        baseline_ask_depth, levels
    )
    if baseline <= 0:
        return 1.0 if current > 0 else 0.0
    return min(1.0, current / baseline)


def compute_spread_component(spread_bps: float | None, *, max_spread_bps: float) -> float:
    """Higher spread lowers the score toward 0."""
    if spread_bps is None:
        return 0.5
    if max_spread_bps <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(spread_bps) / max_spread_bps))


def compute_volume_component(volume_ratio: float | None) -> float:
    """Volume relative to historical average (1.0 = at or above average)."""
    if volume_ratio is None:
        return 0.5
    return max(0.0, min(1.0, float(volume_ratio)))


def compute_liquidity_score(
    *,
    spread_bps: float | None,
    bid_depth: list[dict[str, Any]],
    ask_depth: list[dict[str, Any]],
    baseline_bid_depth: list[dict[str, Any]],
    baseline_ask_depth: list[dict[str, Any]],
    volume_ratio: float | None,
    depth_levels: int = 5,
    max_spread_bps: float = 100.0,
    depth_weight: float = 0.45,
    spread_weight: float = 0.35,
    volume_weight: float = 0.20,
) -> float:
    """
    Composite liquidity score in [0, 1].

    1 = deep, tight, liquid market; 0 = dangerously thin book / wide spread / low volume.
    """
    depth = compute_depth_ratio(
        bid_depth,
        ask_depth,
        baseline_bid_depth,
        baseline_ask_depth,
        levels=depth_levels,
    )
    spread = compute_spread_component(spread_bps, max_spread_bps=max_spread_bps)
    volume = compute_volume_component(volume_ratio)

    weight_sum = depth_weight + spread_weight + volume_weight
    if weight_sum <= 0:
        return 0.0
    score = (
        depth * depth_weight + spread * spread_weight + volume * volume_weight
    ) / weight_sum
    return max(0.0, min(1.0, score))
