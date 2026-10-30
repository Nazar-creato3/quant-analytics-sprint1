"""Feature extraction for RegimeEngine observations."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.quant_math import correlation, historical_volatility, log_return, rolling_volatility

from app.services.regime.types import InstrumentSeries, RegimeFeatureVector


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_mean(values: Sequence[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def prices_to_returns(prices: Sequence[float]) -> list[float]:
    if len(prices) < 2:
        return []
    return [log_return(prices[index], prices[index - 1]) for index in range(1, len(prices))]


def compute_ma_slope(prices: Sequence[float], window: int = 10) -> float:
    """Relative change in trailing vs prior moving average, scaled to [-1, 1]."""
    if len(prices) < window + 1:
        return 0.0

    recent_ma = _safe_mean(prices[-window:])
    if len(prices) >= window * 2:
        prior_ma = _safe_mean(prices[-window * 2 : -window])
    else:
        prior_ma = _safe_mean(prices[:window])

    if prior_ma <= 0.0:
        return 0.0

    relative_change = (recent_ma - prior_ma) / prior_ma
    return _clamp(relative_change * 10.0)


def compute_band_position(prices: Sequence[float], window: int = 20) -> float:
    """Price position within Bollinger bands, mapped to [0, 1]."""
    if len(prices) < window:
        return 0.5

    window_prices = list(prices[-window:])
    mean_price = _safe_mean(window_prices)
    variance = sum((value - mean_price) ** 2 for value in window_prices) / max(window - 1, 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0.0:
        return 0.5

    upper = mean_price + 2.0 * std_dev
    lower = mean_price - 2.0 * std_dev
    width = upper - lower
    if width <= 0.0:
        return 0.5
    return _clamp((prices[-1] - lower) / width, 0.0, 1.0)


def compute_vol_shock_score(returns: Sequence[float], recent_window: int = 5) -> float:
    """Detect abrupt return spikes relative to prior absolute-return baseline."""
    if len(returns) < 2:
        return 1.0

    abs_returns = [abs(value) for value in returns]
    recent = abs_returns[-min(recent_window, len(abs_returns)) :]
    prior = abs_returns[: -len(recent)] if len(abs_returns) > len(recent) else abs_returns[:-1]
    baseline = _safe_mean(prior) if prior else _safe_mean(abs_returns)
    recent_peak = max(recent) if recent else 0.0

    if baseline <= 1e-12:
        return _clamp(recent_peak * 50.0, 0.0, 5.0)
    return _clamp(recent_peak / baseline, 0.0, 5.0)


def compute_vol_ratio(returns: Sequence[float], window: int = 10) -> tuple[float, float]:
    """Return (current rolling vol / baseline vol, normalized vol level)."""
    if len(returns) < window:
        shock = compute_vol_shock_score(returns)
        return shock, _clamp(shock / 5.0, 0.0, 1.0)

    rolling = rolling_volatility(returns, window)
    finite = [value for value in rolling if math.isfinite(value)]
    if not finite:
        shock = compute_vol_shock_score(returns)
        return shock, _clamp(shock / 5.0, 0.0, 1.0)

    short_window = min(5, window)
    short_vol = (
        historical_volatility(returns[-short_window:])
        if len(returns) >= short_window
        else finite[-1]
    )
    current = max(finite[-1], short_vol)
    baseline = _safe_mean(finite[:-1]) if len(finite) > 1 else finite[-1]
    if baseline <= 1e-12:
        ratio = 1.0 if current <= 1e-12 else 3.0
    else:
        ratio = current / baseline

    shock = compute_vol_shock_score(returns)
    combined_ratio = max(ratio, shock)
    vol_level = _clamp(combined_ratio / 5.0, 0.0, 1.0)
    return _clamp(combined_ratio, 0.0, 5.0), vol_level


def compute_volume_change(volumes: Sequence[float], window: int = 10) -> float:
    if len(volumes) < window + 1:
        return 0.0

    recent = _safe_mean(volumes[-window:])
    baseline = _safe_mean(volumes[:-window]) if len(volumes) > window else recent
    if baseline <= 1e-12:
        return 0.0
    return _clamp((recent - baseline) / baseline)


def normalize_spread_bps(spread_bps: float | None) -> float:
    if spread_bps is None or spread_bps < 0.0:
        return 0.25
    return _clamp(float(spread_bps) / 100.0, 0.0, 1.0)


def average_pairwise_correlation(return_series: Sequence[Sequence[float]]) -> float:
    """Mean absolute pairwise correlation across instruments in a sector."""
    series = [list(values) for values in return_series if len(values) >= 2]
    if len(series) < 2:
        return 0.0

    min_len = min(len(values) for values in series)
    aligned = [values[-min_len:] for values in series]

    correlations: list[float] = []
    for left_index in range(len(aligned)):
        for right_index in range(left_index + 1, len(aligned)):
            correlations.append(abs(correlation(aligned[left_index], aligned[right_index])))
    return _clamp(_safe_mean(correlations), 0.0, 1.0)


def build_feature_vector(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    spread_bps: float | None = None,
    correlation_cluster: float = 0.0,
    ma_window: int = 10,
    band_window: int = 20,
    vol_window: int = 10,
) -> RegimeFeatureVector:
    returns = prices_to_returns(prices)
    vol_ratio, vol_level = compute_vol_ratio(returns, window=vol_window)
    volume_values = list(volumes or [])
    if not volume_values and prices:
        volume_values = [1.0] * len(prices)

    return RegimeFeatureVector(
        trend_slope=compute_ma_slope(prices, window=ma_window),
        band_position=compute_band_position(prices, window=band_window),
        vol_ratio=vol_ratio,
        vol_level=vol_level,
        volume_change=compute_volume_change(volume_values, window=ma_window),
        spread_norm=normalize_spread_bps(spread_bps),
        correlation_cluster=_clamp(correlation_cluster, 0.0, 1.0),
    )


def build_feature_sequence(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    spread_bps: float | None = None,
    correlation_cluster: float = 0.0,
    min_history: int = 25,
) -> list[RegimeFeatureVector]:
    """Build a sequence of feature vectors for HMM filtering."""
    if len(prices) < min_history:
        return [
            build_feature_vector(
                prices,
                volumes,
                spread_bps=spread_bps,
                correlation_cluster=correlation_cluster,
            )
        ]

    max_sequence = 12
    sequence: list[RegimeFeatureVector] = []
    # Only the last max_sequence vectors are returned; building the earlier ones (each O(n))
    # made this O(n^2) and dominated manoeuvre generation time. Same output as before.
    start = max(min_history, len(prices) - max_sequence + 1)
    for end in range(start, len(prices) + 1):
        sequence.append(
            build_feature_vector(
                prices[:end],
                volumes[:end] if volumes else None,
                spread_bps=spread_bps,
                correlation_cluster=correlation_cluster,
            )
        )
    if len(sequence) > max_sequence:
        sequence = sequence[-max_sequence:]
    return sequence


def aggregate_sector_prices(instruments: dict[int, InstrumentSeries]) -> list[float]:
    """Equal-weight average price path across sector instruments."""
    if not instruments:
        return []

    min_len = min(len(series.prices) for series in instruments.values())
    if min_len == 0:
        return []

    aggregated: list[float] = []
    for index in range(min_len):
        aggregated.append(
            _safe_mean(series.prices[index] for series in instruments.values())
        )
    return aggregated


def aggregate_sector_volumes(instruments: dict[int, InstrumentSeries]) -> list[float]:
    if not instruments:
        return []

    min_len = min(len(series.prices) for series in instruments.values())
    volumes: list[float] = []
    for index in range(min_len):
        values = [
            series.volumes[index]
            for series in instruments.values()
            if index < len(series.volumes)
        ]
        volumes.append(_safe_mean(values) if values else 1.0)
    return volumes


def aggregate_sector_spread(instruments: dict[int, InstrumentSeries]) -> float | None:
    spreads = [
        series.spread_bps
        for series in instruments.values()
        if series.spread_bps is not None
    ]
    if not spreads:
        return None
    return _safe_mean(spreads)


def sector_return_series(instruments: dict[int, InstrumentSeries]) -> list[list[float]]:
    return [prices_to_returns(series.prices) for series in instruments.values()]
