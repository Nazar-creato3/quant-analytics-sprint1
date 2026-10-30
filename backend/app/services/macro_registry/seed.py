"""Seed data for macro_source_registry (Prompt 41).

Only confirmed free/public endpoints — no invented URLs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.macro_registry.world_bank.indicators import (
    WORLD_BANK_BULK_AVAILABLE,
    WORLD_BANK_INDICATORS,
    world_bank_bulk_endpoint,
    world_bank_endpoint,
)
from app.services.macro_registry.eia.series import EIA_SERIES, eia_endpoint
from app.services.macro_registry.eurostat.indicators import (
    EUROSTAT_INDICATORS,
    eurostat_bulk_endpoint,
)

MACRO_SOURCE_SEED: list[dict] = [
    {
        "source_id": "cbr_key_rate",
        "category": "rate",
        "symbol": "CBR_KEY_RATE",
        "endpoint": "adapter:cbr_soap",
        "refresh_interval": "0 8 * * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_cbr_key_rate",
    },
    {
        "source_id": "fred_fedfunds",
        "category": "rate",
        "symbol": "FED_FUNDS_RATE",
        "endpoint": "adapter:fred:FEDFUNDS",
        "refresh_interval": "0 9 * * *",
        "priority": 20,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_cpi",
        "category": "inflation",
        "symbol": "US_CPI_YOY",
        "endpoint": "adapter:fred:CPIAUCSL",
        "refresh_interval": "0 10 15 * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_cpi_yoy",
    },
    {
        "source_id": "fred_unrate",
        "category": "employment",
        "symbol": "US_UNEMPLOYMENT",
        "endpoint": "adapter:fred:UNRATE",
        "refresh_interval": "0 10 1 * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_dxy",
        "category": "fx",
        "symbol": "DXY",
        "endpoint": "adapter:fred:DTWEXBGS",
        "refresh_interval": "0 12 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_vix",
        "category": "volatility_index",
        "symbol": "VIX",
        "endpoint": "adapter:fred:VIXCLS",
        "refresh_interval": "0 22 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "yfinance_brent",
        "category": "energy",
        "symbol": "BRENT_OIL",
        "endpoint": "adapter:yfinance:BZ=F",
        "refresh_interval": "0 14 * * 1-5",
        "priority": 50,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_yfinance_close",
    },
    # ── EIA bulk/API energy (PET/NG zips in рыночные данные or EIA_API_KEY) ──
    *[
        {
            "source_id": spec.source_id,
            "category": "energy",
            "symbol": spec.symbol,
            "endpoint": eia_endpoint(spec.series_id),
            "refresh_interval": "0 14 * * 1-5",
            "priority": 15,
            "is_free": True,
            "fallback_source": "yfinance_brent" if spec.source_id == "eia_brent_spot" else None,
            "transformer": "transform_eia_level",
        }
        for spec in EIA_SERIES
    ],
    # ── Spot energy & metals: OilPriceAPI / API Ninjas (keys in .env; else fallback) ──
    {
        "source_id": "oilpriceapi_brent",
        "category": "energy",
        "symbol": "BRENT_OIL",
        "endpoint": "adapter:oilpriceapi:BRENT_CRUDE_USD",
        "refresh_interval": "0 */4 * * *",
        "priority": 5,
        "is_free": False,
        "fallback_source": "fred_brent",
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "oilpriceapi_wti",
        "category": "energy",
        "symbol": "WTI_OIL",
        "endpoint": "adapter:oilpriceapi:WTI_USD",
        "refresh_interval": "0 */4 * * *",
        "priority": 5,
        "is_free": False,
        "fallback_source": "eia_wti_spot",
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "oilpriceapi_natgas",
        "category": "energy",
        "symbol": "NG_HENRY_HUB",
        "endpoint": "adapter:oilpriceapi:NATURAL_GAS_USD",
        "refresh_interval": "0 */4 * * *",
        "priority": 5,
        "is_free": False,
        "fallback_source": "eia_ng_henry_hub",
        "transformer": "transform_fred_level",
    },
    *[
        {
            "source_id": f"apininjas_{name}",
            "category": "commodity",
            "symbol": symbol,
            "endpoint": f"adapter:apininjas:{name}",
            "refresh_interval": "0 */4 * * 1-5",
            "priority": 10,
            "is_free": False,
            "fallback_source": None,
            "transformer": "transform_fred_level",
        }
        for name, symbol in (("gold", "GOLD"), ("silver", "SILVER"), ("platinum", "PLATINUM"), ("copper", "COPPER"))
    ],
    {
        "source_id": "fred_brent",
        "category": "energy",
        "symbol": "BRENT_OIL",
        "endpoint": "adapter:fred:DCOILBRENTEU",
        "refresh_interval": "0 14 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": "eia_brent_spot",
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_hy_spread",
        "category": "credit",
        "symbol": "HY_OAS",
        "endpoint": "adapter:fred:BAMLH0A0HYM2",
        "refresh_interval": "0 16 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_gov_10y",
        "category": "credit",
        "symbol": "GOV_10Y",
        "endpoint": "adapter:fred:DGS10",
        "refresh_interval": "0 16 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fomc_calendar",
        "category": "calendar",
        "symbol": "FOMC_SCHEDULE",
        "endpoint": "adapter:fomc_calendar",
        "refresh_interval": "0 6 * * 1",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_calendar",
    },
    {
        "source_id": "cbr_meeting_calendar",
        "category": "calendar",
        "symbol": "CBR_KEY_RATE_SCHEDULE",
        "endpoint": "adapter:cbr_calendar",
        "refresh_interval": "0 6 * * 1",
        "priority": 20,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_calendar",
    },
    # ── Other major central banks via FRED (ECB deposit rate; OECD «central bank rate» series) ──
    *[
        {
            "source_id": f"fred_cb_{code.lower()}",
            "category": "rate",
            "symbol": symbol,
            "endpoint": f"adapter:fred:{series}",
            "refresh_interval": "0 9 * * *",
            "priority": 20,
            "is_free": True,
            "fallback_source": None,
            "transformer": "transform_fred_level",
        }
        for code, symbol, series in (
            ("ECB", "ECB_DEPOSIT_RATE", "ECBDFR"),
            ("BOE", "BOE_BANK_RATE", "IRSTCB01GBM156N"),
            ("BOJ", "BOJ_POLICY_RATE", "IRSTCB01JPM156N"),
            ("PBOC", "PBOC_POLICY_RATE", "IRSTCB01CNM156N"),
        )
    ],
    # ── Sweden (Riksbank SWEA, open API; optional subscription key) ──
    {
        "source_id": "riksbank_policy_rate",
        "category": "rate",
        "symbol": "SE_POLICY_RATE",
        "endpoint": "adapter:riksbank:SECBREPOEFF",
        "refresh_interval": "0 8 * * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    # ── Canada (BoC Valet + FRED Canada key) ─────────────────
    {
        "source_id": "boc_overnight_rate",
        "category": "rate",
        "symbol": "BOC_OVERNIGHT_RATE",
        "endpoint": "adapter:boc_valet:V39079",
        "refresh_interval": "0 8 * * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": "fred_ca_boc_rate",
        "transformer": "transform_boc_key_rate",
    },
    {
        "source_id": "fred_ca_boc_rate",
        "category": "rate",
        "symbol": "BOC_OVERNIGHT_RATE",
        "endpoint": "adapter:fred_ca:IRSTCB01CAM156N",
        "refresh_interval": "0 8 * * *",
        "priority": 20,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_boc_key_rate",
    },
    {
        "source_id": "fred_ca_cpi",
        "category": "inflation",
        "symbol": "CA_CPI_YOY",
        "endpoint": "adapter:fred_ca:CPALTT01CAM657N",
        "refresh_interval": "0 10 20 * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_ca_unemployment",
        "category": "employment",
        "symbol": "CA_UNEMPLOYMENT",
        "endpoint": "adapter:fred_ca:LRUNTTTTCAM156S",
        "refresh_interval": "0 10 10 * *",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_ca_usdcad",
        "category": "fx",
        "symbol": "USDCAD",
        "endpoint": "adapter:fred_ca:DEXCAUS",
        "refresh_interval": "0 12 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_ca_gov_10y",
        "category": "credit",
        "symbol": "CA_GOV_10Y",
        "endpoint": "adapter:fred_ca:IRLTLT01CAM156N",
        "refresh_interval": "0 16 * * 1-5",
        "priority": 10,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    {
        "source_id": "fred_ca_wti",
        "category": "energy",
        "symbol": "WTI_CANADA",
        "endpoint": "adapter:fred_ca:MCOILWTICO",
        "refresh_interval": "0 14 * * 1-5",
        "priority": 15,
        "is_free": True,
        "fallback_source": None,
        "transformer": "transform_fred_level",
    },
    # ── World Bank (free API — no key) ─────────────────────────
    *[
        {
            "source_id": spec.source_id,
            "category": "global",
            "symbol": spec.symbol,
            "endpoint": world_bank_endpoint(spec.country_code, spec.indicator_code),
            "refresh_interval": "0 6 1 * *",
            "priority": 30,
            "is_free": True,
            "fallback_source": (
                f"{spec.source_id}_bulk"
                if (spec.country_code, spec.indicator_code) in WORLD_BANK_BULK_AVAILABLE
                else None
            ),
            "transformer": "transform_world_bank_level",
        }
        for spec in WORLD_BANK_INDICATORS
    ],
    *[
        {
            "source_id": f"{spec.source_id}_bulk",
            "category": "global",
            "symbol": spec.symbol,
            "endpoint": world_bank_bulk_endpoint(spec.country_code, spec.indicator_code),
            "refresh_interval": "0 6 1 * *",
            "priority": 40,
            "is_free": True,
            "fallback_source": None,
            "transformer": "transform_world_bank_level",
        }
        for spec in WORLD_BANK_INDICATORS
        if (spec.country_code, spec.indicator_code) in WORLD_BANK_BULK_AVAILABLE
    ],
    # ── Eurostat bulk (ESTAT SDMX-CSV zips in EUROSTAT_DATA_DIR) ──
    *[
        {
            "source_id": spec.source_id,
            "category": "regional",
            "symbol": spec.symbol,
            "endpoint": eurostat_bulk_endpoint(spec.source_id),
            "refresh_interval": "0 7 1 * *",
            "priority": 25,
            "is_free": True,
            "fallback_source": None,
            "transformer": "transform_eurostat_level",
        }
        for spec in EUROSTAT_INDICATORS
    ],
    # ── Economic calendar (RapidAPI Investing.com — RAPIDAPI_KEY) ─
    {
        "source_id": "investing_economic_calendar",
        "category": "calendar",
        "symbol": "INVESTING_ECON_CALENDAR",
        "endpoint": "adapter:investing_calendar",
        "refresh_interval": "0 5 * * *",
        "priority": 5,
        "is_free": False,
        "fallback_source": "fomc_calendar",
        "transformer": "transform_calendar",
    },
]

# Instrument symbol → legacy macro_indicators.indicator_code mapping
INSTRUMENT_TO_LEGACY_CODE: dict[str, str] = {
    "CBR_KEY_RATE": "rate_cb",
    "FED_FUNDS_RATE": "rate_cb_us",
    "US_CPI_YOY": "cpi",
    "US_UNEMPLOYMENT": "unemployment",
    "DXY": "dxy",
    "VIX": "vix",
    "BRENT_OIL": "oil_brent",
    "HY_OAS": "hy_oas",
    "GOV_10Y": "gov_10y",
    "BOC_OVERNIGHT_RATE": "rate_cb_ca",
    "CA_CPI_YOY": "cpi_ca",
    "CA_UNEMPLOYMENT": "unemployment_ca",
    "USDCAD": "usdcad",
    "CA_GOV_10Y": "gov_10y_ca",
    "WTI_CANADA": "oil_wti_ca",
    "WTI_OIL": "oil_wti",
    "NG_HENRY_HUB": "ng_gas",
    "SE_POLICY_RATE": "rate_cb_se",
    "ECB_DEPOSIT_RATE": "rate_cb_eu",
    "BOE_BANK_RATE": "rate_cb_gb",
    "BOJ_POLICY_RATE": "rate_cb_jp",
    "PBOC_POLICY_RATE": "rate_cb_cn",
    "GOLD": "gold",
    "SILVER": "silver",
    "PLATINUM": "platinum",
    "COPPER": "copper",
    **{spec.symbol: spec.legacy_code for spec in WORLD_BANK_INDICATORS},
    **{spec.symbol: spec.legacy_code for spec in EUROSTAT_INDICATORS},
}


def seed_timestamp() -> datetime:
    return datetime.now(timezone.utc)
