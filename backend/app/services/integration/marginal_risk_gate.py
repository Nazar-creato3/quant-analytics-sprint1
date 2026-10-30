"""Mandatory marginal-risk gate for DealIntent sizing (Prompt 33)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.models import MarketContext
from app.services.integration.types import HistoricalBar, VenueConfig
from app.services.prediction_hierarchy.marginal_risk import PortfolioMarginalRiskEngine
from app.services.prediction_hierarchy.types import ProposedPositionChange
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot


DEFAULT_INTENT_DELTA_WEIGHT = 0.05
_MARGINAL_ENGINE = PortfolioMarginalRiskEngine()


def intent_delta_weight(intent_size_usd: float | Decimal | None, *, total_capital_usd: float = 100_000.0) -> float:
    """Map absolute sizing intent to portfolio weight delta."""
    if intent_size_usd is None:
        return DEFAULT_INTENT_DELTA_WEIGHT
    size = float(intent_size_usd)
    if size <= 0 or total_capital_usd <= 0:
        return 0.0
    return min(1.0, max(0.0, size / total_capital_usd))


def build_portfolio_snapshot(
    bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    *,
    target: VenueConfig,
    index: int,
    sleeve_id: str,
    existing_weight: float = 0.0,
) -> PortfolioSnapshot:
    """Minimal portfolio snapshot for what_if from historical bars."""
    returns_by_instrument: dict[int, list[float]] = {}
    for instrument_id, bars in bars_by_instrument.items():
        if index >= len(bars):
            continue
        closes = [bar.close for bar in bars[: index + 1]]
        if len(closes) < 2:
            continue
        series = [
            (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-9)
            for i in range(1, len(closes))
        ]
        if series:
            returns_by_instrument[instrument_id] = series

    positions: list[PortfolioPosition] = []
    if existing_weight > 0:
        positions.append(
            PortfolioPosition(
                instrument_id=target.instrument_id,
                sleeve_id=sleeve_id,
                weight=existing_weight,
            )
        )

    return PortfolioSnapshot(
        positions=tuple(positions),
        factor_exposures={},
        returns_by_instrument=returns_by_instrument,
    )


def compute_marginal_risk_fields(
    *,
    bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    target: VenueConfig,
    index: int,
    profile: ProfileRead,
    sleeve: SleeveRead,
    delta_weight: float,
    correlation_edges: Sequence = (),
    remaining_risk_budget_var: float | None = None,
) -> tuple[float, float | None]:
    """Return (proposed_delta_var, remaining_risk_budget_var) for approval gates."""
    if delta_weight <= 0:
        return 0.0, remaining_risk_budget_var

    portfolio = build_portfolio_snapshot(
        bars_by_instrument,
        target=target,
        index=index,
        sleeve_id=sleeve.id,
    )
    change = ProposedPositionChange(
        instrument_id=target.instrument_id,
        sleeve_id=sleeve.id,
        delta_weight=delta_weight,
    )
    result = _MARGINAL_ENGINE.what_if(
        portfolio,
        change,
        correlation_edges=correlation_edges,
    )
    budget = remaining_risk_budget_var
    if budget is None and sleeve.risk_budget is not None:
        budget = float(sleeve.risk_budget)
    if budget is None and profile.max_drawdown_pct is not None:
        budget = float(profile.max_drawdown_pct) / 100.0
    return result.delta_var, budget


def enrich_market_context_with_marginal_risk(
    context: MarketContext,
    *,
    bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    target: VenueConfig,
    index: int,
    profile: ProfileRead,
    sleeve: SleeveRead,
    delta_weight: float,
    correlation_edges: Sequence = (),
) -> MarketContext:
    """Attach computed proposed_delta_var — mandatory for sizing-changing intents."""
    proposed_delta_var, remaining = compute_marginal_risk_fields(
        bars_by_instrument=bars_by_instrument,
        target=target,
        index=index,
        profile=profile,
        sleeve=sleeve,
        delta_weight=delta_weight,
        correlation_edges=correlation_edges,
        remaining_risk_budget_var=context.remaining_risk_budget_var,
    )
    return replace(
        context,
        proposed_delta_var=proposed_delta_var,
        remaining_risk_budget_var=remaining,
        marginal_risk_computed=True,
    )
