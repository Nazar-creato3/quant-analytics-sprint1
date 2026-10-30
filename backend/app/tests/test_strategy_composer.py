"""Tests for Strategy Composer validation and compilation."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.enums import AssetCategory, Strategy
from app.services.strategy.composer import (
    StrategyComposerService,
    apply_outcome_to_context,
    compile_composer_config,
    resolve_from_root,
    validate_composer_config,
)
from app.services.strategy.composer.models import (
    ComposerBranch,
    ComposerConditionGroup,
    ComposerConfig,
    ComposerField,
    ComposerOperator,
    ComposerOutcome,
    ComposerPredicate,
)
from app.services.strategy.composer.service import ComposerValidationError
from app.services.strategy.types import (
    GridMode,
    InstrumentSnapshot,
    MarketRegime,
    SleeveStrategyContext,
    StrategyMarketContext,
)


def _default_config() -> ComposerConfig:
    return StrategyComposerService.default_config()


def _context(
    *,
    regime: MarketRegime = MarketRegime.TREND_UP,
    volatility_percentile: float = 0.6,
) -> StrategyMarketContext:
    instrument = InstrumentSnapshot(
        instrument_id=1,
        symbol="BTC",
        category=AssetCategory.CRYPTO,
        last_price=Decimal("50000"),
        volatility=0.2,
    )
    sleeve = SleeveStrategyContext(
        sleeve_id="sleeve-1",
        category=AssetCategory.CRYPTO,
        instruments=(instrument,),
    )
    return StrategyMarketContext(
        sleeve=sleeve,
        regime=regime,
        volatility_percentile=volatility_percentile,
        asset_class="crypto",
    )


class TestComposerModels:
    def test_default_config_is_valid(self):
        config = _default_config()
        result = validate_composer_config(config)
        assert result.valid is True

    def test_rejects_self_referencing_branch(self):
        config = _default_config()
        config = config.model_copy(
            update={
                "branches": [
                    config.branches[0].model_copy(update={"else_branch_id": "branch-main", "else_outcome_id": None})
                ]
            }
        )
        with pytest.raises(ValidationError):
            ComposerConfig.model_validate(config.model_dump(mode="json"))

    def test_rejects_grid_mode_on_non_grid_strategy(self):
        with pytest.raises(ValidationError):
            ComposerOutcome(
                id="bad",
                label="Bad",
                primary_strategy=Strategy.MEAN_REVERSION,
                grid_mode=GridMode.POINT,
            )


class TestComposerValidation:
    def test_detects_branch_cycle(self):
        config = ComposerConfig(
            name="cycle",
            root_branch_id="b1",
            default_outcome_id="o-default",
            outcomes=[
                ComposerOutcome(id="o-grid", label="Grid", primary_strategy=Strategy.GRID),
                ComposerOutcome(id="o-mr", label="MR", primary_strategy=Strategy.MEAN_REVERSION),
                ComposerOutcome(id="o-default", label="Default", primary_strategy=Strategy.TREND),
            ],
            branches=[
                ComposerBranch(
                    id="b1",
                    condition=ComposerConditionGroup(
                        id="b1",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.REGIME,
                                operator=ComposerOperator.EQ,
                                value="trend",
                            )
                        ],
                    ),
                    then_outcome_id="o-grid",
                    else_branch_id="b2",
                ),
                ComposerBranch(
                    id="b2",
                    condition=ComposerConditionGroup(
                        id="b2",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.VOLATILITY_PERCENTILE,
                                operator=ComposerOperator.GT,
                                value=0.7,
                            )
                        ],
                    ),
                    then_outcome_id="o-mr",
                    else_branch_id="b1",
                ),
            ],
        )
        result = validate_composer_config(config)
        assert result.valid is False
        assert any("cycle" in err for err in result.errors)

    def test_detects_unreachable_branch(self):
        config = ComposerConfig(
            name="unreachable",
            root_branch_id="b1",
            default_outcome_id="o-default",
            outcomes=[
                ComposerOutcome(id="o-grid", label="Grid", primary_strategy=Strategy.GRID),
                ComposerOutcome(id="o-mr", label="MR", primary_strategy=Strategy.MEAN_REVERSION),
                ComposerOutcome(id="o-default", label="Default", primary_strategy=Strategy.TREND),
            ],
            branches=[
                ComposerBranch(
                    id="b1",
                    condition=ComposerConditionGroup(
                        id="b1",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.REGIME,
                                operator=ComposerOperator.EQ,
                                value="trend",
                            )
                        ],
                    ),
                    then_outcome_id="o-grid",
                    else_outcome_id="o-mr",
                ),
                ComposerBranch(
                    id="b-orphan",
                    condition=ComposerConditionGroup(
                        id="b-orphan",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.VOLATILITY_PERCENTILE,
                                operator=ComposerOperator.LT,
                                value=0.2,
                            )
                        ],
                    ),
                    then_outcome_id="o-default",
                    else_outcome_id="o-mr",
                ),
            ],
        )
        result = validate_composer_config(config)
        assert result.valid is False
        assert any("unreachable branches" in err for err in result.errors)


class TestComposerCompilation:
    def test_default_scenario_compiles(self):
        config = _default_config()
        compiled = compile_composer_config(config)
        assert compiled.default.primary_strategy == Strategy.MEAN_REVERSION.value
        assert len(compiled.rules) == 1
        rule = compiled.rules[0]
        assert rule.logic == "and"
        assert len(rule.conditions) == 2
        assert rule.then.primary_strategy == Strategy.GRID.value
        assert rule.then.grid_mode == GridMode.POINT.value
        assert rule.else_outcome is not None
        assert rule.else_outcome.primary_strategy == Strategy.MEAN_REVERSION.value

    def test_high_vol_trend_resolves_to_grid(self):
        config = _default_config()
        compiled = compile_composer_config(config)
        outcome = resolve_from_root(
            _context(regime=MarketRegime.TREND_UP, volatility_percentile=0.6),
            compiled,
            root_branch_id=config.root_branch_id,
        )
        assert outcome.primary_strategy == Strategy.GRID.value
        assert outcome.grid_mode == GridMode.POINT.value

    def test_low_vol_trend_resolves_to_mean_reversion(self):
        config = _default_config()
        compiled = compile_composer_config(config)
        outcome = resolve_from_root(
            _context(regime=MarketRegime.TREND_UP, volatility_percentile=0.3),
            compiled,
            root_branch_id=config.root_branch_id,
        )
        assert outcome.primary_strategy == Strategy.MEAN_REVERSION.value

    def test_range_regime_resolves_to_mean_reversion(self):
        config = _default_config()
        compiled = compile_composer_config(config)
        outcome = resolve_from_root(
            _context(regime=MarketRegime.RANGE, volatility_percentile=0.8),
            compiled,
            root_branch_id=config.root_branch_id,
        )
        assert outcome.primary_strategy == Strategy.MEAN_REVERSION.value

    def test_chained_branches_compile_and_resolve(self):
        config = ComposerConfig(
            name="chain",
            root_branch_id="b-vol",
            default_outcome_id="o-default",
            outcomes=[
                ComposerOutcome(id="o-grid", label="Grid", primary_strategy=Strategy.GRID, grid_mode=GridMode.DIVERSIFIED),
                ComposerOutcome(id="o-trend", label="Trend", primary_strategy=Strategy.TREND),
                ComposerOutcome(id="o-mr", label="MR", primary_strategy=Strategy.MEAN_REVERSION),
                ComposerOutcome(id="o-default", label="Default", primary_strategy=Strategy.BREAKOUT),
            ],
            branches=[
                ComposerBranch(
                    id="b-vol",
                    condition=ComposerConditionGroup(
                        id="b-vol",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.VOLATILITY_PERCENTILE,
                                operator=ComposerOperator.GT,
                                value=0.5,
                            )
                        ],
                    ),
                    then_outcome_id="o-grid",
                    else_branch_id="b-regime",
                ),
                ComposerBranch(
                    id="b-regime",
                    condition=ComposerConditionGroup(
                        id="b-regime",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.REGIME,
                                operator=ComposerOperator.EQ,
                                value="trend",
                            )
                        ],
                    ),
                    then_outcome_id="o-trend",
                    else_outcome_id="o-mr",
                ),
            ],
        )
        result = validate_composer_config(config)
        assert result.valid is True

        compiled = compile_composer_config(config)
        high_vol = resolve_from_root(
            _context(regime=MarketRegime.RANGE, volatility_percentile=0.7),
            compiled,
            root_branch_id="b-vol",
        )
        assert high_vol.primary_strategy == Strategy.GRID.value
        assert high_vol.grid_mode == GridMode.DIVERSIFIED.value

        low_vol_trend = resolve_from_root(
            _context(regime=MarketRegime.TREND_DOWN, volatility_percentile=0.2),
            compiled,
            root_branch_id="b-vol",
        )
        assert low_vol_trend.primary_strategy == Strategy.TREND.value

        low_vol_range = resolve_from_root(
            _context(regime=MarketRegime.RANGE, volatility_percentile=0.2),
            compiled,
            root_branch_id="b-vol",
        )
        assert low_vol_range.primary_strategy == Strategy.MEAN_REVERSION.value

    def test_apply_outcome_sets_grid_mode(self):
        config = _default_config()
        compiled = compile_composer_config(config)
        outcome = compiled.rules[0].then
        ctx = _context()
        updated = apply_outcome_to_context(ctx, outcome)
        assert updated.grid_mode == GridMode.POINT

    def test_compile_rejects_invalid_config(self):
        config = _default_config()
        config = config.model_copy(
            update={
                "branches": [
                    config.branches[0].model_copy(update={"else_branch_id": "missing", "else_outcome_id": None})
                ]
            }
        )
        with pytest.raises(ValidationError):
            ComposerConfig.model_validate(config.model_dump(mode="json"))

    def test_service_compile_raises_on_cycle(self):
        config = ComposerConfig(
            name="cycle",
            root_branch_id="b1",
            default_outcome_id="o-default",
            outcomes=[
                ComposerOutcome(id="o-grid", label="Grid", primary_strategy=Strategy.GRID),
                ComposerOutcome(id="o-mr", label="MR", primary_strategy=Strategy.MEAN_REVERSION),
                ComposerOutcome(id="o-default", label="Default", primary_strategy=Strategy.TREND),
            ],
            branches=[
                ComposerBranch(
                    id="b1",
                    condition=ComposerConditionGroup(
                        id="b1",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.REGIME,
                                operator=ComposerOperator.EQ,
                                value="trend",
                            )
                        ],
                    ),
                    then_outcome_id="o-grid",
                    else_branch_id="b2",
                ),
                ComposerBranch(
                    id="b2",
                    condition=ComposerConditionGroup(
                        id="b2",
                        predicates=[
                            ComposerPredicate(
                                field=ComposerField.VOLATILITY_PERCENTILE,
                                operator=ComposerOperator.GT,
                                value=0.7,
                            )
                        ],
                    ),
                    then_outcome_id="o-mr",
                    else_branch_id="b1",
                ),
            ],
        )
        with pytest.raises(ComposerValidationError):
            StrategyComposerService.compile_config(config)
