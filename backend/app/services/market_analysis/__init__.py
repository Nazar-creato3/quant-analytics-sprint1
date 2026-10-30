"""Institutional-style market analysis (factor exposures, risk, scenarios)."""

from __future__ import annotations

from typing import Any

from app.services.market_analysis.service import event_calendar, overview

__all__ = [
    "STYLE_FACTOR_NAMES",
    "build_ticker_analysis_payload",
    "compute_risk_metrics_from_prices",
    "compute_style_factor_exposures",
    "cross_sectional_zscore",
    "event_calendar",
    "overview",
]


def __getattr__(name: str) -> Any:
    if name == "build_ticker_analysis_payload":
        from app.services.market_analysis.assembler import build_ticker_analysis_payload as fn

        return fn
    if name == "compute_risk_metrics_from_prices":
        from app.services.market_analysis.risk_metrics import compute_risk_metrics_from_prices as fn

        return fn
    if name in {"STYLE_FACTOR_NAMES", "compute_style_factor_exposures", "cross_sectional_zscore"}:
        from app.services.market_analysis import style_factors

        return getattr(style_factors, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
