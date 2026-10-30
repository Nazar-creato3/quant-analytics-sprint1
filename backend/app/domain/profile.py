"""Trading profile (constitution) — rules source for sleeves and deal intents."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.domain.compliance import AccountType, BrokerAgreementStatus, Jurisdiction
from app.domain.enums import AssetCategory
from app.utils.helpers import utcnow


class RiskAppetite(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class TimeHorizon(str, Enum):
    INTRADAY = "intraday"
    SWING = "swing"
    POSITION = "position"
    LONG_TERM = "long_term"


class ExecutionStyle(str, Enum):
    PASSIVE = "passive"
    ACTIVE = "active"
    AGGRESSIVE = "aggressive"


class ProfileMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class AutomationLevel(str, Enum):
    MANUAL = "manual"
    SEMI_AUTO = "semi_auto"
    FULL_AUTO = "full_auto"


class ProfileORM(Base):
    """One trading constitution per user (``id`` matches ``users.id`` / sleeve ``profile_id``)."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    risk_appetite: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RiskAppetite.MODERATE.value,
        server_default="moderate",
    )
    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("15.00"),
        server_default="15.00",
    )
    max_daily_loss_abs: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    allowed_categories: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    allowed_instrument_ids: Mapped[list[int]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    approval_policy_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("approval_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    time_horizon: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TimeHorizon.SWING.value,
        server_default="swing",
    )
    execution_style: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ExecutionStyle.ACTIVE.value,
        server_default="active",
    )
    volatility_tolerance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        server_default="0.5",
    )
    hedge_preference: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    leverage_max: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
    )
    mode: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ProfileMode.PAPER.value,
        server_default="paper",
    )
    automation_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AutomationLevel.MANUAL.value,
        server_default="manual",
    )
    session_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    news_sensitivity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        server_default="0.5",
    )
    event_sensitivity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        server_default="0.5",
    )
    diversification_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    paper_trading_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    paper_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=Jurisdiction.RU.value,
        server_default="global",
    )
    account_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AccountType.RETAIL.value,
        server_default="retail",
    )
    broker_agreement_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=BrokerAgreementStatus.PENDING.value,
        server_default="pending",
    )
    # Membership access level (Prompt 56) — synced from AccessPolicyStateORM.
    access_level: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="trial_read_only",
        server_default="trial_read_only",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ApprovalPolicyORM(Base):
    """Stub approval policy registry (expanded in Approval Policy Engine prompt)."""

    __tablename__ = "approval_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProfileBase(BaseModel):
    risk_appetite: RiskAppetite = RiskAppetite.MODERATE
    max_drawdown_pct: Decimal = Field(default=Decimal("15"), gt=Decimal("0"), le=Decimal("100"))
    max_daily_loss_abs: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    allowed_categories: list[AssetCategory] = Field(default_factory=list)
    allowed_instrument_ids: list[int] = Field(default_factory=list)
    approval_policy_id: str | None = None
    time_horizon: TimeHorizon = TimeHorizon.SWING
    execution_style: ExecutionStyle = ExecutionStyle.ACTIVE
    volatility_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    hedge_preference: bool = False
    leverage_max: Decimal = Field(default=Decimal("1"), ge=Decimal("0"))
    mode: ProfileMode = ProfileMode.PAPER
    automation_level: AutomationLevel = AutomationLevel.MANUAL
    session_preferences: dict[str, Any] = Field(default_factory=dict)
    news_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    event_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    diversification_policy: dict[str, Any] = Field(default_factory=dict)
    paper_trading_days: int = Field(default=0, ge=0)
    paper_sharpe: float | None = None
    jurisdiction: Jurisdiction = Jurisdiction.RU
    account_type: AccountType = AccountType.RETAIL
    broker_agreement_status: BrokerAgreementStatus = BrokerAgreementStatus.PENDING

    @field_validator("allowed_instrument_ids")
    @classmethod
    def unique_instrument_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_instrument_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def check_compatible_settings(self) -> ProfileBase:
        errors: list[str] = []

        if (
            self.risk_appetite == RiskAppetite.CONSERVATIVE
            and self.execution_style == ExecutionStyle.AGGRESSIVE
        ):
            errors.append("conservative risk_appetite is incompatible with aggressive execution_style")

        if self.risk_appetite == RiskAppetite.CONSERVATIVE and self.leverage_max > Decimal("1"):
            errors.append("conservative risk_appetite requires leverage_max <= 1")

        if (
            self.risk_appetite == RiskAppetite.AGGRESSIVE
            and self.execution_style == ExecutionStyle.PASSIVE
            and self.automation_level == AutomationLevel.FULL_AUTO
        ):
            errors.append(
                "aggressive risk with passive execution cannot use full_auto automation"
            )

        if self.time_horizon == TimeHorizon.INTRADAY and self.automation_level == AutomationLevel.MANUAL:
            if self.execution_style == ExecutionStyle.PASSIVE:
                errors.append("intraday passive manual execution is not a supported combination")

        if self.time_horizon == TimeHorizon.LONG_TERM and self.execution_style == ExecutionStyle.AGGRESSIVE:
            errors.append("long_term time_horizon is incompatible with aggressive execution_style")

        if (
            self.automation_level == AutomationLevel.FULL_AUTO
            and self.mode == ProfileMode.PAPER
            and self.risk_appetite == RiskAppetite.CONSERVATIVE
            and self.leverage_max > Decimal("1")
        ):
            errors.append("full_auto conservative profile cannot use leverage above 1")

        if errors:
            raise ValueError("; ".join(errors))
        return self


class ProfileCreate(ProfileBase):
    id: str = Field(min_length=1, max_length=36)


class ProfileUpdate(BaseModel):
    risk_appetite: RiskAppetite | None = None
    max_drawdown_pct: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("100"))
    max_daily_loss_abs: Decimal | None = Field(default=None, ge=Decimal("0"))
    allowed_categories: list[AssetCategory] | None = None
    allowed_instrument_ids: list[int] | None = None
    approval_policy_id: str | None = None
    time_horizon: TimeHorizon | None = None
    execution_style: ExecutionStyle | None = None
    volatility_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    hedge_preference: bool | None = None
    leverage_max: Decimal | None = Field(default=None, ge=Decimal("0"))
    mode: ProfileMode | None = None
    automation_level: AutomationLevel | None = None
    session_preferences: dict[str, Any] | None = None
    news_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    event_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    diversification_policy: dict[str, Any] | None = None
    paper_trading_days: int | None = Field(default=None, ge=0)
    paper_sharpe: float | None = None
    jurisdiction: Jurisdiction | None = None
    account_type: AccountType | None = None
    broker_agreement_status: BrokerAgreementStatus | None = None

    @field_validator("allowed_instrument_ids")
    @classmethod
    def unique_instrument_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("allowed_instrument_ids must not contain duplicates")
        return value


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row: ProfileORM) -> ProfileRead:
        categories = [AssetCategory(c) for c in (row.allowed_categories or [])]
        jurisdiction = row.jurisdiction or Jurisdiction.GLOBAL.value
        account_type = row.account_type or AccountType.RETAIL.value
        broker_status = row.broker_agreement_status or BrokerAgreementStatus.PENDING.value
        return cls(
            id=row.id,
            risk_appetite=RiskAppetite(row.risk_appetite),
            max_drawdown_pct=row.max_drawdown_pct,
            max_daily_loss_abs=row.max_daily_loss_abs,
            allowed_categories=categories,
            allowed_instrument_ids=list(row.allowed_instrument_ids or []),
            approval_policy_id=row.approval_policy_id,
            time_horizon=TimeHorizon(row.time_horizon),
            execution_style=ExecutionStyle(row.execution_style),
            volatility_tolerance=row.volatility_tolerance,
            hedge_preference=row.hedge_preference,
            leverage_max=row.leverage_max,
            mode=ProfileMode(row.mode),
            automation_level=AutomationLevel(row.automation_level),
            session_preferences=row.session_preferences or {},
            news_sensitivity=row.news_sensitivity,
            event_sensitivity=row.event_sensitivity,
            diversification_policy=row.diversification_policy or {},
            paper_trading_days=row.paper_trading_days,
            paper_sharpe=row.paper_sharpe,
            jurisdiction=Jurisdiction(jurisdiction),
            account_type=AccountType(account_type),
            broker_agreement_status=BrokerAgreementStatus(broker_status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class LiveTransitionResult(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
