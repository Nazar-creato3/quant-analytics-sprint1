"""Best-effort SQL insert for forecast_log rows. Never UPDATE/DELETE."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.forecast_log.store import ForecastLogRow


async def insert_forecast_log(session: AsyncSession, row: ForecastLogRow) -> None:
    await session.execute(
        text(
            """
            INSERT INTO forecast_log (
              issued_at, instrument_id, ticker, horizon_days, direction,
              probability, interval_low, interval_high, section, model_id,
              model_version, feature_hash, issued_price, issued_price_source,
              prev_hash, row_hash
            ) VALUES (
              :issued_at, :instrument_id, :ticker, :horizon_days, :direction,
              :probability, :interval_low, :interval_high, :section, :model_id,
              :model_version, :feature_hash, :issued_price, :issued_price_source,
              :prev_hash, :row_hash
            )
            """
        ),
        {
            "issued_at": row.issued_at,
            "instrument_id": row.instrument_id,
            "ticker": row.ticker,
            "horizon_days": row.horizon_days,
            "direction": row.direction,
            "probability": row.probability,
            "interval_low": row.interval_low,
            "interval_high": row.interval_high,
            "section": row.section,
            "model_id": row.model_id,
            "model_version": row.model_version,
            "feature_hash": row.feature_hash,
            "issued_price": row.issued_price,
            "issued_price_source": row.issued_price_source,
            "prev_hash": row.prev_hash,
            "row_hash": row.row_hash,
        },
    )
    await session.commit()
