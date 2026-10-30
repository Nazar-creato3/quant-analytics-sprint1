"""Unit tests for trading profile constitution and ProfileService."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.enums import AssetCategory
from app.domain.profile import (
    AutomationLevel,
    ExecutionStyle,
    ProfileBase,
    ProfileMode,
    ProfileORM,
    ProfileRead,
    ProfileUpdate,
    RiskAppetite,
    TimeHorizon,
)
from app.services.profile.service import (
    LiveTransitionBlockedError,
    ProfileNotFoundError,
    ProfileService,
    ProfileValidationError,
    validate_live_transition,
)


def _settings(**overrides: object) -> Settings:
    return Settings(
        **{
            "PAPER_TRADING_MIN_DAYS": 30,
            "PAPER_SHARPE_MIN_THRESHOLD": 0.5,
            **overrides,
        }
    )


def _qualified_profile(**overrides: object) -> ProfileBase:
    defaults = {
        "risk_appetite": RiskAppetite.MODERATE,
        "max_drawdown_pct": Decimal("10"),
        "max_daily_loss_abs": Decimal("1000"),
        "allowed_categories": [AssetCategory.EQUITIES, AssetCategory.ETF],
        "allowed_instrument_ids": [],
        "time_horizon": TimeHorizon.SWING,
        "execution_style": ExecutionStyle.ACTIVE,
        "volatility_tolerance": 0.5,
        "hedge_preference": False,
        "leverage_max": Decimal("1"),
        "mode": ProfileMode.PAPER,
        "automation_level": AutomationLevel.SEMI_AUTO,
        "paper_trading_days": 45,
        "paper_sharpe": 1.2,
    }
    defaults.update(overrides)
    return ProfileBase(**defaults)


class TestProfileBaseValidation:
    def test_valid_defaults(self):
        profile = _qualified_profile()
        assert profile.mode == ProfileMode.PAPER
        assert profile.risk_appetite == RiskAppetite.MODERATE

    def test_rejects_volatility_out_of_range(self):
        with pytest.raises(ValidationError):
            _qualified_profile(volatility_tolerance=1.5)

    def test_rejects_news_sensitivity_out_of_range(self):
        with pytest.raises(ValidationError):
            _qualified_profile(news_sensitivity=-0.1)

    def test_rejects_event_sensitivity_out_of_range(self):
        with pytest.raises(ValidationError):
            _qualified_profile(event_sensitivity=2.0)

    def test_rejects_zero_max_drawdown(self):
        with pytest.raises(ValidationError):
            _qualified_profile(max_drawdown_pct=Decimal("0"))

    def test_rejects_negative_leverage(self):
        with pytest.raises(ValidationError):
            _qualified_profile(leverage_max=Decimal("-0.1"))

    def test_rejects_duplicate_instrument_ids(self):
        with pytest.raises(ValidationError):
            _qualified_profile(allowed_instrument_ids=[1, 1, 2])

    def test_conservative_aggressive_execution_incompatible(self):
        with pytest.raises(ValidationError, match="incompatible"):
            _qualified_profile(
                risk_appetite=RiskAppetite.CONSERVATIVE,
                execution_style=ExecutionStyle.AGGRESSIVE,
            )

    def test_conservative_leverage_above_one_incompatible(self):
        with pytest.raises(ValidationError, match="leverage_max"):
            _qualified_profile(
                risk_appetite=RiskAppetite.CONSERVATIVE,
                leverage_max=Decimal("2"),
            )

    def test_long_term_aggressive_execution_incompatible(self):
        with pytest.raises(ValidationError, match="long_term"):
            _qualified_profile(
                time_horizon=TimeHorizon.LONG_TERM,
                execution_style=ExecutionStyle.AGGRESSIVE,
            )

    def test_intraday_passive_manual_incompatible(self):
        with pytest.raises(ValidationError, match="intraday"):
            _qualified_profile(
                time_horizon=TimeHorizon.INTRADAY,
                execution_style=ExecutionStyle.PASSIVE,
                automation_level=AutomationLevel.MANUAL,
            )

    def test_aggressive_passive_full_auto_incompatible(self):
        with pytest.raises(ValidationError, match="full_auto"):
            _qualified_profile(
                risk_appetite=RiskAppetite.AGGRESSIVE,
                execution_style=ExecutionStyle.PASSIVE,
                automation_level=AutomationLevel.FULL_AUTO,
            )

    def test_allowed_categories_accepts_asset_category_enum(self):
        profile = _qualified_profile(allowed_categories=[AssetCategory.CRYPTO])
        assert profile.allowed_categories == [AssetCategory.CRYPTO]


class TestValidateLiveTransition:
    def test_allows_when_criteria_met(self):
        profile = _qualified_profile(paper_trading_days=30, paper_sharpe=0.5)
        result = validate_live_transition(profile, settings=_settings())
        assert result.allowed is True
        assert result.reasons == []

    def test_blocks_insufficient_paper_days(self):
        profile = _qualified_profile(paper_trading_days=29, paper_sharpe=2.0)
        result = validate_live_transition(profile, settings=_settings())
        assert result.allowed is False
        assert any("paper_trading_days" in r for r in result.reasons)

    def test_blocks_missing_paper_sharpe(self):
        profile = _qualified_profile(paper_trading_days=60, paper_sharpe=None)
        result = validate_live_transition(profile, settings=_settings())
        assert result.allowed is False
        assert any("paper_sharpe is not recorded" in r for r in result.reasons)

    def test_blocks_low_paper_sharpe(self):
        profile = _qualified_profile(paper_trading_days=60, paper_sharpe=0.49)
        result = validate_live_transition(profile, settings=_settings(PAPER_SHARPE_MIN_THRESHOLD=0.5))
        assert result.allowed is False
        assert any("paper_sharpe" in r for r in result.reasons)

    def test_blocks_multiple_reasons(self):
        profile = ProfileRead.model_construct(
            id="user-x",
            risk_appetite=RiskAppetite.CONSERVATIVE,
            max_drawdown_pct=Decimal("10"),
            max_daily_loss_abs=Decimal("0"),
            allowed_categories=[AssetCategory.EQUITIES],
            allowed_instrument_ids=[],
            approval_policy_id=None,
            time_horizon=TimeHorizon.SWING,
            execution_style=ExecutionStyle.AGGRESSIVE,
            volatility_tolerance=0.5,
            hedge_preference=False,
            leverage_max=Decimal("1"),
            mode=ProfileMode.PAPER,
            automation_level=AutomationLevel.MANUAL,
            session_preferences={},
            news_sensitivity=0.5,
            event_sensitivity=0.5,
            diversification_policy={},
            paper_trading_days=5,
            paper_sharpe=0.1,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result = validate_live_transition(profile, settings=_settings())
        assert result.allowed is False
        assert len(result.reasons) >= 2

    def test_respects_config_thresholds(self):
        profile = _qualified_profile(paper_trading_days=10, paper_sharpe=0.3)
        strict = validate_live_transition(
            profile,
            settings=_settings(PAPER_TRADING_MIN_DAYS=10, PAPER_SHARPE_MIN_THRESHOLD=0.3),
        )
        assert strict.allowed is True


class TestProfileService:
    @pytest.fixture
    def now(self):
        return datetime(2026, 7, 17, tzinfo=timezone.utc)

    @pytest.fixture
    def existing_row(self, now):
        return ProfileORM(
            id="user-1",
            risk_appetite=RiskAppetite.MODERATE.value,
            max_drawdown_pct=Decimal("15"),
            max_daily_loss_abs=Decimal("0"),
            allowed_categories=["equities"],
            allowed_instrument_ids=[],
            time_horizon=TimeHorizon.SWING.value,
            execution_style=ExecutionStyle.ACTIVE.value,
            volatility_tolerance=0.5,
            hedge_preference=False,
            leverage_max=Decimal("1"),
            mode=ProfileMode.PAPER.value,
            automation_level=AutomationLevel.MANUAL.value,
            session_preferences={},
            news_sensitivity=0.5,
            event_sensitivity=0.5,
            diversification_policy={},
            paper_trading_days=40,
            paper_sharpe=1.0,
            created_at=now,
            updated_at=now,
        )

    @pytest.fixture
    def db(self, existing_row):
        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, pk: existing_row if pk == "user-1" else None)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=lambda row: None)
        session.add = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, db):
        return ProfileService(db, settings=_settings())

    @pytest.mark.asyncio
    async def test_get_existing_profile(self, service, existing_row):
        profile = await service.get("user-1", create_if_missing=False)
        assert profile.id == "user-1"
        assert profile.mode == ProfileMode.PAPER
        assert profile.allowed_categories == [AssetCategory.EQUITIES]

    @pytest.mark.asyncio
    async def test_get_missing_without_create_raises(self, db):
        db.get = AsyncMock(return_value=None)
        service = ProfileService(db, settings=_settings())
        with pytest.raises(ProfileNotFoundError):
            await service.get("missing", create_if_missing=False)

    @pytest.mark.asyncio
    async def test_get_creates_default_profile(self, db):
        db.get = AsyncMock(return_value=None)
        service = ProfileService(db, settings=_settings())
        profile = await service.get("new-user")
        assert profile.id == "new-user"
        assert profile.mode == ProfileMode.PAPER
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_paper_fields(self, service, existing_row):
        patch = ProfileUpdate(
            risk_appetite=RiskAppetite.AGGRESSIVE,
            allowed_categories=[AssetCategory.CRYPTO, AssetCategory.EQUITIES],
            paper_trading_days=50,
        )
        updated = await service.update("user-1", patch)
        assert updated.risk_appetite == RiskAppetite.AGGRESSIVE
        assert AssetCategory.CRYPTO in updated.allowed_categories
        assert existing_row.risk_appetite == RiskAppetite.AGGRESSIVE.value

    @pytest.mark.asyncio
    async def test_update_rejects_incompatible_patch(self, service):
        patch = ProfileUpdate(
            risk_appetite=RiskAppetite.CONSERVATIVE,
            execution_style=ExecutionStyle.AGGRESSIVE,
        )
        with pytest.raises(ValidationError):
            await service.update("user-1", patch)

    @pytest.mark.asyncio
    async def test_update_to_live_when_qualified(self, service, existing_row):
        patch = ProfileUpdate(mode=ProfileMode.LIVE)
        updated = await service.update("user-1", patch)
        assert updated.mode == ProfileMode.LIVE
        assert existing_row.mode == ProfileMode.LIVE.value

    @pytest.mark.asyncio
    async def test_update_to_live_blocked_insufficient_paper(self, service, existing_row):
        existing_row.paper_trading_days = 10
        patch = ProfileUpdate(mode=ProfileMode.LIVE)
        with pytest.raises(LiveTransitionBlockedError, match="paper_trading_days"):
            await service.update("user-1", patch)

    @pytest.mark.asyncio
    async def test_update_to_live_blocked_low_sharpe(self, service, existing_row):
        existing_row.paper_sharpe = 0.2
        patch = ProfileUpdate(mode=ProfileMode.LIVE)
        with pytest.raises(LiveTransitionBlockedError, match="paper_sharpe"):
            await service.update("user-1", patch)

    @pytest.mark.asyncio
    async def test_update_stays_paper_without_gate(self, service, existing_row):
        existing_row.paper_trading_days = 0
        existing_row.paper_sharpe = None
        patch = ProfileUpdate(max_drawdown_pct=Decimal("12"))
        updated = await service.update("user-1", patch)
        assert updated.mode == ProfileMode.PAPER

    @pytest.mark.asyncio
    async def test_validate_live_transition_via_service(self, service, existing_row):
        result = await service.validate_live_transition("user-1")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_validate_live_transition_fails(self, service, existing_row):
        existing_row.paper_trading_days = 1
        existing_row.paper_sharpe = 0.0
        result = await service.validate_live_transition("user-1")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_instrument_ids(self, service, db):
        db.execute = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[(1,)]))
        )
        patch = ProfileUpdate(allowed_instrument_ids=[1, 99])
        with pytest.raises(ProfileValidationError, match="unknown instruments"):
            await service.update("user-1", patch)

    @pytest.mark.asyncio
    async def test_update_jsonb_fields(self, service, existing_row):
        patch = ProfileUpdate(
            session_preferences={"moex": {"open": "10:00", "close": "18:45"}},
            diversification_policy={
                "max_pct_per_category": {"equities": 40},
                "max_pct_per_instrument": 10,
                "max_correlation_cluster_pct": 25,
            },
        )
        updated = await service.update("user-1", patch)
        assert updated.session_preferences["moex"]["open"] == "10:00"
        assert updated.diversification_policy["max_pct_per_instrument"] == 10


class TestProfileORM:
    def test_tablename(self):
        assert ProfileORM.__tablename__ == "profiles"

    def test_profile_read_from_orm(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = ProfileORM(
            id="u1",
            risk_appetite="moderate",
            max_drawdown_pct=Decimal("15"),
            max_daily_loss_abs=Decimal("500"),
            allowed_categories=["etf", "crypto"],
            allowed_instrument_ids=[3, 7],
            time_horizon="position",
            execution_style="passive",
            volatility_tolerance=0.3,
            hedge_preference=True,
            leverage_max=Decimal("1.5"),
            mode="paper",
            automation_level="semi_auto",
            session_preferences={"binance": {"open": "00:00"}},
            news_sensitivity=0.7,
            event_sensitivity=0.4,
            diversification_policy={"max_pct_per_instrument": 5},
            paper_trading_days=12,
            paper_sharpe=0.8,
            created_at=now,
            updated_at=now,
        )
        read = ProfileRead.from_orm_row(row)
        assert read.allowed_categories == [AssetCategory.ETF, AssetCategory.CRYPTO]
        assert read.allowed_instrument_ids == [3, 7]
        assert read.hedge_preference is True
