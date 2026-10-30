"""Pure signal functions for ForecastEngine (Prompt 22)."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.quant_math import (
    expected_shortfall,
    historical_volatility,
    log_return,
    rolling_volatility,
    value_at_risk,
)
from app.services.regime.features import prices_to_returns

from app.services.forecast.types import ForecastDirection


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_mean(values: Sequence[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def compute_short_term_momentum(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    return_window: int = 5,
    volume_window: int = 5,
) -> tuple[float, ForecastDirection]:
    """Strength of short-horizon momentum from rolling returns and volume trend."""
    if len(prices) < return_window + 1:
        return 0.0, ForecastDirection.NEUTRAL

    returns = prices_to_returns(prices)
    recent_returns = returns[-return_window:]
    momentum = _safe_mean(recent_returns)

    volume_boost = 0.0
    if volumes and len(volumes) >= volume_window + 1:
        recent_volume = _safe_mean(volumes[-volume_window:])
        prior_volume = _safe_mean(volumes[-volume_window * 2 : -volume_window])
        if prior_volume > 0:
            volume_boost = _clamp((recent_volume / prior_volume - 1.0) * 0.25, 0.0, 0.25)

    strength = _clamp(abs(momentum) * 25.0 + volume_boost)
    if momentum > 0.001:
        direction = ForecastDirection.BULLISH
    elif momentum < -0.001:
        direction = ForecastDirection.BEARISH
    else:
        direction = ForecastDirection.NEUTRAL
    return strength, direction


def compute_tail_risk_score(
    returns: Sequence[float],
    *,
    alpha: float = 0.95,
    normalization_scale: float = 0.05,
) -> float:
    """Normalize expected shortfall into [0, 1] tail-risk score."""
    values = list(returns)
    if len(values) < 5:
        return 0.0

    var_value = value_at_risk(values, alpha)
    es_value = expected_shortfall(values, alpha, var_value)
    if normalization_scale <= 0:
        return 0.0
    return _clamp(es_value / normalization_scale)


def compute_volatility_expansion_probability(
    returns: Sequence[float],
    *,
    window: int = 10,
    trend_periods: int = 5,
) -> float:
    """Probability that rolling volatility is expanding over recent periods."""
    values = list(returns)
    if len(values) < window + trend_periods:
        return 0.0

    rolling = rolling_volatility(values, window)
    recent = [value for value in rolling[-trend_periods:] if math.isfinite(value)]
    prior = [
        value
        for value in rolling[-(trend_periods * 2) : -trend_periods]
        if math.isfinite(value)
    ]
    if not recent:
        return 0.0

    recent_avg = _safe_mean(recent)
    prior_avg = _safe_mean(prior) if prior else recent_avg
    if prior_avg <= 1e-12:
        expansion_ratio = recent_avg * 100.0
    else:
        expansion_ratio = recent_avg / prior_avg

    return _clamp((expansion_ratio - 1.0) / 1.5)


def compute_correlation_shift_score(
    current_weights: Sequence[float] | None,
    prior_weights: Sequence[float] | None,
) -> float:
    """Absolute shift in average absolute correlation edge weight."""
    current = list(current_weights or [])
    prior = list(prior_weights or [])
    if not current:
        return 0.0

    current_avg = _safe_mean([abs(value) for value in current])
    prior_avg = _safe_mean([abs(value) for value in prior]) if prior else current_avg * 0.7
    shift = abs(current_avg - prior_avg)
    return _clamp(shift / 0.5)


def compute_liquidity_deterioration_score(
    *,
    liquidity_score: float | None = None,
    prior_liquidity_score: float | None = None,
    spread_bps: float | None = None,
    prior_spread_bps: float | None = None,
    depth_ratio: float | None = None,
    prior_depth_ratio: float | None = None,
    max_spread_bps: float = 100.0,
) -> float:
    """Higher score means liquidity is deteriorating (spread wider / depth thinner)."""
    components: list[float] = []

    if liquidity_score is not None:
        components.append(_clamp(1.0 - liquidity_score))
    if prior_liquidity_score is not None and liquidity_score is not None:
        drop = prior_liquidity_score - liquidity_score
        if drop > 0:
            components.append(_clamp(drop / max(prior_liquidity_score, 0.05)))

    if spread_bps is not None and prior_spread_bps is not None and prior_spread_bps > 0:
        spread_widen = (spread_bps - prior_spread_bps) / prior_spread_bps
        if spread_widen > 0:
            components.append(_clamp(spread_widen))
    elif spread_bps is not None and max_spread_bps > 0:
        components.append(_clamp(spread_bps / max_spread_bps))

    if depth_ratio is not None and prior_depth_ratio is not None and prior_depth_ratio > 0:
        depth_drop = (prior_depth_ratio - depth_ratio) / prior_depth_ratio
        if depth_drop > 0:
            components.append(_clamp(depth_drop))

    if not components:
        return 0.0
    return _clamp(max(components))


def compute_event_impact_score(
    *,
    news_impact_probability: float = 0.0,
    news_shock_score: float = 0.0,
) -> float:
    """Combine Event Risk Layer probability and shock score into [0, 1]."""
    probability = _clamp(news_impact_probability)
    shock = _clamp(news_shock_score)
    return _clamp(max(probability, shock * 0.85))


def build_returns(prices: Sequence[float], returns: Sequence[float] | None = None) -> list[float]:
    if returns is not None:
        return list(returns)
    return prices_to_returns(prices)


def correlation_weights_for_instrument(
    edges: Sequence[object],
    instrument_id: int,
) -> list[float]:
    """Extract absolute correlation edge weights touching an instrument node."""
    from app.services.market_graph.nodes import instrument_node, parse_instrument_node
    from app.services.market_graph.types import EdgeType

    node = instrument_node(instrument_id)
    weights: list[float] = []
    for edge in edges:
        edge_type = getattr(edge, "edge_type", None)
        if edge_type is not None and edge_type != EdgeType.CORRELATION:
            continue
        from_node = getattr(edge, "from_node", "")
        to_node = getattr(edge, "to_node", "")
        if from_node != node and to_node != node:
            continue
        if parse_instrument_node(from_node) is None and parse_instrument_node(to_node) is None:
            continue
        weights.append(abs(float(getattr(edge, "weight", 0.0))))
    return weights
