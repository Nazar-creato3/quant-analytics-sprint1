"""Apex portfolio risk math — maintained in-tree, zero upstream runtime dependency.

Adapted from Quantopian empyrical (Apache-2.0) and pyfolio (Apache-2.0).
See ``backend/docs/internal/portfolio_math_provenance.md`` for attribution.
"""
from app.services.risk.portfolio_math.drawdown import max_drawdown
from app.services.risk.portfolio_math.regression import multi_factor_betas, ols_alpha_beta
from app.services.risk.portfolio_math.returns import cumulative_return, simple_returns
from app.services.risk.portfolio_math.var import (
    conditional_var_quantile,
    historical_var_es,
    historical_var_quantile,
)

__all__ = [
    "conditional_var_quantile",
    "cumulative_return",
    "historical_var_es",
    "historical_var_quantile",
    "max_drawdown",
    "multi_factor_betas",
    "ols_alpha_beta",
    "simple_returns",
]
