"""RiskEngine — full risk metrics for Control Fabric RiskGate (Prompt 23).

Extends RiskGate with VaR/ES, drawdown, tail, factor, concentration, correlation,
liquidity, event, gap, and contagion metrics. AntiLossGuard and ApprovalPolicyEngine
query this engine before DealIntent decisions — no parallel decision path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain.enums import AssetCategory
from app.services.control_fabric.anti_loss_guard import CORRELATION_CLUSTER_THRESHOLD
from app.services.control_fabric.risk_types import (
    InstrumentRiskAssessment,
    PortfolioRiskAssessment,
    RiskBudgetContext,
    RiskEngineInput,
    RiskMetricAssessment,
)
from app.services.factor.types import ALL_FACTORS, FactorName
from app.services.forecast.signals import compute_tail_risk_score
from app.services.market_graph.builder import find_correlated_cluster
from app.services.market_graph.types import EdgeType, GraphEdgeRow
from app.services.quant_math import expected_shortfall, value_at_risk
from app.services.scenario.engine import ScenarioEngine
from app.services.scenario.portfolio_math import portfolio_return_series, weights_by_instrument
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot, ScenarioName


DEFAULT_VAR_ALPHAS: tuple[float, ...] = (0.95, 0.99)
DEFAULT_MAX_VAR_95 = 0.05
DEFAULT_MAX_VAR_99 = 0.08
DEFAULT_MAX_ES_95 = 0.07
DEFAULT_MAX_ES_99 = 0.10
DEFAULT_MAX_TAIL_RISK = 0.75
DEFAULT_MAX_FACTOR_CONCENTRATION = 0.60
DEFAULT_MAX_PCT_PER_INSTRUMENT = 25.0
DEFAULT_MAX_PCT_PER_SECTOR = 50.0
DEFAULT_MAX_PCT_PER_SLEEVE = 60.0
DEFAULT_MAX_CORRELATION_CLUSTER_PCT = 25.0
DEFAULT_MAX_LIQUIDITY_RISK = 0.70
DEFAULT_MAX_EVENT_RISK = 0.50
DEFAULT_MAX_GAP_RISK = 0.15
DEFAULT_MAX_CONTAGION_RISK = 0.08
DEFAULT_GAP_SIGMA_THRESHOLD = 2.0


@dataclass(frozen=True, slots=True)
class RiskEngineConfig:
    """Default metric thresholds when not overridden by profile policy."""

    var_alphas: tuple[float, ...] = DEFAULT_VAR_ALPHAS
    max_var_95: float = DEFAULT_MAX_VAR_95
    max_var_99: float = DEFAULT_MAX_VAR_99
    max_es_95: float = DEFAULT_MAX_ES_95
    max_es_99: float = DEFAULT_MAX_ES_99
    max_tail_risk: float = DEFAULT_MAX_TAIL_RISK
    max_factor_concentration: float = DEFAULT_MAX_FACTOR_CONCENTRATION
    max_pct_per_instrument: float = DEFAULT_MAX_PCT_PER_INSTRUMENT
    max_pct_per_sector: float = DEFAULT_MAX_PCT_PER_SECTOR
    max_pct_per_sleeve: float = DEFAULT_MAX_PCT_PER_SLEEVE
    max_correlation_cluster_pct: float = DEFAULT_MAX_CORRELATION_CLUSTER_PCT
    max_liquidity_risk: float = DEFAULT_MAX_LIQUIDITY_RISK
    max_event_risk: float = DEFAULT_MAX_EVENT_RISK
    max_gap_risk: float = DEFAULT_MAX_GAP_RISK
    max_contagion_risk: float = DEFAULT_MAX_CONTAGION_RISK
    gap_sigma_threshold: float = DEFAULT_GAP_SIGMA_THRESHOLD
    correlation_cluster_threshold: float = CORRELATION_CLUSTER_THRESHOLD


def _metric(
    name: str,
    value: float,
    threshold: float,
    *,
    scope: str,
    metadata: dict | None = None,
) -> RiskMetricAssessment:
    return RiskMetricAssessment(
        name=name,
        value=value,
        threshold=threshold,
        exceeded=value > threshold,
        scope=scope,  # type: ignore[arg-type]
        metadata=metadata or {},
    )


def compute_drawdown_risk(prices: Sequence[float]) -> float:
    """Current drawdown relative to historical peak (0 = at peak, 1 = total loss)."""
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_drawdown = 0.0
    for price in prices:
        if price > peak:
            peak = price
        if peak <= 0:
            continue
        drawdown = (peak - price) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max(0.0, min(1.0, max_drawdown))


def compute_gap_risk_probability(
    overnight_returns: Sequence[float],
    *,
    sigma_threshold: float = DEFAULT_GAP_SIGMA_THRESHOLD,
) -> float:
    """Probability of an overnight gap exceeding sigma_threshold × typical move.

    Baseline volatility is estimated from the lower 75% of absolute moves so
    occasional gaps do not inflate the reference scale.
    """
    values = list(overnight_returns)
    if len(values) < 5:
        return 0.0

    abs_returns = sorted(abs(value) for value in values)
    cutoff_idx = max(2, int(len(abs_returns) * 0.75))
    baseline_sample = abs_returns[:cutoff_idx]
    mean_b = sum(baseline_sample) / len(baseline_sample)
    if len(baseline_sample) >= 2:
        var_b = sum((value - mean_b) ** 2 for value in baseline_sample) / (len(baseline_sample) - 1)
        baseline = max(mean_b, var_b ** 0.5)
    else:
        baseline = mean_b
    if baseline <= 0:
        return 0.0

    threshold = sigma_threshold * baseline
    gap_count = sum(1 for value in abs_returns if value >= threshold)
    return gap_count / len(abs_returns)


def compute_factor_concentration(
    positions: Sequence[PortfolioPosition],
    factor_exposures: Mapping[int, Mapping[FactorName, float]],
) -> tuple[float, dict[str, float]]:
    """Max absolute weighted factor exposure — concentration in one factor."""
    weights = weights_by_instrument(positions)
    if not weights:
        return 0.0, {}

    factor_totals: dict[str, float] = {factor.value: 0.0 for factor in ALL_FACTORS}
    for instrument_id, weight in weights.items():
        exposures = factor_exposures.get(instrument_id, {})
        for factor in ALL_FACTORS:
            factor_totals[factor.value] += weight * exposures.get(factor, 0.0)

    max_concentration = max((abs(value) for value in factor_totals.values()), default=0.0)
    return max_concentration, factor_totals


def compute_concentration_pct(
    positions: Sequence[PortfolioPosition],
    *,
    sector_by_instrument: Mapping[int, str],
    group_key: str,
) -> float:
    """Largest weight share by instrument, sector, or sleeve (% of portfolio)."""
    if not positions:
        return 0.0

    totals: dict[str | int, float] = {}
    for position in positions:
        if group_key == "instrument":
            key: str | int = position.instrument_id
        elif group_key == "sleeve":
            key = position.sleeve_id
        else:
            key = sector_by_instrument.get(position.instrument_id, "unknown")
        totals[key] = totals.get(key, 0.0) + position.weight

    return max(totals.values(), default=0.0) * 100.0


def compute_correlation_cluster_weight(
    instrument_id: int,
    positions: Sequence[PortfolioPosition],
    correlation_edges: Sequence[GraphEdgeRow] | None,
    *,
    threshold: float,
    proposed_weight: float = 0.0,
) -> float:
    """Portfolio weight in the correlated cluster around instrument_id."""
    if not positions:
        return proposed_weight

    cluster_ids: set[int]
    if correlation_edges:
        cluster_ids = set(
            find_correlated_cluster(instrument_id, correlation_edges, threshold=threshold)
        )
    else:
        cluster_ids = {instrument_id}

    cluster_weight = sum(
        position.weight
        for position in positions
        if position.instrument_id in cluster_ids
    )
    if instrument_id in cluster_ids and not any(
        position.instrument_id == instrument_id for position in positions
    ):
        cluster_weight += proposed_weight
    elif proposed_weight > 0 and instrument_id not in {
        position.instrument_id for position in positions
    }:
        cluster_weight += proposed_weight
    return cluster_weight


def compute_contagion_risk(portfolio: PortfolioSnapshot) -> float:
    """Normalized contagion score from correlation_breakdown scenario."""
    if not portfolio.positions:
        return 0.0
    engine = ScenarioEngine()
    result = engine.run(ScenarioName.CORRELATION_BREAKDOWN, portfolio)
    return min(1.0, abs(result.estimated_pnl_impact) + result.portfolio_variance_delta)


def _portfolio_returns(inputs: RiskEngineInput) -> list[float]:
    weights = weights_by_instrument(inputs.positions)
    if not weights:
        target_returns = inputs.returns_by_instrument.get(inputs.instrument_id, [])
        return list(target_returns)
    return portfolio_return_series(inputs.returns_by_instrument, weights)


def _resolve_thresholds(
    budget: RiskBudgetContext,
    config: RiskEngineConfig,
) -> dict[str, float]:
    policy = budget.diversification_policy or {}
    return {
        "max_var_95": float(policy.get("max_var_95", config.max_var_95)),
        "max_var_99": float(policy.get("max_var_99", config.max_var_99)),
        "max_es_95": float(policy.get("max_es_95", config.max_es_95)),
        "max_es_99": float(policy.get("max_es_99", config.max_es_99)),
        "max_drawdown_risk": float(
            policy.get("max_drawdown_risk", budget.max_drawdown_pct / 100.0)
        ),
        "max_tail_risk": float(policy.get("max_tail_risk_score", config.max_tail_risk)),
        "max_factor_concentration": float(
            policy.get("max_factor_concentration", config.max_factor_concentration)
        ),
        "max_pct_per_instrument": float(
            policy.get("max_pct_per_instrument", config.max_pct_per_instrument)
        ),
        "max_pct_per_sector": float(
            policy.get("max_pct_per_sector", config.max_pct_per_sector)
        ),
        "max_pct_per_sleeve": float(
            policy.get("max_pct_per_sleeve", config.max_pct_per_sleeve)
        ),
        "max_correlation_cluster_pct": float(
            policy.get("max_correlation_cluster_pct", config.max_correlation_cluster_pct)
        ),
        "max_liquidity_risk": float(
            policy.get("max_liquidity_risk_score", config.max_liquidity_risk)
        ),
        "max_event_risk": float(policy.get("max_event_risk", config.max_event_risk)),
        "max_gap_risk": float(policy.get("max_gap_risk_prob", config.max_gap_risk)),
        "max_contagion_risk": float(
            policy.get("max_contagion_risk", config.max_contagion_risk)
        ),
    }


class RiskEngine:
    """Compute per-instrument and per-portfolio risk metrics with threshold checks."""

    def __init__(self, *, config: RiskEngineConfig | None = None) -> None:
        self._config = config or RiskEngineConfig()
        self._scenario_engine = ScenarioEngine()

    def assess(
        self,
        inputs: RiskEngineInput,
        budget: RiskBudgetContext,
    ) -> PortfolioRiskAssessment:
        """Compute full risk assessment for portfolio and intent instrument."""
        thresholds = _resolve_thresholds(budget, self._config)
        portfolio_metrics = self._assess_portfolio(inputs, budget, thresholds)
        instrument_metrics = self._assess_instrument(inputs, thresholds)
        return PortfolioRiskAssessment(
            metrics=portfolio_metrics,
            instrument_assessments=(instrument_metrics,),
        )

    def first_breach(
        self,
        assessment: PortfolioRiskAssessment,
    ) -> RiskMetricAssessment | None:
        """Return the first exceeded metric, or None when all within limits."""
        breached = assessment.breached
        return breached[0] if breached else None

    def _assess_portfolio(
        self,
        inputs: RiskEngineInput,
        budget: RiskBudgetContext,
        thresholds: dict[str, float],
    ) -> tuple[RiskMetricAssessment, ...]:
        metrics: list[RiskMetricAssessment] = []
        portfolio_returns = _portfolio_returns(inputs)

        for alpha in self._config.var_alphas:
            label = int(alpha * 100)
            if len(portfolio_returns) >= 5:
                var_value = value_at_risk(portfolio_returns, alpha)
                es_value = expected_shortfall(portfolio_returns, alpha, var_value)
            else:
                var_value = 0.0
                es_value = 0.0

            var_key = f"var_{label}"
            es_key = f"es_{label}"
            metrics.append(
                _metric(
                    var_key,
                    var_value,
                    thresholds.get(var_key, thresholds["max_var_95"]),
                    scope="portfolio",
                    metadata={"alpha": alpha},
                )
            )
            metrics.append(
                _metric(
                    es_key,
                    es_value,
                    thresholds.get(es_key, thresholds["max_es_95"]),
                    scope="portfolio",
                    metadata={"alpha": alpha},
                )
            )

        factor_conc, factor_totals = compute_factor_concentration(
            inputs.positions,
            inputs.factor_exposures,
        )
        metrics.append(
            _metric(
                "factor_concentration_risk",
                factor_conc,
                thresholds["max_factor_concentration"],
                scope="portfolio",
                metadata={"factor_exposures": factor_totals},
            )
        )

        metrics.append(
            _metric(
                "concentration_instrument",
                compute_concentration_pct(
                    inputs.positions,
                    sector_by_instrument=inputs.sector_by_instrument,
                    group_key="instrument",
                ),
                thresholds["max_pct_per_instrument"],
                scope="portfolio",
            )
        )
        metrics.append(
            _metric(
                "concentration_sector",
                compute_concentration_pct(
                    inputs.positions,
                    sector_by_instrument=inputs.sector_by_instrument,
                    group_key="sector",
                ),
                thresholds["max_pct_per_sector"],
                scope="portfolio",
            )
        )
        metrics.append(
            _metric(
                "concentration_sleeve",
                compute_concentration_pct(
                    inputs.positions,
                    sector_by_instrument=inputs.sector_by_instrument,
                    group_key="sleeve",
                ),
                thresholds["max_pct_per_sleeve"],
                scope="portfolio",
            )
        )

        cluster_weight = compute_correlation_cluster_weight(
            inputs.instrument_id,
            inputs.positions,
            inputs.correlation_edges,
            threshold=inputs.correlation_threshold,
            proposed_weight=inputs.proposed_weight,
        )
        metrics.append(
            _metric(
                "correlation_risk",
                cluster_weight * 100.0,
                thresholds["max_correlation_cluster_pct"],
                scope="portfolio",
                metadata={"cluster_weight": cluster_weight},
            )
        )

        if inputs.positions:
            portfolio_snapshot = PortfolioSnapshot(
                positions=inputs.positions,
                factor_exposures=inputs.factor_exposures,
                returns_by_instrument=inputs.returns_by_instrument,
                sector_by_instrument=inputs.sector_by_instrument or None,
            )
            contagion = compute_contagion_risk(portfolio_snapshot)
        else:
            contagion = 0.0
        metrics.append(
            _metric(
                "portfolio_contagion_risk",
                contagion,
                thresholds["max_contagion_risk"],
                scope="portfolio",
            )
        )

        return tuple(metrics)

    def _assess_instrument(
        self,
        inputs: RiskEngineInput,
        thresholds: dict[str, float],
    ) -> InstrumentRiskAssessment:
        instrument_id = inputs.instrument_id
        metrics: list[RiskMetricAssessment] = []

        returns = inputs.returns_by_instrument.get(instrument_id, [])
        for alpha in self._config.var_alphas:
            label = int(alpha * 100)
            if len(returns) >= 5:
                var_value = value_at_risk(returns, alpha)
                es_value = expected_shortfall(returns, alpha, var_value)
            else:
                var_value = 0.0
                es_value = 0.0
            metrics.append(
                _metric(
                    f"var_{label}",
                    var_value,
                    thresholds.get(f"var_{label}", thresholds["max_var_95"]),
                    scope="instrument",
                    metadata={"alpha": alpha, "instrument_id": instrument_id},
                )
            )
            metrics.append(
                _metric(
                    f"es_{label}",
                    es_value,
                    thresholds.get(f"es_{label}", thresholds["max_es_95"]),
                    scope="instrument",
                    metadata={"alpha": alpha, "instrument_id": instrument_id},
                )
            )

        prices = inputs.prices_by_instrument.get(instrument_id, [])
        drawdown = compute_drawdown_risk(prices) if prices else 0.0
        metrics.append(
            _metric(
                "drawdown_risk",
                drawdown,
                thresholds["max_drawdown_risk"],
                scope="instrument",
                metadata={"instrument_id": instrument_id},
            )
        )

        if inputs.tail_risk_score is not None:
            tail = inputs.tail_risk_score
        elif len(returns) >= 5:
            tail = compute_tail_risk_score(returns)
        else:
            tail = 0.0
        metrics.append(
            _metric(
                "tail_risk",
                tail,
                thresholds["max_tail_risk"],
                scope="instrument",
                metadata={"instrument_id": instrument_id},
            )
        )

        liquidity = inputs.liquidity_risk_score if inputs.liquidity_risk_score is not None else 0.0
        metrics.append(
            _metric(
                "liquidity_risk",
                liquidity,
                thresholds["max_liquidity_risk"],
                scope="instrument",
                metadata={"instrument_id": instrument_id},
            )
        )

        event_score = 1.0 if (
            inputs.event_risk_active or instrument_id in inputs.active_lock_instrument_ids
        ) else 0.0
        metrics.append(
            _metric(
                "event_risk",
                event_score,
                thresholds["max_event_risk"],
                scope="instrument",
                metadata={"instrument_id": instrument_id, "locked": event_score > 0},
            )
        )

        is_equity = inputs.asset_category in {AssetCategory.EQUITIES, AssetCategory.ETF, None}
        overnight = inputs.overnight_returns_by_instrument.get(instrument_id, [])
        if is_equity and overnight:
            gap_prob = compute_gap_risk_probability(
                overnight,
                sigma_threshold=self._config.gap_sigma_threshold,
            )
        else:
            gap_prob = 0.0
        metrics.append(
            _metric(
                "gap_risk",
                gap_prob,
                thresholds["max_gap_risk"],
                scope="instrument",
                metadata={"instrument_id": instrument_id},
            )
        )

        return InstrumentRiskAssessment(instrument_id=instrument_id, metrics=tuple(metrics))

    def marginal_risk_contribution(
        self,
        portfolio: PortfolioSnapshot,
        *,
        alpha: float = 0.95,
    ) -> dict[int, float]:
        """Component risk contribution via PortfolioMarginalRiskEngine (Prompt 33)."""
        from app.services.prediction_hierarchy.marginal_risk import get_marginal_risk_engine

        return get_marginal_risk_engine().marginal_risk_contribution(portfolio, alpha=alpha)

    def what_if(
        self,
        portfolio: PortfolioSnapshot,
        proposed_change,
        *,
        correlation_edges=None,
        alpha: float = 0.95,
    ):
        """Evaluate delta VaR/ES for a proposed position change (Prompt 33)."""
        from app.services.prediction_hierarchy.marginal_risk import get_marginal_risk_engine

        return get_marginal_risk_engine().what_if(
            portfolio,
            proposed_change,
            correlation_edges=correlation_edges or (),
            alpha=alpha,
        )


_engine = RiskEngine()


def get_risk_engine() -> RiskEngine:
    return _engine
