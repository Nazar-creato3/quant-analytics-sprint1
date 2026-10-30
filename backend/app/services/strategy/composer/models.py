"""Declarative Strategy Composer models — no arbitrary code execution."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import Strategy
from app.services.strategy.types import GridMode, MarketRegime


class ComposerField(str, Enum):
    VOLATILITY_PERCENTILE = "volatility_percentile"
    VOLATILITY = "volatility"
    REGIME = "regime"
    MICROSTRUCTURE_SCORE = "microstructure_score"
    SESSION_ACTIVE = "session_active"


class ComposerOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    IN = "in"


REGIME_ALIASES: dict[str, tuple[str, ...]] = {
    "trend": (MarketRegime.TREND_UP.value, MarketRegime.TREND_DOWN.value),
    "range_bound": (MarketRegime.RANGE.value, MarketRegime.LOW_VOL.value),
}

ALLOWED_STRATEGIES = frozenset(s.value for s in Strategy)
ALLOWED_GRID_MODES = frozenset(m.value for m in GridMode)
ALLOWED_REGIMES = frozenset(r.value for r in MarketRegime) | frozenset(REGIME_ALIASES.keys())


class ComposerPredicate(BaseModel):
    field: ComposerField
    operator: ComposerOperator
    value: float | bool | str | list[str]

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any, info: Any) -> Any:
        field = info.data.get("field")
        if field == ComposerField.SESSION_ACTIVE:
            if not isinstance(value, bool):
                raise ValueError("session_active predicate requires a boolean value")
        elif field == ComposerField.REGIME:
            if isinstance(value, str):
                if value not in ALLOWED_REGIMES:
                    raise ValueError(f"invalid regime value: {value}")
            elif isinstance(value, list):
                if not value or not all(v in ALLOWED_REGIMES for v in value):
                    raise ValueError("regime list contains invalid values")
            else:
                raise ValueError("regime predicate requires string or list value")
        elif field in {ComposerField.VOLATILITY_PERCENTILE, ComposerField.VOLATILITY, ComposerField.MICROSTRUCTURE_SCORE}:
            if not isinstance(value, (int, float)):
                raise ValueError(f"{field.value} predicate requires a numeric value")
            if field in {ComposerField.VOLATILITY_PERCENTILE, ComposerField.MICROSTRUCTURE_SCORE}:
                if not 0.0 <= float(value) <= 1.0:
                    raise ValueError(f"{field.value} must be in [0, 1]")
        return value


class ComposerConditionGroup(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    logic: Literal["and", "or"] = "and"
    predicates: list[ComposerPredicate] = Field(min_length=1)


class ComposerOutcome(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    primary_strategy: Strategy
    grid_mode: GridMode | None = None

    @model_validator(mode="after")
    def grid_mode_only_for_grid(self) -> ComposerOutcome:
        if self.grid_mode is not None and self.primary_strategy != Strategy.GRID:
            raise ValueError("grid_mode is only valid when primary_strategy is grid")
        if self.primary_strategy == Strategy.GRID and self.grid_mode is None:
            self.grid_mode = GridMode.POINT
        return self


class ComposerBranch(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    condition: ComposerConditionGroup
    then_outcome_id: str
    else_outcome_id: str | None = None
    else_branch_id: str | None = None

    @model_validator(mode="after")
    def else_target_present(self) -> ComposerBranch:
        if self.else_outcome_id is None and self.else_branch_id is None:
            raise ValueError("branch must specify else_outcome_id or else_branch_id")
        if self.else_outcome_id is not None and self.else_branch_id is not None:
            raise ValueError("branch cannot specify both else_outcome_id and else_branch_id")
        return self


class ComposerConfig(BaseModel):
    version: int = 1
    name: str = Field(default="default", min_length=1, max_length=120)
    root_branch_id: str
    branches: list[ComposerBranch] = Field(min_length=1)
    outcomes: list[ComposerOutcome] = Field(min_length=1)
    default_outcome_id: str

    @model_validator(mode="after")
    def validate_references(self) -> ComposerConfig:
        branch_ids = {b.id for b in self.branches}
        outcome_ids = {o.id for o in self.outcomes}

        if self.root_branch_id not in branch_ids:
            raise ValueError(f"root_branch_id not found: {self.root_branch_id}")
        if self.default_outcome_id not in outcome_ids:
            raise ValueError(f"default_outcome_id not found: {self.default_outcome_id}")

        for branch in self.branches:
            if branch.condition.id != branch.id:
                raise ValueError(f"branch {branch.id} condition id must match branch id")
            if branch.then_outcome_id not in outcome_ids:
                raise ValueError(f"branch {branch.id} references unknown then_outcome_id")
            if branch.else_outcome_id and branch.else_outcome_id not in outcome_ids:
                raise ValueError(f"branch {branch.id} references unknown else_outcome_id")
            if branch.else_branch_id and branch.else_branch_id not in branch_ids:
                raise ValueError(f"branch {branch.id} references unknown else_branch_id")
            if branch.else_branch_id == branch.id:
                raise ValueError(f"branch {branch.id} cannot reference itself as else_branch_id")

        if len(branch_ids) != len(self.branches):
            raise ValueError("duplicate branch ids")
        if len(outcome_ids) != len(self.outcomes):
            raise ValueError("duplicate outcome ids")

        return self


class CompiledOutcome(BaseModel):
    primary_strategy: str
    grid_mode: str | None = None


class CompiledRule(BaseModel):
    branch_id: str
    logic: Literal["and", "or"]
    conditions: list[dict[str, Any]]
    then: CompiledOutcome
    else_outcome: CompiledOutcome | None = None
    else_branch_id: str | None = None


class CompiledStrategyConfig(BaseModel):
    version: int
    name: str
    rules: list[CompiledRule]
    default: CompiledOutcome


class ComposerValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComposerSchemaOut(BaseModel):
    fields: list[dict[str, str]]
    operators: list[str]
    strategies: list[str]
    grid_modes: list[str]
    regime_values: list[str]
    regime_aliases: dict[str, list[str]]
