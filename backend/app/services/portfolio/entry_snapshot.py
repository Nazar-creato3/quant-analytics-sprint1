"""Snapshot entry metadata when a maneuver is filled."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver
from app.services.macro.sector_seed import sector_for_symbol
from app.services.portfolio.position_analytics import _entry_reference, maneuver_stop_loss
from app.utils.json_safe import finite_float

logger = get_logger(__name__)


def _signal_price(maneuver: Maneuver, fill_price: float | None) -> float | None:
    meta = getattr(maneuver, "signal_meta", None) or {}
    for key in ("signal_price", "generated_price", "reference_price", "entry_price"):
        val = finite_float(meta.get(key))
        if val is not None and val > 0:
            return val
    low = finite_float(maneuver.entry_zone_low)
    high = finite_float(maneuver.entry_zone_high)
    if low is not None and high is not None:
        return (low + high) / 2.0
    if fill_price is not None and fill_price > 0:
        return fill_price
    return _entry_reference(maneuver)


async def _load_factor_exposures(db: AsyncSession, ticker: str) -> dict[str, float]:
    from app.domain.instrument import InstrumentORM
    from app.services.event_risk.factor_exposure_reader import FactorExposureReader

    sector_tuple = sector_for_symbol(ticker)
    sector = sector_tuple[0] if sector_tuple else None
    result = await db.execute(
        select(InstrumentORM.id).where(InstrumentORM.symbol == ticker.upper()).limit(1)
    )
    instrument_id = result.scalar_one_or_none()
    reader = FactorExposureReader()
    if instrument_id is None:
        return reader._sector_fallback(sector)
    return await reader.load_exposures(db, instrument_id, sector=sector)


async def _load_regime_at_entry(db: AsyncSession, ticker: str) -> str | None:
    from app.domain.instrument import InstrumentORM
    from app.domain.regime import RegimeHistoryORM

    result = await db.execute(
        select(InstrumentORM.id).where(InstrumentORM.symbol == ticker.upper()).limit(1)
    )
    instrument_id = result.scalar_one_or_none()
    if instrument_id is None:
        return None
    regime_result = await db.execute(
        select(RegimeHistoryORM.dominant_regime)
        .where(
            RegimeHistoryORM.scope_type == "instrument",
            RegimeHistoryORM.scope_id == str(instrument_id),
        )
        .order_by(RegimeHistoryORM.time.desc())
        .limit(1)
    )
    return regime_result.scalar_one_or_none()


async def capture_entry_snapshot(
    db: AsyncSession,
    maneuver: Maneuver,
    *,
    fill_price: float | None = None,
) -> None:
    """Persist audit-relevant metadata at fill time."""
    px = finite_float(fill_price) or finite_float(maneuver.fill_price)
    if px is None or px <= 0:
        return

    maneuver.entry_price = px
    sl = maneuver_stop_loss(maneuver)
    if sl is not None:
        maneuver.stop_loss_price = sl
    maneuver.signal_generated_price = _signal_price(maneuver, px)

    sector_tuple = sector_for_symbol(maneuver.ticker)
    if sector_tuple:
        maneuver.sector_at_entry = sector_tuple[0]

    try:
        exposures = await _load_factor_exposures(db, maneuver.ticker)
        maneuver.factor_exposures_at_entry = exposures
    except Exception as exc:
        logger.warning("factor_snapshot_failed", ticker=maneuver.ticker, error=str(exc))
        maneuver.factor_exposures_at_entry = {}

    try:
        regime = await _load_regime_at_entry(db, maneuver.ticker)
        if regime:
            maneuver.regime_at_entry = regime
    except Exception as exc:
        logger.warning("regime_snapshot_failed", ticker=maneuver.ticker, error=str(exc))

    from app.services.portfolio.position_analytics import reanchor_relative_expiry_on_fill

    if reanchor_relative_expiry_on_fill(maneuver):
        logger.info(
            "maneuver_expiry_reanchored_on_fill",
            maneuver_id=maneuver.id,
            ticker=maneuver.ticker,
            time_horizon=maneuver.time_horizon,
            expiry_at=(maneuver.signal_meta or {}).get("expiry_at"),
        )


def update_peak_unrealized(maneuver: Maneuver, unrealized_pnl: float | None) -> bool:
    """Update running peak unrealized P&L while position is open."""
    if unrealized_pnl is None:
        return False
    current_peak = finite_float(maneuver.peak_unrealized_pnl)
    if current_peak is None or unrealized_pnl > current_peak:
        maneuver.peak_unrealized_pnl = round(unrealized_pnl, 2)
        return True
    return False


async def finalize_close_metadata(
    db: AsyncSession,
    maneuver: Maneuver,
    *,
    exit_reason: str,
    exit_price: float | None,
    realized_pnl: float | None,
) -> None:
    """Stamp close metadata required for position audit."""
    from datetime import datetime, timezone

    if maneuver.entry_price is None:
        maneuver.entry_price = _entry_reference(maneuver)
    if maneuver.stop_loss_price is None:
        sl = maneuver_stop_loss(maneuver)
        if sl is not None:
            maneuver.stop_loss_price = sl
    if maneuver.signal_generated_price is None:
        maneuver.signal_generated_price = _signal_price(maneuver, finite_float(maneuver.fill_price))
    if not maneuver.factor_exposures_at_entry:
        try:
            maneuver.factor_exposures_at_entry = await _load_factor_exposures(db, maneuver.ticker)
        except Exception as exc:
            logger.warning("factor exposures unavailable on close", ticker=maneuver.ticker, error=str(exc)[:200])
            maneuver.factor_exposures_at_entry = {}
    if maneuver.sector_at_entry is None:
        sector_tuple = sector_for_symbol(maneuver.ticker)
        if sector_tuple:
            maneuver.sector_at_entry = sector_tuple[0]
    if maneuver.regime_at_entry is None:
        try:
            maneuver.regime_at_entry = await _load_regime_at_entry(db, maneuver.ticker)
        except Exception as exc:
            logger.warning("regime at entry unavailable on close", ticker=maneuver.ticker, error=str(exc)[:200])

    maneuver.exit_reason = exit_reason
    maneuver.exit_price = finite_float(exit_price)
    maneuver.realized_pnl = round(realized_pnl or 0.0, 2) if realized_pnl is not None else 0.0
    maneuver.closed_at = datetime.now(timezone.utc)
    logger.info(
        "maneuver_close_pnl",
        maneuver_id=maneuver.id,
        ticker=maneuver.ticker,
        exit_reason=exit_reason,
        realized_pnl=maneuver.realized_pnl,
        exit_price=maneuver.exit_price,
    )
