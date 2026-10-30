"""Portfolio marginal risk engine (Prompt 33)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.market_graph.builder import find_correlated_cluster
from app.services.market_graph.types import GraphEdgeRow
from app.services.prediction_hierarchy.types import MarginalRiskImpact, ProposedPositionChange
from app.services.quant_math import expected_shortfall, portfolio_variance, value_at_risk
from app.services.scenario.portfolio_math import (
    build_covariance_matrix,
    instrument_order,
    portfolio_return_series,
    portfolio_variance_for,
    weight_vector,
    weights_by_instrument,
)
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class WhatIfResult:
    """Output of what_if() — pure evaluation, no execution."""

    delta_var: float
    delta_es: float
    new_concentration_risk: float
    new_correlation_cluster_exposure: float
    component_contributions: dict[int, float]
    baseline_var: float
    new_var: float
    baseline_es: float
    new_es: float


class PortfolioMarginalRiskEngine:
    """Marginal risk contribution and what-if analysis."""

    def __init__(
        self,
        *,
        risk_engine: RiskEngine | None = None,
        var_alpha: float = 0.95,
        correlation_threshold: float = 0.7,
    ) -> None:
        self._risk_engine = risk_engine or get_risk_engine()
        self._var_alpha = var_alpha
        self._correlation_threshold = correlation_threshold

    def marginal_risk_contribution(
        self,
        portfolio: PortfolioSnapshot,
        *,
        alpha: float | None = None,
    ) -> dict[int, float]:
        """Component risk contribution: w_i * (Σw)_i / portfolio_variance."""
        alpha = alpha or self._var_alpha
        order = instrument_order(portfolio)
        if not order:
            return {}

        weights = weight_vector(portfolio, order)
        sigma = build_covariance_matrix(portfolio.returns_by_instrument, order)
        var = portfolio_variance(weights, sigma)
        if var <= 0.0:
            return {instrument_id: 0.0 for instrument_id in order}

        sigma_w = [
            sum(sigma[row][col] * weights[col] for col in range(len(order)))
            for row in range(len(order))
        ]
        contributions = {
            order[index]: (weights[index] * sigma_w[index]) / var
            for index in range(len(order))
        }
        return contributions

    def what_if(
        self,
        portfolio: PortfolioSnapshot,
        proposed_change: ProposedPositionChange,
        *,
        correlation_edges: Sequence[GraphEdgeRow] = (),
        alpha: float | None = None,
    ) -> WhatIfResult:
        """Evaluate portfolio risk change from a proposed position adjustment."""
        alpha = alpha or self._var_alpha
        baseline_positions = list(portfolio.positions)
        new_positions = self._apply_change(baseline_positions, proposed_change)
        new_portfolio = PortfolioSnapshot(
            positions=tuple(new_positions),
            factor_exposures=portfolio.factor_exposures,
            returns_by_instrument=portfolio.returns_by_instrument,
            sector_by_instrument=portfolio.sector_by_instrument,
        )

        baseline_var = self._portfolio_var(portfolio)
        new_var = self._portfolio_var(new_portfolio)
        baseline_returns = self._portfolio_returns(portfolio)
        new_returns = self._portfolio_returns(new_portfolio)

        baseline_var_metric = value_at_risk(baseline_returns, alpha) if baseline_returns else 0.0
        new_var_metric = value_at_risk(new_returns, alpha) if new_returns else 0.0
        baseline_es = (
            expected_shortfall(baseline_returns, alpha, baseline_var_metric)
            if baseline_returns
            else 0.0
        )
        new_es = (
            expected_shortfall(new_returns, alpha, new_var_metric) if new_returns else 0.0
        )

        contributions = self.marginal_risk_contribution(new_portfolio, alpha=alpha)
        concentration = self._concentration_risk(new_portfolio)
        cluster_exposure = self._correlation_cluster_exposure(
            proposed_change.instrument_id,
            new_portfolio,
            correlation_edges,
        )

        return WhatIfResult(
            delta_var=round(new_var_metric - baseline_var_metric, 6),
            delta_es=round(new_es - baseline_es, 6),
            new_concentration_risk=concentration,
            new_correlation_cluster_exposure=cluster_exposure,
            component_contributions=contributions,
            baseline_var=baseline_var,
            new_var=new_var,
            baseline_es=baseline_es,
            new_es=new_es,
        )

    @staticmethod
    def _apply_change(
        positions: list[PortfolioPosition],
        change: ProposedPositionChange,
    ) -> list[PortfolioPosition]:
        weight_map = weights_by_instrument(positions)
        current = weight_map.get(change.instrument_id, 0.0)
        if change.new_weight is not None:
            new_weight = change.new_weight
        else:
            new_weight = current + change.delta_weight

        updated = [
            PortfolioPosition(
                instrument_id=position.instrument_id,
                sleeve_id=position.sleeve_id,
                weight=position.weight,
            )
            for position in positions
            if position.instrument_id != change.instrument_id
        ]
        if new_weight > 0.0:
            updated.append(
                PortfolioPosition(
                    instrument_id=change.instrument_id,
                    sleeve_id=change.sleeve_id,
                    weight=new_weight,
                )
            )
        return updated

    @staticmethod
    def _portfolio_var(portfolio: PortfolioSnapshot) -> float:
        try:
            return portfolio_variance_for(portfolio)
        except ValueError:
            return 0.0

    @staticmethod
    def _portfolio_returns(portfolio: PortfolioSnapshot) -> list[float]:
        weights = weights_by_instrument(portfolio.positions)
        return portfolio_return_series(portfolio.returns_by_instrument, weights)

    @staticmethod
    def _concentration_risk(portfolio: PortfolioSnapshot) -> float:
        weights = weights_by_instrument(portfolio.positions)
        if not weights:
            return 0.0
        return max(weights.values()) * 100.0

    def _correlation_cluster_exposure(
        self,
        instrument_id: int,
        portfolio: PortfolioSnapshot,
        edges: Sequence[GraphEdgeRow],
    ) -> float:
        cluster = find_correlated_cluster(
            instrument_id,
            edges,
            threshold=self._correlation_threshold,
        )
        weights = weights_by_instrument(portfolio.positions)
        cluster_weight = sum(weights.get(peer_id, 0.0) for peer_id in cluster)
        return round(cluster_weight * 100.0, 4)

    def to_marginal_impact(self, result: WhatIfResult) -> MarginalRiskImpact:
        return MarginalRiskImpact(
            delta_var=result.delta_var,
            delta_es=result.delta_es,
            component_contributions=result.component_contributions,
            new_concentration_risk=result.new_concentration_risk,
            new_correlation_cluster_exposure=result.new_correlation_cluster_exposure,
        )


_engine = PortfolioMarginalRiskEngine()


def get_marginal_risk_engine() -> PortfolioMarginalRiskEngine:
    return _engine
