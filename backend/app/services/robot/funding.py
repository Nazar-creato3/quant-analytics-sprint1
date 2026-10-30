"""Funding sync — persist venue funding events; LotLedger prefers events over constant."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import new_uuid
from app.db.robot_models import FundingEvent, PositionLot

logger = get_logger(__name__)


async def funding_sum_for_user_ticker(
    db: AsyncSession, *, user_id: str, ticker: str
) -> float:
    res = await db.execute(
        select(func.coalesce(func.sum(FundingEvent.amount), 0.0)).where(
            FundingEvent.user_id == user_id,
            FundingEvent.ticker == ticker.strip().upper(),
        )
    )
    return float(res.scalar() or 0.0)


async def funding_sum_for_lot(db: AsyncSession, *, lot_id: str) -> float:
    res = await db.execute(
        select(func.coalesce(func.sum(FundingEvent.amount), 0.0)).where(
            FundingEvent.lot_id == lot_id
        )
    )
    return float(res.scalar() or 0.0)


async def record_funding_event(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    amount: float,
    rate: float = 0.0,
    venue: str = "paper",
    lot_id: str | None = None,
    plan_id: str | None = None,
    occurred_at: datetime | None = None,
    meta: dict[str, Any] | None = None,
) -> FundingEvent:
    ev = FundingEvent(
        id=new_uuid(),
        user_id=user_id,
        ticker=ticker.strip().upper(),
        amount=float(amount),
        rate=float(rate),
        venue=venue,
        lot_id=lot_id,
        plan_id=plan_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        meta=meta or {},
    )
    db.add(ev)
    await db.flush()
    return ev


async def sync_funding_from_open_lots(
    db: AsyncSession, *, user_id: str | None = None
) -> dict[str, Any]:
    """Accrue estimated funding for open lots into funding_events (paper / fallback).

    Live path: replace body with venue transaction-log pull; keep same table.
    """
    stmt = select(PositionLot).where(
        PositionLot.status == "open", PositionLot.qty_open > 0
    )
    if user_id:
        stmt = stmt.where(PositionLot.user_id == user_id)
    result = await db.execute(stmt)
    lots = list(result.scalars().all())
    rate_day = max(float(getattr(settings, "FUNDING_RATE_PCT_PER_DAY", 0.0) or 0.0), 0.0) / 100.0
    # 8h funding ≈ daily/3
    rate_period = rate_day / 3.0
    created = 0
    now = datetime.now(timezone.utc)
    for lot in lots:
        notional = float(lot.entry_price) * float(lot.qty_open)
        if notional <= 0 or rate_period <= 0:
            continue
        amount = round(notional * rate_period, 6)
        await record_funding_event(
            db,
            user_id=lot.user_id,
            ticker=lot.ticker,
            amount=amount,
            rate=rate_period,
            venue="paper",
            lot_id=lot.id,
            plan_id=lot.robot_plan_id,
            occurred_at=now,
            meta={"source": "paper_funding_model"},  # modelled accrual on the paper book
        )
        # Stamp lot meta for BE without re-scanning all events each time
        meta = dict(lot.meta or {})
        meta["funding_usd"] = float(meta.get("funding_usd") or 0.0) + amount
        lot.meta = meta
        created += 1
    if created:
        await db.commit()
    logger.info("funding_synced", events=created)
    return {"events": created}
