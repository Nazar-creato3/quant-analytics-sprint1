"""
Portfolio-level position sizing guardrails applied at approval / execution time.

Uses the operator's effective deploy cap (clamped to real balance), never a soft
$10k fallback that lets paper tickets exceed cash and inflate the navbar total.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver
from app.services.portfolio.exposure import current_exposure

logger = get_logger(__name__)

_MIN_POSITION_USD = 1.0


@dataclass
class PositionLimitDecision:
    allowed: bool
    reason: str
    original_size_usd: float
    approved_size_usd: float
    scaled: bool
    max_position_usd: float
    remaining_budget_usd: float
    portfolio_size: float

    @property
    def scale_factor(self) -> float:
        if self.original_size_usd <= 0:
            return 0.0
        return self.approved_size_usd / self.original_size_usd


async def _portfolio_size(email: str, db: AsyncSession) -> float:
    """Deployable capital — clamped to account total, never phantom $10k."""
    try:
        from app.services.portfolio.metrics import _user_effective_deploy_cap

        cap = await _user_effective_deploy_cap(email, db)
        if cap > 0:
            return float(cap)
    except Exception as exc:
        logger.debug("effective_deploy_cap_failed", error=str(exc)[:120])
    try:
        from app.services.portfolio.metrics import _user_portfolio_size, user_account_total_usd
        from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing

        stored = await _user_portfolio_size(email)
        total = await user_account_total_usd(email, db)
        return float(resolve_deploy_cap_for_sizing(stored, total))
    except Exception:
        return float(settings.DEFAULT_PORTFOLIO_SIZE)


async def _current_exposure_usd(
    db: AsyncSession,
    exclude_id: str | None,
    *,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> float:
    """Sum notional of open maneuver positions plus active grid net positions."""
    snapshot = await current_exposure(
        db,
        exclude_maneuver_id=exclude_id,
        owner_user_id=owner_user_id,
        owner_email=owner_email,
    )
    return snapshot.total_usd


async def evaluate_position_limits(
    db: AsyncSession,
    maneuver: Maneuver,
    email: str,
) -> PositionLimitDecision:
    """Decide whether a maneuver can open, scaling it down to fit the caps."""
    portfolio_size = await _portfolio_size(email, db)
    original = float(maneuver.position_size_usd or 0.0)

    if original < _MIN_POSITION_USD:
        return PositionLimitDecision(
            allowed=False,
            reason=(
                "Маневр без размера позиции ($0) — нечего исполнять. "
                "Запустите анализ рынка, чтобы получить маневр с рассчитанным объёмом."
            ),
            original_size_usd=round(original, 2),
            approved_size_usd=0.0,
            scaled=False,
            max_position_usd=0.0,
            remaining_budget_usd=0.0,
            portfolio_size=portfolio_size,
        )

    if portfolio_size < _MIN_POSITION_USD:
        return PositionLimitDecision(
            allowed=False,
            reason=(
                f"Недостаточно капитала: кап/баланс ≈ ${portfolio_size:,.0f}. "
                "Пополните бумажный счёт или снизьте размер идеи."
            ),
            original_size_usd=round(original, 2),
            approved_size_usd=0.0,
            scaled=False,
            max_position_usd=0.0,
            remaining_budget_usd=0.0,
            portfolio_size=portfolio_size,
        )

    per_position_cap = portfolio_size * settings.MAX_POSITION_PCT / 100
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        per_position_cap = min(per_position_cap, settings.MAX_NOTIONAL_PER_POSITION_USD)

    max_exposure = portfolio_size * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100
    from app.services.portfolio.user_scope import get_user_by_email

    owner_user_id = None
    try:
        user = await get_user_by_email(db, email)
        if user:
            owner_user_id = user.id
    except Exception:
        owner_user_id = None
    used = await _current_exposure_usd(
        db,
        exclude_id=maneuver.id,
        owner_user_id=owner_user_id,
        owner_email=email,
    )
    remaining_budget = max(0.0, round(max_exposure - used, 2))
    free_cash = max(0.0, round(portfolio_size - used, 2))
    remaining_budget = min(remaining_budget, free_cash)

    allowed_size = min(original, per_position_cap, remaining_budget, portfolio_size)

    from app.services.risk.portfolio_sizing import min_proposal_notional_usd

    min_ticket = min_proposal_notional_usd(portfolio_size)
    if allowed_size + 1e-6 < min_ticket:
        return PositionLimitDecision(
            allowed=False,
            reason=(
                f"Размер ${allowed_size:,.0f} меньше минимума ${min_ticket:,.0f} "
                f"при капе ${portfolio_size:,.0f}."
            ),
            original_size_usd=round(original, 2),
            approved_size_usd=0.0,
            scaled=False,
            max_position_usd=round(per_position_cap, 2),
            remaining_budget_usd=remaining_budget,
            portfolio_size=portfolio_size,
        )

    if allowed_size < _MIN_POSITION_USD:
        return PositionLimitDecision(
            allowed=False,
            reason=(
                f"Недостаточно средств для сделки ${original:,.0f}: "
                f"свободно ≈ ${free_cash:,.0f} при капе ${portfolio_size:,.0f} "
                f"(уже в позициях ${used:,.0f}). "
                "Уменьшите размер или закройте часть позиций."
            ),
            original_size_usd=round(original, 2),
            approved_size_usd=0.0,
            scaled=False,
            max_position_usd=round(per_position_cap, 2),
            remaining_budget_usd=remaining_budget,
            portfolio_size=portfolio_size,
        )

    scaled = allowed_size < original - 1e-6
    reason = "OK"
    if scaled:
        if abs(allowed_size - remaining_budget) < 1e-6 and remaining_budget <= per_position_cap + 1e-6:
            reason = (
                f"Размер уменьшен до ${allowed_size:,.0f} — упор в свободный капитал "
                f"(кап ${portfolio_size:,.0f}, занято ${used:,.0f})."
            )
        else:
            reason = (
                f"Размер уменьшен до ${allowed_size:,.0f} — лимит на одну позицию "
                f"{settings.MAX_POSITION_PCT:.0f}% капитала."
            )

    return PositionLimitDecision(
        allowed=True,
        reason=reason,
        original_size_usd=round(original, 2),
        approved_size_usd=round(allowed_size, 2),
        scaled=scaled,
        max_position_usd=round(per_position_cap, 2),
        remaining_budget_usd=remaining_budget,
        portfolio_size=portfolio_size,
    )


def apply_decision_to_maneuver(maneuver: Maneuver, decision: PositionLimitDecision) -> None:
    """Mutate the maneuver in place so downstream execution uses the capped size."""
    if not decision.scaled or decision.original_size_usd <= 0:
        return
    factor = decision.scale_factor
    maneuver.position_size_usd = decision.approved_size_usd
    if maneuver.expected_pnl_low is not None:
        maneuver.expected_pnl_low = round(maneuver.expected_pnl_low * factor, 2)
    if maneuver.expected_pnl_high is not None:
        maneuver.expected_pnl_high = round(maneuver.expected_pnl_high * factor, 2)
    if maneuver.risk_percent is not None:
        maneuver.risk_percent = round(maneuver.risk_percent * factor, 4)
