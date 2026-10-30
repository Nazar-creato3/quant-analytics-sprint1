"""Strategy Composer service — save/load per profile."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.profile import ProfileUpdate
from app.services.profile.service import ProfileService
from app.services.strategy.composer.compiler import compile_composer_config
from app.services.strategy.composer.models import (
    ComposerBranch,
    ComposerConditionGroup,
    ComposerConfig,
    ComposerOutcome,
    ComposerPredicate,
    ComposerSchemaOut,
    ComposerValidationResult,
    CompiledStrategyConfig,
    ComposerField,
    ComposerOperator,
    REGIME_ALIASES,
)
from app.services.strategy.composer.validator import validate_composer_config
from app.domain.enums import Strategy
from app.services.strategy.types import GridMode, MarketRegime

COMPOSER_SESSION_KEY = "strategy_composer"


class ComposerValidationError(ValueError):
    """Raised when composer config fails validation."""


class StrategyComposerService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ProfileService(db)

    async def resolve_profile_id(self, email: str) -> str:
        result = await self._db.execute(select(User.id).where(User.email == email.lower()))
        user_id = result.scalar_one_or_none()
        if user_id is None:
            raise LookupError(f"user not found: {email}")
        return user_id

    async def load(self, profile_id: str) -> ComposerConfig | None:
        profile = await self._profiles.get(profile_id)
        raw = (profile.session_preferences or {}).get(COMPOSER_SESSION_KEY)
        if not raw:
            return None
        return ComposerConfig.model_validate(raw)

    async def save(self, profile_id: str, config: ComposerConfig) -> ComposerConfig:
        validation = self.validate(config)
        if not validation.valid:
            raise ComposerValidationError("; ".join(validation.errors))

        profile = await self._profiles.get(profile_id)
        prefs = dict(profile.session_preferences or {})
        prefs[COMPOSER_SESSION_KEY] = config.model_dump(mode="json")
        await self._profiles.update(profile_id, ProfileUpdate(session_preferences=prefs))
        return config

    def validate(self, config: ComposerConfig) -> ComposerValidationResult:
        return StrategyComposerService.validate_config(config)

    def compile(self, config: ComposerConfig) -> CompiledStrategyConfig:
        return StrategyComposerService.compile_config(config)

    @staticmethod
    def validate_config(config: ComposerConfig) -> ComposerValidationResult:
        try:
            ComposerConfig.model_validate(config.model_dump(mode="json"))
        except ValidationError as exc:
            return ComposerValidationResult(valid=False, errors=[str(exc)])

        return validate_composer_config(config)

    @staticmethod
    def compile_config(config: ComposerConfig) -> CompiledStrategyConfig:
        validation = StrategyComposerService.validate_config(config)
        if not validation.valid:
            raise ComposerValidationError("; ".join(validation.errors))
        return compile_composer_config(config)

    @staticmethod
    def schema() -> ComposerSchemaOut:
        return ComposerSchemaOut(
            fields=[
                {"id": f.value, "label": f.value.replace("_", " ").title()}
                for f in ComposerField
            ],
            operators=[op.value for op in ComposerOperator],
            strategies=[s.value for s in Strategy],
            grid_modes=[m.value for m in GridMode],
            regime_values=[r.value for r in MarketRegime],
            regime_aliases={k: list(v) for k, v in REGIME_ALIASES.items()},
        )

    @staticmethod
    def default_config() -> ComposerConfig:
        """Example: if volatility > 0.5 and regime == trend then grid else mean_reversion."""
        return ComposerConfig(
            name="default",
            root_branch_id="branch-main",
            default_outcome_id="outcome-mean-reversion",
            outcomes=[
                ComposerOutcome(
                    id="outcome-grid",
                    label="Grid Mode",
                    primary_strategy=Strategy.GRID,
                    grid_mode=GridMode.POINT,
                ),
                ComposerOutcome(
                    id="outcome-mean-reversion",
                    label="Mean Reversion",
                    primary_strategy=Strategy.MEAN_REVERSION,
                ),
            ],
            branches=[
                ComposerBranch(
                    id="branch-main",
                    condition=ComposerConditionGroup(
                        id="branch-main",
                        logic="and",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.VOLATILITY_PERCENTILE,
                                operator=ComposerOperator.GT,
                                value=0.5,
                            ),
                            ComposerPredicate(
                                field=ComposerField.REGIME,
                                operator=ComposerOperator.EQ,
                                value="trend",
                            ),
                        ],
                    ),
                    then_outcome_id="outcome-grid",
                    else_outcome_id="outcome-mean-reversion",
                ),
            ],
        )
