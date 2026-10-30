"""Probabilistic forecast ensemble — lazy exports."""

from __future__ import annotations

from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "aggregate_forecast": ("app.services.forecast.aggregation", "aggregate_forecast"),
    "composite_risk_score": ("app.services.forecast.aggregation", "composite_risk_score"),
    "ForecastEngine": ("app.services.forecast.engine", "ForecastEngine"),
    "get_forecast_engine": ("app.services.forecast.engine", "get_forecast_engine"),
    "compute_correlation_shift_score": ("app.services.forecast.signals", "compute_correlation_shift_score"),
    "compute_event_impact_score": ("app.services.forecast.signals", "compute_event_impact_score"),
    "compute_liquidity_deterioration_score": (
        "app.services.forecast.signals",
        "compute_liquidity_deterioration_score",
    ),
    "compute_short_term_momentum": ("app.services.forecast.signals", "compute_short_term_momentum"),
    "compute_tail_risk_score": ("app.services.forecast.signals", "compute_tail_risk_score"),
    "compute_volatility_expansion_probability": (
        "app.services.forecast.signals",
        "compute_volatility_expansion_probability",
    ),
    "ContributingFactor": ("app.services.forecast.types", "ContributingFactor"),
    "ForecastDirection": ("app.services.forecast.types", "ForecastDirection"),
    "ForecastInputBundle": ("app.services.forecast.types", "ForecastInputBundle"),
    "ForecastSignals": ("app.services.forecast.types", "ForecastSignals"),
    "InstrumentForecast": ("app.services.forecast.types", "InstrumentForecast"),
    "RiskFlag": ("app.services.forecast.types", "RiskFlag"),
}

__all__ = list(_LAZY.keys())


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0])
    return getattr(module, target[1])
