"""Profile constitution service — get, update, live-transition validation."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.domain.enums import AssetCategory
from app.domain.compliance import AccountType, BrokerAgreementStatus, Jurisdiction
from app.domain.profile import (
    ApprovalPolicyORM,
    LiveTransitionResult,
    ProfileBase,
    ProfileMode,
    ProfileORM,
    ProfileRead,
    ProfileUpdate,
    RiskAppetite,
)
from app.utils.helpers import utcnow

logger = get_logger(__name__)


class ProfileNotFoundError(LookupError):
    """Raised when no profile exists for the given user id."""


class ProfileValidationError(ValueError):
    """Raised when profile constitution fields fail validation."""


class LiveTransitionBlockedError(ProfileValidationError):
    """Raised when a profile cannot switch from paper to live mode."""


def _default_profile_fields() -> dict[str, Any]:
    return {
        "risk_appetite": RiskAppetite.MODERATE.value,
        "max_drawdown_pct": Decimal("15"),
        "max_daily_loss_abs": Decimal("0"),
        "allowed_categories": [],
        "allowed_instrument_ids": [],
        "approval_policy_id": None,
        "time_horizon": "swing",
        "execution_style": "active",
        "volatility_tolerance": 0.5,
        "hedge_preference": False,
        "leverage_max": Decimal("1"),
        "mode": ProfileMode.PAPER.value,
        "automation_level": "manual",
        "session_preferences": {},
        "news_sensitivity": 0.5,
        "event_sensitivity": 0.5,
        "diversification_policy": {},
        "paper_trading_days": 0,
        "paper_sharpe": None,
        # Primary market: MOEX/Tinkoff (RU). Crypto paper via separate venue policy later.
        "jurisdiction": Jurisdiction.RU.value,
        "account_type": AccountType.RETAIL.value,
        "broker_agreement_status": BrokerAgreementStatus.PENDING.value,
    }


def validate_profile_constitution(data: ProfileBase | ProfileRead) -> None:
    """Re-run pydantic compatibility checks (raises ProfileValidationError)."""
    try:
        ProfileBase.model_validate(data.model_dump())
    except ValidationError as exc:
        raise ProfileValidationError(str(exc)) from exc


def validate_live_transition(
    profile: ProfileBase | ProfileRead,
    *,
    settings: Settings | None = None,
) -> LiveTransitionResult:
    """Check whether ``profile`` meets paper sign-off criteria for live mode."""
    cfg = settings or get_settings()
    reasons: list[str] = []

    if profile.paper_trading_days < cfg.PAPER_TRADING_MIN_DAYS:
        reasons.append(
            f"paper_trading_days ({profile.paper_trading_days}) "
            f"< required minimum ({cfg.PAPER_TRADING_MIN_DAYS})"
        )

    if profile.paper_sharpe is None:
        reasons.append("paper_sharpe is not recorded")
    elif profile.paper_sharpe < cfg.PAPER_SHARPE_MIN_THRESHOLD:
        reasons.append(
            f"paper_sharpe ({profile.paper_sharpe:.4f}) "
            f"< threshold ({cfg.PAPER_SHARPE_MIN_THRESHOLD})"
        )

    try:
        validate_profile_constitution(profile)
    except ProfileValidationError as exc:
        reasons.append(str(exc))

    return LiveTransitionResult(allowed=len(reasons) == 0, reasons=reasons)


class ProfileService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()

    async def get(self, profile_id: str, *, create_if_missing: bool = True) -> ProfileRead:
        row = await self._db.get(ProfileORM, profile_id)
        if row is None:
            if not create_if_missing:
                raise ProfileNotFoundError(f"profile not found: {profile_id}")
            row = ProfileORM(id=profile_id, **_default_profile_fields())
            now = utcnow()
            row.created_at = now
            row.updated_at = now
            self._db.add(row)
            await self._db.flush()
            await self._db.refresh(row)
        return ProfileRead.from_orm_row(row)

    async def update(self, profile_id: str, patch: ProfileUpdate) -> ProfileRead:
        row = await self._db.get(ProfileORM, profile_id)
        if row is None:
            row = ProfileORM(id=profile_id, **_default_profile_fields())
            now = utcnow()
            row.created_at = now
            row.updated_at = now
            self._db.add(row)
            await self._db.flush()

        current = ProfileRead.from_orm_row(row)
        merged = current.model_dump()
        patch_data = patch.model_dump(exclude_unset=True)
        merged.update(patch_data)

        if "allowed_categories" in patch_data and patch_data["allowed_categories"] is not None:
            merged["allowed_categories"] = [
                c.value if isinstance(c, AssetCategory) else c for c in patch.allowed_categories or []
            ]
        else:
            merged["allowed_categories"] = [c.value for c in current.allowed_categories]

        candidate = ProfileBase.model_validate(merged)

        if candidate.mode == ProfileMode.LIVE and current.mode != ProfileMode.LIVE:
            transition = validate_live_transition(candidate, settings=self._settings)
            if not transition.allowed:
                raise LiveTransitionBlockedError("; ".join(transition.reasons))

        if patch.approval_policy_id is not None:
            await self._ensure_approval_policy_belongs_to_profile(
                patch.approval_policy_id,
                profile_id,
            )

        if patch.allowed_instrument_ids is not None:
            await self._validate_instrument_ids(patch.allowed_instrument_ids)

        self._apply_patch(row, patch, candidate)
        await self._db.flush()
        await self._db.refresh(row)
        return ProfileRead.from_orm_row(row)

    async def validate_live_transition(self, profile_id: str) -> LiveTransitionResult:
        profile = await self.get(profile_id, create_if_missing=False)
        return validate_live_transition(profile, settings=self._settings)

    async def _ensure_approval_policy_belongs_to_profile(
        self,
        policy_id: str,
        profile_id: str,
    ) -> None:
        policy = await self._db.get(ApprovalPolicyORM, policy_id)
        if policy is None:
            raise ProfileValidationError(f"approval_policy_id not found: {policy_id}")
        if policy.profile_id != profile_id:
            raise ProfileValidationError(
                f"approval_policy {policy_id} does not belong to profile {profile_id}"
            )

    async def _validate_instrument_ids(self, instrument_ids: list[int]) -> None:
        if not instrument_ids:
            return
        from app.domain.instrument import InstrumentORM

        result = await self._db.execute(
            select(InstrumentORM.id).where(InstrumentORM.id.in_(instrument_ids))
        )
        found = {row[0] for row in result.all()}
        missing = set(instrument_ids) - found
        if missing:
            raise ProfileValidationError(
                f"allowed_instrument_ids reference unknown instruments: {sorted(missing)}"
            )

    @staticmethod
    def _apply_patch(row: ProfileORM, patch: ProfileUpdate, candidate: ProfileBase) -> None:
        row.risk_appetite = candidate.risk_appetite.value
        row.max_drawdown_pct = candidate.max_drawdown_pct
        row.max_daily_loss_abs = candidate.max_daily_loss_abs
        row.allowed_categories = [c.value for c in candidate.allowed_categories]
        row.allowed_instrument_ids = list(candidate.allowed_instrument_ids)
        row.approval_policy_id = candidate.approval_policy_id
        row.time_horizon = candidate.time_horizon.value
        row.execution_style = candidate.execution_style.value
        row.volatility_tolerance = candidate.volatility_tolerance
        row.hedge_preference = candidate.hedge_preference
        row.leverage_max = candidate.leverage_max
        row.mode = candidate.mode.value
        row.automation_level = candidate.automation_level.value
        row.session_preferences = candidate.session_preferences
        row.news_sensitivity = candidate.news_sensitivity
        row.event_sensitivity = candidate.event_sensitivity
        row.diversification_policy = candidate.diversification_policy
        row.paper_trading_days = candidate.paper_trading_days
        row.paper_sharpe = candidate.paper_sharpe
        row.jurisdiction = candidate.jurisdiction.value
        row.account_type = candidate.account_type.value
        row.broker_agreement_status = candidate.broker_agreement_status.value
