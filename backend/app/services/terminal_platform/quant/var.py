"""Value-at-Risk: historical, parametric, and Monte Carlo."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.quant_math import VaRMethod, expected_shortfall, value_at_risk
from app.services.terminal_platform.quant.models import ReturnSeries, VaRMethodName, VaRResult


def historical_var(
    returns: ReturnSeries | Sequence[float],
    confidence_level: float = 0.95,
) -> VaRResult:
    """Historical VaR (positive loss magnitude) + CVaR."""
    values = _values(returns)
    _validate_confidence(confidence_level)
    var = max(0.0, float(value_at_risk(values, confidence_level, method=VaRMethod.HISTORICAL)))
    cvar = float(expected_shortfall(values, confidence_level, var))
    try:
        from app.services.qa.feature_flags import is_enabled
        from app.services.risk_engine.shadow import shadow_compare

        if is_enabled("qa_risk_engine"):
            shadow_compare(values)
    except Exception:
        pass
    return VaRResult(
        method=VaRMethodName.HISTORICAL,
        confidence=confidence_level,
        var=var,
        cvar=cvar,
        metadata={"n_observations": len(values)},
    )


def parametric_var(
    returns: ReturnSeries | Sequence[float],
    confidence_level: float = 0.95,
) -> VaRResult:
    """Parametric (normal) VaR wrapping quant_math."""
    values = _values(returns)
    _validate_confidence(confidence_level)
    var = float(value_at_risk(values, confidence_level, method=VaRMethod.PARAMETRIC))
    # ES under normality approximation from simulated tail of the fitted distribution.
    cvar = float(expected_shortfall(values, confidence_level, max(var, 0.0)))
    return VaRResult(
        method=VaRMethodName.PARAMETRIC,
        confidence=confidence_level,
        var=max(0.0, var),
        cvar=max(0.0, cvar),
        metadata={"n_observations": len(values)},
    )


def monte_carlo_var(
    returns: ReturnSeries | Sequence[float],
    confidence_level: float = 0.95,
    n_simulations: int = 10_000,
    *,
    seed: int | None = 42,
    horizon_periods: int = 1,
) -> VaRResult:
    """Monte Carlo VaR: simulate i.i.d. normal paths from sample μ, σ."""
    values = _values(returns)
    _validate_confidence(confidence_level)
    if n_simulations < 100:
        raise ValueError("n_simulations must be >= 100")
    if horizon_periods < 1:
        raise ValueError("horizon_periods must be >= 1")

    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    rng = np.random.default_rng(seed)

    # Horizon return ≈ sum of i.i.d. period returns.
    shocks = rng.normal(loc=mu, scale=max(sigma, 0.0), size=(n_simulations, horizon_periods))
    simulated = shocks.sum(axis=1)
    losses = -simulated
    var = float(np.quantile(losses, confidence_level))
    tail = losses[losses >= var]
    cvar = float(np.mean(tail)) if len(tail) else var

    return VaRResult(
        method=VaRMethodName.MONTE_CARLO,
        confidence=confidence_level,
        var=max(0.0, var),
        cvar=max(0.0, cvar),
        horizon_periods=horizon_periods,
        n_simulations=n_simulations,
        metadata={"mu": mu, "sigma": sigma, "seed": seed},
    )


def compute_var(
    returns: ReturnSeries | Sequence[float],
    confidence_level: float = 0.95,
    *,
    method: VaRMethodName | str = VaRMethodName.HISTORICAL,
    n_simulations: int = 10_000,
    seed: int | None = 42,
) -> VaRResult:
    """Dispatch helper for API / risk manager."""
    method_name = VaRMethodName(method) if not isinstance(method, VaRMethodName) else method
    if method_name is VaRMethodName.HISTORICAL:
        return historical_var(returns, confidence_level)
    if method_name is VaRMethodName.PARAMETRIC:
        return parametric_var(returns, confidence_level)
    if method_name is VaRMethodName.MONTE_CARLO:
        return monte_carlo_var(
            returns,
            confidence_level,
            n_simulations=n_simulations,
            seed=seed,
        )
    raise ValueError(f"unsupported VaR method: {method_name}")


def _values(returns: ReturnSeries | Sequence[float]) -> list[float]:
    if isinstance(returns, ReturnSeries):
        return list(returns.values)
    return [float(v) for v in returns]


def _validate_confidence(confidence: float) -> None:
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence_level must be in (0, 1)")
