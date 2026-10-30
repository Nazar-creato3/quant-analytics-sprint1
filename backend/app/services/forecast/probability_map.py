"""Unified probability / signal map from hierarchy ForecastOutput."""
from __future__ import annotations

from typing import Mapping

from app.services.prediction_hierarchy.types import ForecastOutput

_RISK_SIGNAL_KEYS: tuple[str, ...] = (
    "volatility_expansion_probability",
    "liquidity_deterioration_score",
    "liquidity_risk_score",
    "tail_risk_score",
    "event_impact_score",
    "correlation_shift_score",
    "composite_risk_score",
)

TRACKED_METRIC_KEYS: tuple[str, ...] = (
    "volatility_expansion_probability",
    "liquidity_risk_score",
    "event_impact_score",
    "correlation_shift_score",
    "interval_p10",
    "interval_p90",
)


def build_hierarchy_probability_map(hierarchy: ForecastOutput) -> dict[str, float]:
    """Same risk/point signals as chat Risk section and ActionForecastEngine."""
    metrics = hierarchy.risk_forecast.instrument_metrics
    out: dict[str, float] = {
        "momentum_score": float(hierarchy.point_forecast.momentum_score),
        "interval_p10": float(hierarchy.interval_forecast.p10),
        "interval_p90": float(hierarchy.interval_forecast.p90),
    }
    for key in _RISK_SIGNAL_KEYS:
        val = metrics.get(key)
        if val is not None:
            out[key] = float(val)
    return out


def build_probability_map_data_quality(hierarchy: ForecastOutput) -> dict[str, str]:
    """Flag metrics that are zero due to missing inputs, not a real computed zero."""
    flags: dict[str, str] = {}
    summary = hierarchy.interval_forecast.plain_language_summary or ""
    if "insufficient_data" in summary or "Недостаточно истории" in summary:
        flags["interval_p10"] = "insufficient_data"
        flags["interval_p90"] = "insufficient_data"
    metrics = hierarchy.risk_forecast.instrument_metrics
    for key in _RISK_SIGNAL_KEYS:
        if metrics.get(key) is None:
            flags[key] = "insufficient_data"
    return flags


def build_metric_validity(hierarchy: ForecastOutput) -> dict[str, bool]:
    """Per-metric validity for API/UI — False when computation did not run or failed."""
    quality = build_probability_map_data_quality(hierarchy)
    return {
        key: quality.get(key) != "insufficient_data"
        for key in TRACKED_METRIC_KEYS
    }


def meaningful_factor_exposures(
    exposures: Mapping[str, float | None] | None,
) -> dict[str, float]:
    """Drop nulls; keep valid z-scores including 0.0."""
    if not exposures:
        return {}
    out: dict[str, float] = {}
    for key, raw in exposures.items():
        if raw is None:
            continue
        value = float(raw)
        if not (value == value):  # NaN
            continue
        out[str(key)] = round(value, 4)
    return out


def is_placeholder_factor_map(exposures: Mapping[str, float] | None) -> bool:
    """Daily-builder / DB stubs that are all zeros — prefer assembler output."""
    if not exposures:
        return True
    return all(abs(float(v)) < 1e-9 for v in exposures.values())


def resolve_factor_exposures_for_forecast(
    *,
    payload_factors: Mapping[str, float] | None,
    analysis_factors: Mapping[str, float] | None,
    ticker_analysis_factors: Mapping[str, float | None] | None,
) -> dict[str, float]:
    """Priority: market_analysis assembler → analysis context → daily payload."""
    for source in (
        ticker_analysis_factors,
        analysis_factors,
        payload_factors,
    ):
        resolved = meaningful_factor_exposures(source)
        if not resolved:
            continue
        if source is payload_factors and is_placeholder_factor_map(resolved):
            continue
        return resolved
    return {}
