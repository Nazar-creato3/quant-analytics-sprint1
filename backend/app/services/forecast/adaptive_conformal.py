"""Adaptive Conformal Inference (ACI) intervals — augments static MAPIE/split conformal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.conformal import ConformalInterval, compute_conformal_intervals

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AciState:
    alpha_target: float
    alpha_t: float
    coverage_ema: float
    step_size: float


_ACI_STATE: dict[str, AciState] = {}


def _get_state(key: str, alpha: float = 0.1, step: float = 0.05) -> AciState:
    if key not in _ACI_STATE:
        _ACI_STATE[key] = AciState(alpha_target=alpha, alpha_t=alpha, coverage_ema=1.0 - alpha, step_size=step)
    return _ACI_STATE[key]


def update_aci_coverage(key: str, covered: bool, *, alpha: float = 0.1, step: float = 0.05) -> AciState:
    """Online ACI update: widen when miss, shrink when over-cover."""
    st = _get_state(key, alpha=alpha, step=step)
    err = 0.0 if covered else 1.0
    alpha_next = st.alpha_t + step * (err - st.alpha_target)
    alpha_next = float(min(0.5, max(0.01, alpha_next)))
    cov_ema = 0.9 * st.coverage_ema + 0.1 * (1.0 - err)
    new = AciState(st.alpha_target, alpha_next, cov_ema, st.step_size)
    _ACI_STATE[key] = new
    return new


def record_conformal_coverage_from_resolution(
    symbol: str,
    realized_return: float,
    conformal_payload: dict[str, object] | None,
) -> dict[str, object]:
    """Update ACI state when a mature snapshot resolves against realized return."""
    if not conformal_payload:
        return {"updated": False, "reason": "no_conformal_payload"}
    sym = (symbol or "global").upper()
    lower_70 = conformal_payload.get("lower_70")
    upper_70 = conformal_payload.get("upper_70")
    lower_90 = conformal_payload.get("lower_90")
    upper_90 = conformal_payload.get("upper_90")
    updated: dict[str, object] = {"updated": False, "symbol": sym}
    try:
        ret = float(realized_return)
        if lower_70 is not None and upper_70 is not None:
            covered_70 = float(lower_70) <= ret <= float(upper_70)
            st70 = update_aci_coverage(f"{sym}:70", covered_70, alpha=0.30)
            updated["aci_70"] = {"covered": covered_70, "alpha_t": st70.alpha_t}
            updated["updated"] = True
        if lower_90 is not None and upper_90 is not None:
            covered_90 = float(lower_90) <= ret <= float(upper_90)
            st90 = update_aci_coverage(f"{sym}:90", covered_90, alpha=0.10)
            updated["aci_90"] = {"covered": covered_90, "alpha_t": st90.alpha_t}
            updated["updated"] = True
    except (TypeError, ValueError):
        updated["reason"] = "invalid_interval_bounds"
    return updated


def adaptive_conformal_interval(
    prices: Sequence[float],
    point_forecast: float,
    *,
    horizon_days: int = 30,
    symbol: str | None = None,
    alpha_90: float = 0.10,
    alpha_70: float = 0.30,
) -> ConformalInterval:
    """ACI-adjusted intervals around the point forecast.

    Uses rolling residual quantiles at adaptive miscoverage levels. Falls back to
    the existing MAPIE/split conformal helper when history is short.
    """
    arr = np.asarray(prices, dtype=float)
    if len(arr) < 40:
        base = compute_conformal_intervals(prices, point_forecast, horizon_days=horizon_days)
        return ConformalInterval(
            horizon_days=base.horizon_days,
            median_return=base.median_return,
            lower_70=base.lower_70,
            upper_70=base.upper_70,
            lower_90=base.lower_90,
            upper_90=base.upper_90,
            method=f"aci_fallback:{base.method}",
            sufficient_data=base.sufficient_data,
        )

    rets = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
    # Walk-forward naive residual vs trailing mean predictor.
    residuals: list[float] = []
    for i in range(20, len(rets)):
        pred = float(np.mean(rets[i - 5 : i]))
        residuals.append(abs(rets[i] - pred))
    resid = np.asarray(residuals, dtype=float)
    key = (symbol or "global").upper()
    st90 = _get_state(f"{key}:90", alpha=alpha_90)
    st70 = _get_state(f"{key}:70", alpha=alpha_70)

    q90 = float(np.quantile(resid, 1.0 - st90.alpha_t))
    q70 = float(np.quantile(resid, 1.0 - st70.alpha_t))
    scale = np.sqrt(min(horizon_days, 10))

    return ConformalInterval(
        horizon_days=horizon_days,
        median_return=point_forecast,
        lower_70=point_forecast - q70 * scale,
        upper_70=point_forecast + q70 * scale,
        lower_90=point_forecast - q90 * scale,
        upper_90=point_forecast + q90 * scale,
        method="adaptive_conformal",
        sufficient_data=True,
    )
