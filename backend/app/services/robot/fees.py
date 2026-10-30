"""Maker/taker fee rates — venue_fees table with settings fallback."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import new_uuid
from app.db.robot_models import VenueFee

logger = get_logger(__name__)


def _default_rates() -> tuple[float, float]:
    # COMMISSION_RATE_PCT is percent; convert to fraction. Prefer taker = rate, maker = half.
    base = max(float(settings.COMMISSION_RATE_PCT or 0.0), 0.0) / 100.0
    if base <= 0:
        return 0.0002, 0.0005
    return base * 0.4, base


async def get_venue_fee(
    db: AsyncSession, *, venue: str = "paper", symbol: str = "*"
) -> tuple[float, float]:
    """Return (maker_rate, taker_rate) as fractions."""
    for sym in (symbol.upper(), "*"):
        res = await db.execute(
            select(VenueFee).where(VenueFee.venue == venue, VenueFee.symbol == sym)
        )
        row = res.scalar_one_or_none()
        if row is not None:
            return float(row.maker_rate), float(row.taker_rate)
    return _default_rates()


async def fee_for_fill(
    db: AsyncSession,
    *,
    venue: str,
    symbol: str,
    notional: float,
    liquidity: str = "taker",
) -> float:
    maker, taker = await get_venue_fee(db, venue=venue, symbol=symbol)
    rate = maker if liquidity == "maker" else taker
    return round(abs(float(notional)) * rate, 6)


async def upsert_venue_fee(
    db: AsyncSession,
    *,
    venue: str,
    symbol: str = "*",
    maker_rate: float,
    taker_rate: float,
    source: str = "sync",
) -> VenueFee:
    res = await db.execute(
        select(VenueFee).where(VenueFee.venue == venue, VenueFee.symbol == symbol)
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = VenueFee(
            id=new_uuid(),
            venue=venue,
            symbol=symbol,
            maker_rate=maker_rate,
            taker_rate=taker_rate,
            source=source,
        )
        db.add(row)
    else:
        row.maker_rate = maker_rate
        row.taker_rate = taker_rate
        row.source = source
        row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def sync_venue_fees(
    db: AsyncSession, *, venues: list[str] | None = None
) -> dict[str, Any]:
    """Refresh the paper fee tier from settings.

    Exchange venues are skipped on purpose: their real tier depends on each
    user's account and is applied from the user's own fills, never guessed.
    """
    targets = venues or ["paper", "bybit", "binance"]
    maker, taker = _default_rates()
    known = {"paper": (maker, taker)}
    updated = 0
    skipped: list[str] = []
    for v in targets:
        rates = known.get(v)
        if rates is None:
            skipped.append(v)
            continue
        m, t = rates
        await upsert_venue_fee(db, venue=v, maker_rate=m, taker_rate=t, source="fee_sync")
        updated += 1
    await db.commit()
    logger.info("venue_fees_synced", count=updated, skipped=len(skipped))
    return {"updated": updated, "venues": [v for v in targets if v not in skipped], "skipped": skipped}
