"""Read factor exposures for news impact alignment (Prompt 19 interface)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_SECTOR_FACTOR_PRIORS: dict[str, dict[str, float]] = {
    "financials": {
        "rates_sensitivity": 0.8,
        "market_beta": 0.7,
        "fx_sensitivity": 0.3,
    },
    "finance": {
        "rates_sensitivity": 0.8,
        "market_beta": 0.7,
    },
    "technology": {
        "growth": 0.9,
        "market_beta": 1.1,
        "rates_sensitivity": 0.4,
    },
    "energy": {
        "commodity_sensitivity": 0.9,
        "market_beta": 0.8,
    },
    "utilities": {
        "rates_sensitivity": 0.7,
        "value": 0.6,
    },
    "consumer": {
        "market_beta": 0.8,
        "growth": 0.5,
    },
}


class FactorExposureReader:
    """Load latest factor betas for an instrument."""

    async def load_exposures(
        self,
        db: AsyncSession,
        instrument_id: int,
        *,
        sector: str | None = None,
        instrument_metadata: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        db_exposures = await self._load_from_factor_exposure_table(db, instrument_id)
        if db_exposures:
            return db_exposures

        metadata = instrument_metadata or {}
        metadata_exposures = metadata.get("factor_exposure") or metadata.get("factor_exposures")
        if isinstance(metadata_exposures, dict):
            parsed = {
                str(key): float(value)
                for key, value in metadata_exposures.items()
                if value is not None
            }
            if parsed:
                return parsed

        return self._sector_fallback(sector)

    async def _load_from_factor_exposure_table(
        self,
        db: AsyncSession,
        instrument_id: int,
    ) -> dict[str, float]:
        query = text(
            """
            SELECT DISTINCT ON (factor_name)
                factor_name,
                beta
            FROM factor_exposure
            WHERE instrument_id = :instrument_id
            ORDER BY factor_name, time DESC
            """
        )
        try:
            result = await db.execute(query, {"instrument_id": instrument_id})
        except Exception:
            return {}

        exposures: dict[str, float] = {}
        for row in result.mappings().all():
            factor_name = row.get("factor_name")
            beta = row.get("beta")
            if factor_name is None or beta is None:
                continue
            exposures[str(factor_name)] = float(beta)
        return exposures

    @staticmethod
    def _sector_fallback(sector: str | None) -> dict[str, float]:
        if not sector:
            return {"market_beta": 0.6}
        key = sector.strip().lower()
        for sector_key, exposures in DEFAULT_SECTOR_FACTOR_PRIORS.items():
            if sector_key in key:
                return dict(exposures)
        return {"market_beta": 0.6, "sector_factor": 0.5}
