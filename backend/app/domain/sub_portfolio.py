"""Sub-portfolio segmentation (Prompt 60) — plan only, no live execution."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class SubPortfolioORM(Base):
    __tablename__ = "sub_portfolios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_budget: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    strategy_tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    master_portfolio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sub_portfolios.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SubPortfolioCreate(BaseModel):
    profile_id: str
    name: str
    risk_budget: float = Field(gt=0, le=10)
    strategy_tags: list[str] = Field(default_factory=list)
    is_master: bool = False
    master_portfolio_id: str | None = None


class SubPortfolioRead(BaseModel):
    id: str
    profile_id: str
    name: str
    risk_budget: float
    strategy_tags: list[str]
    is_master: bool
    master_portfolio_id: str | None = None
    diversification_score: float | None = None

    model_config = {"from_attributes": True}


class RebalancePlanItem(BaseModel):
    sub_portfolio_id: str
    name: str
    current_risk_budget: float
    suggested_risk_budget: float
    delta: float


class RebalancePlan(BaseModel):
    profile_id: str
    items: list[RebalancePlanItem]
    note: str = "Plan only — requires DealIntent flow to execute."


def diversification_score(
    *,
    strategy_tags: list[str],
    peer_tags: list[list[str]],
    risk_budget: float,
) -> float:
    """Heuristic 0-1 score using tag uniqueness + risk concentration (no live RiskEngine call required)."""
    if risk_budget <= 0:
        return 0.0
    own = set(t.lower() for t in strategy_tags)
    if not own:
        return 0.35
    overlap = 0
    for tags in peer_tags:
        peer = set(t.lower() for t in tags)
        if own & peer:
            overlap += 1
    uniqueness = 1.0 / (1.0 + overlap)
    concentration_penalty = min(1.0, risk_budget / 3.0)
    score = uniqueness * (1.0 - 0.4 * concentration_penalty)
    return round(max(0.0, min(1.0, score)), 4)


def rebalance_subportfolios_plan(
    profile_id: str,
    portfolios: list[SubPortfolioORM],
) -> RebalancePlan:
    if not portfolios:
        return RebalancePlan(profile_id=profile_id, items=[])
    total = sum(max(0.01, p.risk_budget) for p in portfolios)
    target_each = 1.0  # normalize suggestion around equal risk units scaled
    equal = total / len(portfolios)
    items: list[RebalancePlanItem] = []
    for p in portfolios:
        suggested = round(equal, 4)
        items.append(
            RebalancePlanItem(
                sub_portfolio_id=p.id,
                name=p.name,
                current_risk_budget=p.risk_budget,
                suggested_risk_budget=suggested,
                delta=round(suggested - p.risk_budget, 4),
            )
        )
    return RebalancePlan(profile_id=profile_id, items=items)
