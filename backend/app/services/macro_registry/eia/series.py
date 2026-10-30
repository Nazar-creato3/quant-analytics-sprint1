"""EIA series catalog for macro registry seeding."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EiaSeriesSpec:
    source_id: str
    symbol: str
    legacy_code: str
    series_id: str
    unit: str
    currency: str
    description: str


EIA_SERIES: tuple[EiaSeriesSpec, ...] = (
    EiaSeriesSpec(
        source_id="eia_brent_spot",
        symbol="BRENT_OIL",
        legacy_code="oil_brent",
        series_id="PET.RBRTE.D",
        unit="USD/barrel",
        currency="USD",
        description="Europe Brent spot FOB (daily)",
    ),
    EiaSeriesSpec(
        source_id="eia_wti_spot",
        symbol="WTI_OIL",
        legacy_code="oil_wti",
        series_id="PET.RWTC.D",
        unit="USD/barrel",
        currency="USD",
        description="Cushing OK WTI spot FOB (daily)",
    ),
    EiaSeriesSpec(
        source_id="eia_ng_henry_hub",
        symbol="NG_HENRY_HUB",
        legacy_code="ng_gas",
        series_id="NG.RNGWHHD.D",
        unit="USD/MMBtu",
        currency="USD",
        description="Henry Hub natural gas spot (daily)",
    ),
)


def eia_endpoint(series_id: str) -> str:
    return f"adapter:eia:{series_id}"
