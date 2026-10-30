"""Shared fixtures for integration validation tests."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.compliance import AccountType, Jurisdiction
from app.domain.enums import AssetCategory, SleeveStatus
from app.domain.profile import (
    AutomationLevel,
    ExecutionStyle,
    ProfileMode,
    ProfileRead,
    RiskAppetite,
    TimeHorizon,
)
from app.domain.sleeve import SleeveRead
from app.services.integration.historical_data import generate_synthetic_bars
from app.services.integration.pipeline import ValidationPipeline
from app.services.integration.types import VenueConfig

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def validation_profile() -> ProfileRead:
    return ProfileRead(
        id="profile-e2e",
        risk_appetite=RiskAppetite.MODERATE,
        max_drawdown_pct=Decimal("15"),
        max_daily_loss_abs=Decimal("5000"),
        allowed_categories=[
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
        ],
        allowed_instrument_ids=[],
        approval_policy_id=None,
        time_horizon=TimeHorizon.SWING,
        execution_style=ExecutionStyle.ACTIVE,
        volatility_tolerance=0.6,
        hedge_preference=False,
        leverage_max=Decimal("1"),
        mode=ProfileMode.PAPER,
        automation_level=AutomationLevel.SEMI_AUTO,
        session_preferences={},
        news_sensitivity=0.5,
        event_sensitivity=0.5,
        diversification_policy={"max_correlation": 0.7},
        paper_trading_days=45,
        paper_sharpe=1.0,
        jurisdiction=Jurisdiction.GLOBAL,
        account_type=AccountType.PROFESSIONAL,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture
def crypto_sleeve() -> SleeveRead:
    return SleeveRead(
        id="sleeve-crypto",
        profile_id="profile-e2e",
        name="Crypto",
        category=AssetCategory.CRYPTO,
        capital_allocation_pct=Decimal("30"),
        risk_budget=Decimal("25000"),
        status=SleeveStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture
def equity_sleeve() -> SleeveRead:
    return SleeveRead(
        id="sleeve-equity",
        profile_id="profile-e2e",
        name="Equities",
        category=AssetCategory.EQUITIES,
        capital_allocation_pct=Decimal("50"),
        risk_budget=Decimal("40000"),
        status=SleeveStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture
def validation_pipeline(validation_profile, crypto_sleeve) -> ValidationPipeline:
    return ValidationPipeline(validation_profile, crypto_sleeve)


@pytest.fixture
def synthetic_bars_90():
    return generate_synthetic_bars("BTC-USD", days=90, source="synthetic", seed=42)


@pytest.fixture
def binance_venue() -> VenueConfig:
    return VenueConfig(
        source="binance",
        symbol="BTC-USD",
        instrument_id=1001,
        category=AssetCategory.CRYPTO,
        sleeve_id="sleeve-crypto",
    )


@pytest.fixture
def moex_venue() -> VenueConfig:
    return VenueConfig(
        source="moex",
        symbol="SBER",
        instrument_id=2001,
        category=AssetCategory.EQUITIES,
        sleeve_id="sleeve-equity",
    )


@pytest.fixture
def tinkoff_venue() -> VenueConfig:
    return VenueConfig(
        source="tinkoff",
        symbol="GAZP",
        instrument_id=3001,
        category=AssetCategory.EQUITIES,
        sleeve_id="sleeve-equity",
    )
