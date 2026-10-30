"""Black–Litterman views taken only from forecast_core payloads.

Mapping (docs/methodology/portfolio-construction.md):
calibrated_probability is the service's shrunk P(up). Signed excess is
(2 * P(up) - 1) * sigma. Missing calibrated_probability or a «нет данных»
payload produces no view.
"""
from __future__ import annotations

from app.services.target_portfolio.types import ForecastView


def view_from_forecast(payload: dict, *, sigma: float) -> ForecastView | None:
    if not payload:
        return None
    status = str(payload.get("data_status") or payload.get("status") or "")
    if status in {"нет данных", "insufficient_data"}:
        return None
    if payload.get("probability") is None and payload.get("calibrated_probability") is None:
        return None
    calibrated = payload.get("calibrated_probability")
    if calibrated is None:
        return None
    try:
        confidence = float(calibrated)
        vol = float(sigma)
    except (TypeError, ValueError):
        return None
    if not (0.0 < confidence < 1.0) or vol <= 0 or vol != vol:
        return None
    ticker = str(payload.get("ticker") or "")
    if not ticker:
        return None
    q = (2.0 * confidence - 1.0) * vol
    return ForecastView(ticker=ticker, q=q, confidence=confidence)
