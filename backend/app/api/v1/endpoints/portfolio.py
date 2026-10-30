"""Portfolio capital metrics for cockpit NavBar."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.schemas.portfolio import PortfolioMetricsOut, PortfolioRefreshOut, RiskStatusOut, VenueBalancesOut
from app.schemas.portfolio_risk import PortfolioRiskAnalyticsOut, StressScenarioMetaOut
from app.services.portfolio.metrics import build_portfolio_metrics, refresh_portfolio_metrics
from app.services.portfolio.risk_status import build_risk_status
from app.services.portfolio.user_venue_balances import build_user_venue_balances, empty_venue_balances

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/metrics", response_model=PortfolioMetricsOut)
async def get_portfolio_metrics(
    mode: str | None = Query(None, pattern="^(paper|live)$", description="Header switch: live = view the broker account"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PortfolioMetricsOut:
    """TRD / BLNC / SUM breakdown — paper from DB+Redis, live from the user's broker account."""
    return await build_portfolio_metrics(email, db, view_mode=mode)


@router.post("/refresh", response_model=PortfolioRefreshOut)
async def refresh_portfolio_balance(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PortfolioRefreshOut:
    """Recalculate TRD/BLNC from actual open positions and release stale grid locks."""
    metrics, reconcile = await refresh_portfolio_metrics(email, db)
    return PortfolioRefreshOut(
        **metrics.model_dump(),
        deactivated_grid_bots=int(reconcile.get("deactivated_grid_bots", 0)),
        released_capital_usd=float(reconcile.get("released_capital_usd", 0.0)),
        reconciled_at=str(reconcile.get("reconciled_at", metrics.as_of)),
    )


@router.get("/balances", response_model=VenueBalancesOut)
async def get_venue_balances(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> VenueBalancesOut:
    """This user's connected API-key balances only — never platform env keys."""
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        return empty_venue_balances()
    return await build_user_venue_balances(db, user.id)


@router.get("/risk-status", response_model=RiskStatusOut)
async def get_risk_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> RiskStatusOut:
    """Dashboard risk indicator — level, label, and plain-language explanation."""
    return await build_risk_status(email, db)


@router.get("/risk-analytics", response_model=PortfolioRiskAnalyticsOut)
async def get_portfolio_risk_analytics(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PortfolioRiskAnalyticsOut:
    """Institutional risk pack: historical VaR, sector factors, alpha/beta, correlation, stress."""
    from app.services.portfolio.risk_analytics import compute_portfolio_risk_report
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    report = await compute_portfolio_risk_report(
        db,
        owner_user_id=user.id if user else None,
        owner_email=email,
        persist=True,
    )
    return PortfolioRiskAnalyticsOut.model_validate(report.to_dict())


@router.get("/risk-analytics/scenarios", response_model=list[StressScenarioMetaOut])
async def list_risk_stress_scenarios(
    _: str = Depends(get_current_user_email),
) -> list[StressScenarioMetaOut]:
    """Named historical shock windows applied to the current book."""
    from app.services.portfolio.risk_analytics import available_stress_scenarios

    return [StressScenarioMetaOut.model_validate(row) for row in available_stress_scenarios()]


# ── Sample portfolio (new users see every block before connecting a broker) ──
from app.services.qa.session_user import require_session_user_id as _session_uid  # noqa: E402


@router.get("/sample")
def get_sample_state(user_id: str = Depends(_session_uid)) -> dict:
    from app.services.sample_portfolio import sample_state

    return sample_state(user_id)


@router.post("/sample")
async def post_load_sample(user_id: str = Depends(_session_uid)) -> dict:
    from app.services.price_history import service as history
    from app.services.sample_portfolio import load_sample
    from app.services.sample_portfolio.service import sample_tickers

    out = load_sample(user_id)
    history.want([*sample_tickers(), "IMOEX"])  # prices for risk/returns arrive in the background
    return out


@router.delete("/sample")
def delete_sample(user_id: str = Depends(_session_uid)) -> dict:
    from app.services.sample_portfolio import unload_sample

    return unload_sample(user_id)
