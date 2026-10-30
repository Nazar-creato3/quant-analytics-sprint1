"""Unit tests for ComplianceAccessLayer — jurisdiction and account_type narrowing."""
from __future__ import annotations

from decimal import Decimal

from app.domain.compliance import AccountType, BrokerAgreementStatus, Jurisdiction
from app.domain.enums import AssetCategory
from app.domain.profile import ProfileBase, ProfileMode
from app.services.compliance import (
    ComplianceContext,
    ComplianceStrategyHook,
    check_category_access,
    check_instrument_access,
    resolve_compliance_access,
    resolve_effective_profile_access,
)
from app.services.sleeve import ComplianceIntentRequest, SleeveEngine


def _profile(**overrides: object) -> ProfileBase:
    defaults = {
        "allowed_categories": [],
        "allowed_instrument_ids": [],
        "leverage_max": Decimal("5"),
        "mode": ProfileMode.PAPER,
        "jurisdiction": Jurisdiction.GLOBAL,
        "account_type": AccountType.RETAIL,
        "broker_agreement_status": BrokerAgreementStatus.SIGNED,
    }
    defaults.update(overrides)
    return ProfileBase.model_validate(defaults)


class TestCompliancePolicy:
    def test_global_retail_paper_includes_crypto(self):
        result = resolve_compliance_access(
            ComplianceContext(
                jurisdiction=Jurisdiction.GLOBAL,
                account_type=AccountType.RETAIL,
                market_mode=ProfileMode.PAPER,
                broker_agreement_status=BrokerAgreementStatus.SIGNED,
            )
        )
        assert AssetCategory.CRYPTO in result.allowed_categories
        assert result.allowed_leverage >= Decimal("1")

    def test_us_retail_live_excludes_crypto(self):
        result = resolve_compliance_access(
            ComplianceContext(
                jurisdiction=Jurisdiction.US,
                account_type=AccountType.RETAIL,
                market_mode=ProfileMode.LIVE,
                broker_agreement_status=BrokerAgreementStatus.SIGNED,
            )
        )
        assert AssetCategory.EQUITIES in result.allowed_categories
        assert AssetCategory.CRYPTO not in result.allowed_categories

    def test_jurisdiction_change_narrows_allowed_set(self):
        global_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.GLOBAL,
            account_type=AccountType.RETAIL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        us_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        global_access = resolve_compliance_access(global_ctx)
        us_access = resolve_compliance_access(us_ctx)

        assert us_access.allowed_categories < global_access.allowed_categories
        assert AssetCategory.CRYPTO in global_access.allowed_categories
        assert AssetCategory.CRYPTO not in us_access.allowed_categories

    def test_account_type_retail_to_professional_expands_set(self):
        retail_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        pro_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.PROFESSIONAL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        retail_access = resolve_compliance_access(retail_ctx)
        pro_access = resolve_compliance_access(pro_ctx)

        assert pro_access.allowed_categories > retail_access.allowed_categories
        assert AssetCategory.CRYPTO in pro_access.allowed_categories

    def test_account_type_change_narrows_when_downgrading(self):
        pro_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.EU,
            account_type=AccountType.PROFESSIONAL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        retail_ctx = ComplianceContext(
            jurisdiction=Jurisdiction.EU,
            account_type=AccountType.RETAIL,
            market_mode=ProfileMode.PAPER,
            broker_agreement_status=BrokerAgreementStatus.SIGNED,
        )
        pro_access = resolve_compliance_access(pro_ctx)
        retail_access = resolve_compliance_access(retail_ctx)

        assert retail_access.allowed_categories < pro_access.allowed_categories
        assert AssetCategory.CRYPTO in pro_access.allowed_categories
        assert AssetCategory.CRYPTO not in retail_access.allowed_categories

    def test_live_without_signed_agreement_blocks_all_categories(self):
        result = resolve_compliance_access(
            ComplianceContext(
                jurisdiction=Jurisdiction.GLOBAL,
                account_type=AccountType.RETAIL,
                market_mode=ProfileMode.LIVE,
                broker_agreement_status=BrokerAgreementStatus.PENDING,
            )
        )
        assert result.allowed_categories == frozenset()

    def test_revoked_agreement_blocks_live_access(self):
        result = resolve_compliance_access(
            ComplianceContext(
                jurisdiction=Jurisdiction.GLOBAL,
                account_type=AccountType.PROFESSIONAL,
                market_mode=ProfileMode.LIVE,
                broker_agreement_status=BrokerAgreementStatus.REVOKED,
            )
        )
        assert result.allowed_categories == frozenset()
        assert result.allowed_leverage == Decimal("1")

    def test_ru_retail_excludes_crypto(self):
        result = resolve_compliance_access(
            ComplianceContext(
                jurisdiction=Jurisdiction.RU,
                account_type=AccountType.RETAIL,
                market_mode=ProfileMode.PAPER,
                broker_agreement_status=BrokerAgreementStatus.SIGNED,
            )
        )
        assert AssetCategory.EQUITIES in result.allowed_categories
        assert AssetCategory.CRYPTO not in result.allowed_categories


class TestEffectiveProfileAccess:
    def test_intersects_profile_categories_with_compliance(self):
        profile = _profile(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            allowed_categories=[AssetCategory.EQUITIES, AssetCategory.CRYPTO],
        )
        effective = resolve_effective_profile_access(profile)

        assert AssetCategory.EQUITIES in effective.allowed_categories
        assert AssetCategory.CRYPTO not in effective.allowed_categories

    def test_leverage_capped_by_compliance(self):
        profile = _profile(
            account_type=AccountType.RETAIL,
            leverage_max=Decimal("10"),
        )
        effective = resolve_effective_profile_access(profile)

        assert effective.allowed_leverage <= Decimal("2")


class TestComplianceGates:
    def test_check_category_access_blocks_restricted_category(self):
        profile = _profile(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            mode=ProfileMode.LIVE,
        )
        result = check_category_access(AssetCategory.CRYPTO, profile)

        assert result.allowed is False
        assert "blocked by compliance" in result.reason

    def test_check_instrument_access_allows_permitted_category(self):
        profile = _profile(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            mode=ProfileMode.PAPER,
        )
        result = check_instrument_access(42, AssetCategory.EQUITIES, profile)

        assert result.allowed is True


class TestSleeveEngineComplianceIntegration:
    def test_validate_compliance_access_blocks_crypto_for_us_retail_live(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        profile = _profile(
            jurisdiction=Jurisdiction.US,
            account_type=AccountType.RETAIL,
            mode=ProfileMode.LIVE,
        )
        result = engine.validate_compliance_access(
            ComplianceIntentRequest(
                instrument_id=1,
                instrument_category=AssetCategory.CRYPTO,
                profile=profile,
            )
        )

        assert result.allowed is False


class TestStrategyComplianceHook:
    def test_propose_intent_blocked_without_compliance(self):
        hook = ComplianceStrategyHook()
        profile = _profile(
            jurisdiction=Jurisdiction.RU,
            account_type=AccountType.RETAIL,
        )
        proposal = hook.propose_intent(
            profile=profile,
            instrument_id=99,
            instrument_category=AssetCategory.CRYPTO,
            analyze=lambda _ctx: None,
            market_context={},
        )

        assert proposal.blocked is True
        assert proposal.intent is None
        assert proposal.compliance.allowed is False
