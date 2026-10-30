"""ComplianceAccessLayer — pure policy for regulatory market access."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.compliance import AccountType, BrokerAgreementStatus, Jurisdiction
from app.domain.enums import AssetCategory
from app.domain.profile import ProfileBase, ProfileMode

# Base category sets by jurisdiction and account type (regulatory ceiling, pre-mode).
_JURISDICTION_ACCOUNT_BASE: dict[tuple[Jurisdiction, AccountType], frozenset[AssetCategory]] = {
    (Jurisdiction.GLOBAL, AccountType.RETAIL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.GLOBAL, AccountType.PROFESSIONAL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.THEMATIC_BASKET,
            AssetCategory.SECTOR_BASKET,
            AssetCategory.MACRO_HEDGE,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
            AssetCategory.SPECULATIVE_SLEEVE,
        }
    ),
    (Jurisdiction.GLOBAL, AccountType.INSTITUTIONAL): frozenset(AssetCategory),
    (Jurisdiction.US, AccountType.RETAIL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.US, AccountType.PROFESSIONAL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.INDICES,
            AssetCategory.THEMATIC_BASKET,
            AssetCategory.SECTOR_BASKET,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
            AssetCategory.SPECULATIVE_SLEEVE,
        }
    ),
    (Jurisdiction.US, AccountType.INSTITUTIONAL): frozenset(AssetCategory),
    (Jurisdiction.EU, AccountType.RETAIL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.EU, AccountType.PROFESSIONAL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.THEMATIC_BASKET,
            AssetCategory.MACRO_HEDGE,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.EU, AccountType.INSTITUTIONAL): frozenset(AssetCategory),
    (Jurisdiction.UK, AccountType.RETAIL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.UK, AccountType.PROFESSIONAL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
            AssetCategory.SPECULATIVE_SLEEVE,
        }
    ),
    (Jurisdiction.UK, AccountType.INSTITUTIONAL): frozenset(AssetCategory),
    (Jurisdiction.RU, AccountType.RETAIL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.COMMODITIES,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    # Product note: live crypto for RU requires a non-RU venue (Tinkoff has no spot crypto).
    (Jurisdiction.RU, AccountType.PROFESSIONAL): frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.FX,
            AssetCategory.COMMODITIES,
            AssetCategory.RATES_BONDS,
            AssetCategory.INDICES,
            AssetCategory.INCOME_SLEEVE,
            AssetCategory.DEFENSIVE_SLEEVE,
        }
    ),
    (Jurisdiction.RU, AccountType.INSTITUTIONAL): frozenset(AssetCategory),
}

# Live-mode retail restrictions applied on top of jurisdiction base (paper exempt).
_LIVE_RETAIL_EXCLUDED: frozenset[AssetCategory] = frozenset(
    {
        AssetCategory.CRYPTO,
        AssetCategory.FX,
        AssetCategory.SPECULATIVE_SLEEVE,
        AssetCategory.MACRO_HEDGE,
        AssetCategory.EVENT_DRIVEN_WATCHLIST,
        AssetCategory.CUSTOM_USER_BASKET,
    }
)

_LEVERAGE_CEILING: dict[AccountType, Decimal] = {
    AccountType.RETAIL: Decimal("1"),
    AccountType.PROFESSIONAL: Decimal("5"),
    AccountType.INSTITUTIONAL: Decimal("10"),
}

_PAPER_LEVERAGE_BONUS: Decimal = Decimal("2")


@dataclass(frozen=True, slots=True)
class ComplianceContext:
    """Inputs for regulatory access policy evaluation."""

    jurisdiction: Jurisdiction
    account_type: AccountType
    market_mode: ProfileMode
    broker_agreement_status: BrokerAgreementStatus


@dataclass(frozen=True, slots=True)
class ComplianceAccessResult:
    """Regulatory ceiling for categories, instruments, and leverage."""

    allowed_categories: frozenset[AssetCategory]
    allowed_instruments: frozenset[int]
    allowed_leverage: Decimal


@dataclass(frozen=True, slots=True)
class EffectiveProfileAccess:
    """Profile constitution intersected with compliance ceiling."""

    allowed_categories: frozenset[AssetCategory]
    allowed_instruments: frozenset[int]
    allowed_leverage: Decimal
    compliance: ComplianceAccessResult


@dataclass(frozen=True, slots=True)
class ComplianceGateResult:
    allowed: bool
    reason: str


def resolve_compliance_access(context: ComplianceContext) -> ComplianceAccessResult:
    """Pure policy: jurisdiction × account_type × mode × broker agreement → access set."""
    base = _JURISDICTION_ACCOUNT_BASE.get(
        (context.jurisdiction, context.account_type),
        frozenset(),
    )
    categories = set(base)

    if context.market_mode == ProfileMode.LIVE:
        if context.broker_agreement_status != BrokerAgreementStatus.SIGNED:
            categories.clear()
        elif context.account_type == AccountType.RETAIL:
            categories -= _LIVE_RETAIL_EXCLUDED
        if context.broker_agreement_status in {
            BrokerAgreementStatus.SUSPENDED,
            BrokerAgreementStatus.REVOKED,
        }:
            categories.clear()

    leverage = _LEVERAGE_CEILING[context.account_type]
    if context.market_mode == ProfileMode.PAPER:
        leverage = min(leverage * _PAPER_LEVERAGE_BONUS, Decimal("10"))
    if context.broker_agreement_status != BrokerAgreementStatus.SIGNED:
        leverage = Decimal("1")

    return ComplianceAccessResult(
        allowed_categories=frozenset(categories),
        allowed_instruments=frozenset(),
        allowed_leverage=leverage,
    )


def compliance_context_from_profile(profile: ProfileBase) -> ComplianceContext:
    return ComplianceContext(
        jurisdiction=profile.jurisdiction,
        account_type=profile.account_type,
        market_mode=profile.mode,
        broker_agreement_status=profile.broker_agreement_status,
    )


def resolve_effective_profile_access(profile: ProfileBase) -> EffectiveProfileAccess:
    """Intersect profile constitution preferences with compliance ceiling."""
    compliance = resolve_compliance_access(compliance_context_from_profile(profile))

    if profile.allowed_categories:
        categories = frozenset(profile.allowed_categories) & compliance.allowed_categories
    else:
        categories = compliance.allowed_categories

    if profile.allowed_instrument_ids:
        instruments = frozenset(profile.allowed_instrument_ids)
        if compliance.allowed_instruments:
            instruments &= compliance.allowed_instruments
    elif compliance.allowed_instruments:
        instruments = compliance.allowed_instruments
    else:
        instruments = frozenset()

    leverage = min(profile.leverage_max, compliance.allowed_leverage)

    return EffectiveProfileAccess(
        allowed_categories=categories,
        allowed_instruments=instruments,
        allowed_leverage=leverage,
        compliance=compliance,
    )


def check_category_access(
    category: AssetCategory,
    profile: ProfileBase,
) -> ComplianceGateResult:
    """Return whether ``category`` is permitted for ``profile``."""
    effective = resolve_effective_profile_access(profile)
    if category in effective.allowed_categories:
        return ComplianceGateResult(
            allowed=True,
            reason=f"category {category.value} permitted by compliance and profile constitution",
        )
    return ComplianceGateResult(
        allowed=False,
        reason=(
            f"category {category.value} blocked by compliance access layer "
            f"(jurisdiction={profile.jurisdiction.value}, "
            f"account_type={profile.account_type.value}, "
            f"mode={profile.mode.value}, "
            f"broker_agreement={profile.broker_agreement_status.value})"
        ),
    )


def check_instrument_access(
    instrument_id: int,
    category: AssetCategory,
    profile: ProfileBase,
) -> ComplianceGateResult:
    """Return whether a new DealIntent for ``instrument_id`` / ``category`` is permitted."""
    category_result = check_category_access(category, profile)
    if not category_result.allowed:
        return category_result

    effective = resolve_effective_profile_access(profile)
    if effective.allowed_instruments and instrument_id not in effective.allowed_instruments:
        return ComplianceGateResult(
            allowed=False,
            reason=(
                f"instrument_id {instrument_id} not in effective allowed_instruments "
                f"after compliance intersection"
            ),
        )

    return ComplianceGateResult(
        allowed=True,
        reason=f"instrument {instrument_id} ({category.value}) permitted",
    )
