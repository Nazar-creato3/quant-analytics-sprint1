"""StressHarness API — on-demand portfolio stress testing (Prompt 27)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.db.models import User
from app.schemas.stress_harness import CustomScenarioIn, PositionReviewOut, ScenarioImpactOut, StressReportOut
from app.services.stress_harness import CustomScenarioRequest, StressHarness
from app.services.stress_harness.types import StressReport

router = APIRouter(prefix="/stress-harness", tags=["stress-harness"])
_service = StressHarness()


async def _profile_id_for_email(db: AsyncSession, email: str) -> str:
    result = await db.execute(select(User.id).where(User.email == email))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user_id


def _reject_invented_portfolio_value(portfolio_value_usd: float | None) -> None:
    """GA16-340: do not accept a client-invented portfolio value without the book."""
    if portfolio_value_usd is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Стоимость портфеля берётся из книги, а не из запроса.",
        )


def _scenario_out(row) -> ScenarioImpactOut:
    return ScenarioImpactOut(
        scenario_name=row.scenario_name,
        shock_strength=row.shock_strength,
        estimated_pnl_impact=row.estimated_pnl_impact,
        estimated_pnl_usd=row.estimated_pnl_usd,
        portfolio_variance_delta=row.portfolio_variance_delta,
        affected_sleeves=[
            {
                "sleeve_id": sleeve.sleeve_id,
                "pnl_impact": sleeve.pnl_impact,
                "contribution_pct": sleeve.contribution_pct,
            }
            for sleeve in row.affected_sleeves
        ],
    )


def _to_out(report: StressReport) -> StressReportOut:
    return StressReportOut(
        profile_id=report.profile_id,
        generated_at=report.generated_at,
        portfolio_value_usd=report.portfolio_value_usd,
        scenario_results=[_scenario_out(row) for row in report.scenario_results],
        worst_scenario=_scenario_out(report.worst_scenario),
        max_loss_fraction=report.max_loss_fraction,
        max_loss_usd=report.max_loss_usd,
        positions_to_review=[
            PositionReviewOut(
                instrument_id=row.instrument_id,
                sleeve_id=row.sleeve_id,
                weight=row.weight,
                scenario_name=row.scenario_name,
                stressed_loss_fraction=row.stressed_loss_fraction,
                stressed_loss_usd=row.stressed_loss_usd,
                sleeve_risk_budget_usd=row.sleeve_risk_budget_usd,
                exceeds_budget=row.exceeds_budget,
                reason=row.reason,
            )
            for row in report.positions_to_review
        ],
        metadata=report.metadata,
    )


@router.post("/run", response_model=StressReportOut)
async def run_stress_harness(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
    portfolio_value_usd: float | None = Query(default=None, gt=0.0),
    target_instrument_id: int | None = Query(default=None, gt=0),
    target_sector: str | None = Query(default=None),
) -> StressReportOut:
    """Run all built-in ScenarioEngine scenarios against the live profile portfolio."""
    _reject_invented_portfolio_value(portfolio_value_usd)
    profile_id = await _profile_id_for_email(db, email)
    context = await _service.loader.load_profile_portfolio(
        db,
        profile_id,
        portfolio_value_usd=None,
    )
    if not context.portfolio.positions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет открытых позиций для стресс-теста.",
        )
    report = _service.run_all_scenarios(
        context,
        target_instrument_id=target_instrument_id,
        target_sector=target_sector,
    )
    return _to_out(report)


@router.post("/run/custom", response_model=StressReportOut)
async def run_custom_stress_scenario(
    body: CustomScenarioIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
    portfolio_value_usd: float | None = Query(default=None, gt=0.0),
) -> StressReportOut:
    """Run a parameterized custom scenario without code changes."""
    _reject_invented_portfolio_value(portfolio_value_usd)
    profile_id = await _profile_id_for_email(db, email)
    context = await _service.loader.load_profile_portfolio(
        db,
        profile_id,
        portfolio_value_usd=None,
    )
    if not context.portfolio.positions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет открытых позиций для стресс-теста.",
        )
    request = CustomScenarioRequest(
        scenario=body.scenario,
        shock_strength=body.shock_strength,
        target_instrument_id=body.target_instrument_id,
        target_sector=body.target_sector,
    )
    report = _service.run_custom_scenario(context, request)
    return _to_out(report)
