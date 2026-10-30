"""Curated Eurostat bulk datasets mapped to macro registry instruments."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EurostatIndicatorSpec:
    source_id: str
    symbol: str
    legacy_code: str
    dataset_file: str
    geo: str
    filters: dict[str, str]
    unit: str
    description: str
    derive: str = "latest"
    optional: bool = False


# Datasets confirmed in local ESTAT_downloads_data_* zips (SDMX-CSV).
# prc_hicp_* / une_rt_* are not present in the current bulk export — marked optional.
EUROSTAT_INDICATORS: tuple[EurostatIndicatorSpec, ...] = (
    EurostatIndicatorSpec(
        source_id="eu_gdp_growth",
        symbol="EU_GDP_GROWTH",
        legacy_code="eu_gdp_growth",
        dataset_file="tec00115.csv",
        geo="EA19",
        filters={"na_item": "B1GQ", "unit": "CLV_PCH_PRE", "freq": "A"},
        unit="%",
        description="Euro area GDP volume growth (annual %)",
    ),
    EurostatIndicatorSpec(
        source_id="eu_gdp_yoy_q",
        symbol="EU_GDP_YOY_Q",
        legacy_code="eu_gdp_yoy_q",
        dataset_file="namq_10_gdp.csv",
        geo="EA19",
        filters={"na_item": "B1GQ", "unit": "CLV_I10", "s_adj": "SCA", "freq": "Q"},
        unit="%",
        derive="yoy_quarterly",
        description="Euro area GDP YoY growth (quarterly volume, seasonally adjusted)",
    ),
    EurostatIndicatorSpec(
        source_id="eu_hicp_yoy",
        symbol="EU_HICP_YOY",
        legacy_code="eu_hicp_yoy",
        dataset_file="prc_hicp_manr.csv",
        geo="EA19",
        filters={"coicop1999": "CP00", "unit": "RCH_A_AVG"},
        unit="%",
        description="Euro area HICP inflation (annual rate, all-items)",
        optional=True,
    ),
    EurostatIndicatorSpec(
        source_id="eu_unemployment",
        symbol="EU_UNEMPLOYMENT",
        legacy_code="eu_unemployment",
        dataset_file="une_rt_m.csv",
        geo="EA19",
        filters={"age": "Y15-74", "sex": "T", "s_adj": "SA", "unit": "PC_ACT"},
        unit="%",
        description="Euro area unemployment rate (seasonally adjusted)",
        optional=True,
    ),
    EurostatIndicatorSpec(
        source_id="eu_esi_consumer",
        symbol="EU_ESI_CONSUMER",
        legacy_code="eu_esi_consumer",
        dataset_file="ei_bsco_m.csv",
        geo="EA19",
        filters={"indic": "BS-CSMCI", "s_adj": "SA"},
        unit="bal",
        description="Euro area consumer confidence (ESI, monthly balance)",
        optional=True,
    ),
    EurostatIndicatorSpec(
        source_id="eu_esi_industry",
        symbol="EU_ESI_INDUSTRY",
        legacy_code="eu_esi_industry",
        dataset_file="ei_bsin_m.csv",
        geo="EA19",
        filters={"indic": "BS-ICI", "s_adj": "SA"},
        unit="bal",
        description="Euro area industrial confidence (ESI, monthly balance)",
        optional=True,
    ),
)


def eurostat_bulk_endpoint(spec_id: str) -> str:
    return f"adapter:eurostat_bulk:{spec_id}"


def spec_by_id(spec_id: str) -> EurostatIndicatorSpec | None:
    for spec in EUROSTAT_INDICATORS:
        if spec.source_id == spec_id:
            return spec
    return None


def spec_by_dataset_file(dataset_file: str) -> EurostatIndicatorSpec | None:
    name = dataset_file.strip().lower()
    for spec in EUROSTAT_INDICATORS:
        if spec.dataset_file.lower() == name:
            return spec
    return None
