"""Monte Carlo portfolio P&L distribution runner."""
from __future__ import annotations

import math
import random

from app.services.quant_math import historical_volatility
from app.services.scenario.portfolio_math import portfolio_return_series, weights_by_instrument
from app.services.scenario.types import (
    MonteCarloMethod,
    MonteCarloResult,
    PercentileBands,
    PortfolioSnapshot,
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(0, min(len(sorted_values) - 1, math.ceil(percentile / 100.0 * len(sorted_values)) - 1))
    return sorted_values[rank]


def run_monte_carlo(
    portfolio: PortfolioSnapshot,
    *,
    n_simulations: int,
    method: MonteCarloMethod = MonteCarloMethod.BOOTSTRAP,
    seed: int | None = None,
) -> MonteCarloResult:
    """Generate N random portfolio P&L outcomes from historical return distribution."""
    if n_simulations < 1:
        raise ValueError("n_simulations must be >= 1.")

    weight_map = weights_by_instrument(portfolio.positions)
    historical = portfolio_return_series(portfolio.returns_by_instrument, weight_map)
    if not historical:
        zero = PercentileBands(p5=0.0, p25=0.0, p50=0.0, p75=0.0, p95=0.0)
        return MonteCarloResult(
            method=method,
            n_simulations=n_simulations,
            percentile_bands=zero,
            mean_pnl=0.0,
            std_pnl=0.0,
        )

    rng = random.Random(seed)
    mean_return = sum(historical) / len(historical)
    std_return = historical_volatility(historical)

    simulated: list[float] = []
    for _ in range(n_simulations):
        if method == MonteCarloMethod.BOOTSTRAP:
            simulated.append(rng.choice(historical))
        elif method == MonteCarloMethod.PARAMETRIC:
            draw = rng.gauss(mean_return, std_return if std_return > 0.0 else 1e-9)
            simulated.append(draw)
        else:
            raise ValueError(f"Unsupported Monte Carlo method: {method!r}.")

    mean_pnl = sum(simulated) / len(simulated)
    std_pnl = historical_volatility(simulated) if len(simulated) >= 2 else 0.0
    bands = PercentileBands(
        p5=_percentile(simulated, 5.0),
        p25=_percentile(simulated, 25.0),
        p50=_percentile(simulated, 50.0),
        p75=_percentile(simulated, 75.0),
        p95=_percentile(simulated, 95.0),
    )
    return MonteCarloResult(
        method=method,
        n_simulations=n_simulations,
        percentile_bands=bands,
        mean_pnl=mean_pnl,
        std_pnl=std_pnl,
    )
