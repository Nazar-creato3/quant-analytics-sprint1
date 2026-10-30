"""Static composer configs for tests and proof scripts — no DB session."""
from __future__ import annotations

from app.domain.enums import Strategy
from app.services.strategy.composer.models import (
    ComposerBranch,
    ComposerConditionGroup,
    ComposerConfig,
    ComposerField,
    ComposerOperator,
    ComposerOutcome,
    ComposerPredicate,
)
from app.services.strategy.types import GridMode


def default_composer_config() -> ComposerConfig:
    """IF vol_pct > 0.5 AND regime == trend THEN grid ELSE mean_reversion."""
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
