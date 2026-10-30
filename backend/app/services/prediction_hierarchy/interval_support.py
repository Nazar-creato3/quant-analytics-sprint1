"""Whether interval_forecast bands are supported enough for narrator/UI claims."""
from __future__ import annotations

from typing import Mapping

from app.services.prediction_hierarchy.types import DistributionForecast, IntervalForecast

_INSUFFICIENT_DIST_METHODS = frozenset({"insufficient_data", "degraded_macro_only"})


def interval_band_is_supported(
    interval: IntervalForecast,
    *,
    distribution: DistributionForecast | None = None,
    metadata: Mapping[str, object] | None = None,
    min_band_width: float = 0.08,
) -> bool:
    """True only when P10/P90 come from real vol history, not placeholders."""
    if metadata and metadata.get("degraded"):
        return False
    if distribution is not None and distribution.method in _INSUFFICIENT_DIST_METHODS:
        return False
    if interval.rolling_volatility <= 0.0:
        return False
    band_width = abs(interval.p90 - interval.p10)
    if band_width < min_band_width:
        return False
    return True
