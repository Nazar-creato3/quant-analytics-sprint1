"""World Bank indicator catalog for macro registry seeding."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorldBankIndicatorSpec:
    source_id: str
    symbol: str
    legacy_code: str
    country_code: str
    indicator_code: str
    unit: str
    description: str


# Curated global macro indicators — all available via free World Bank API (no key).
WORLD_BANK_INDICATORS: tuple[WorldBankIndicatorSpec, ...] = (
    WorldBankIndicatorSpec(
        source_id="wb_us_gdp_growth",
        symbol="WB_US_GDP_GROWTH",
        legacy_code="wb_us_gdp_growth",
        country_code="USA",
        indicator_code="NY.GDP.MKTP.KD.ZG",
        unit="%",
        description="US GDP growth (annual %)",
    ),
    WorldBankIndicatorSpec(
        source_id="wb_cn_gdp_growth",
        symbol="WB_CN_GDP_GROWTH",
        legacy_code="wb_cn_gdp_growth",
        country_code="CHN",
        indicator_code="NY.GDP.MKTP.KD.ZG",
        unit="%",
        description="China GDP growth (annual %)",
    ),
    WorldBankIndicatorSpec(
        source_id="wb_ru_gdp_growth",
        symbol="WB_RU_GDP_GROWTH",
        legacy_code="wb_ru_gdp_growth",
        country_code="RUS",
        indicator_code="NY.GDP.MKTP.KD.ZG",
        unit="%",
        description="Russia GDP growth (annual %)",
    ),
    WorldBankIndicatorSpec(
        source_id="wb_world_gdp_growth",
        symbol="WB_WLD_GDP_GROWTH",
        legacy_code="wb_world_gdp_growth",
        country_code="WLD",
        indicator_code="NY.GDP.MKTP.KD.ZG",
        unit="%",
        description="World GDP growth (annual %)",
    ),
    WorldBankIndicatorSpec(
        source_id="wb_us_inflation",
        symbol="WB_US_INFLATION",
        legacy_code="wb_us_inflation",
        country_code="USA",
        indicator_code="FP.CPI.TOTL.ZG",
        unit="%",
        description="US CPI inflation (annual %)",
    ),
    WorldBankIndicatorSpec(
        source_id="wb_us_current_account",
        symbol="WB_US_CURRENT_ACCOUNT",
        legacy_code="wb_us_current_account",
        country_code="USA",
        indicator_code="BN.CAB.XOKA.GD.ZS",
        unit="% of GDP",
        description="US current account balance (% of GDP)",
    ),
)


def world_bank_endpoint(country_code: str, indicator_code: str) -> str:
    return f"adapter:world_bank:{country_code}:{indicator_code}"


def world_bank_bulk_endpoint(country_code: str, indicator_code: str) -> str:
    return f"adapter:world_bank_bulk:{country_code}:{indicator_code}"


# Country/indicator pairs present in local WORLD_BANK.zip bulk export.
WORLD_BANK_BULK_AVAILABLE: frozenset[tuple[str, str]] = frozenset(
    {
        ("USA", "NY.GDP.MKTP.KD.ZG"),
        ("CHN", "NY.GDP.MKTP.KD.ZG"),
        ("USA", "FP.CPI.TOTL.ZG"),
    }
)
