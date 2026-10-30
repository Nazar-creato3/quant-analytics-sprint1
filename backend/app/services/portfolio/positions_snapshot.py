"""Canonical open-positions snapshot for REST list + WS push."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, StrategyType
from app.schemas.schemas import ManeuverOut
from app.services.portfolio.position_analytics import enrich_maneuvers
from app.services.portfolio.user_scope import get_user_by_email, maneuvers_for_user
from app.utils.json_safe import finite_float

logger = get_logger(__name__)

OPEN_POSITION_STATUSES = frozenset(
    {
        ManeuverStatus.APPROVED,
        ManeuverStatus.FILLED,
        ManeuverStatus.EXECUTING,
        "approved",
        "filled",
        "executing",
    }
)

# Mark snapshot stale when any position lacks a live mark price.
STALE_MISSING_PRICE = True


def _live_snapshot_meta(
    *,
    now: datetime,
    refresh_started: datetime,
    stale: bool,
) -> dict[str, str | int | bool]:
    return {
        "server_now": now.isoformat(),
        "last_refresh_at": refresh_started.isoformat(),
        "data_freshness_seconds": max(0, int((now - refresh_started).total_seconds())),
        "stale": stale,
    }


async def _attach_enrichment(
    db: AsyncSession,
    maneuvers: list[Maneuver],
    items: list[ManeuverOut],
) -> bool:
    """Apply enrich_maneuvers fields onto ManeuverOut rows; return stale flag."""
    enrichment = await enrich_maneuvers(db, maneuvers)
    stale = False
    for item, maneuver in zip(items, maneuvers, strict=False):
        data = enrichment.get(item.id)
        if not data:
            stale = True
            continue
        item.current_price = finite_float(data.get("current_price"))
        item.approx_profit = finite_float(data.get("approx_profit"))
        item.unrealized_pnl = finite_float(data.get("unrealized_pnl"))
        item.time_to_close = data.get("time_to_close")
        if data.get("horizon_end_at"):
            item.horizon_end_at = str(data["horizon_end_at"])
            item.expiry_at = item.horizon_end_at
        if data.get("horizon_expired") is not None:
            item.horizon_expired = bool(data["horizon_expired"])
        tp_prob = finite_float(data.get("tp_hit_probability"))
        if tp_prob is not None:
            item.tp_hit_probability = tp_prob
        if data.get("profit_disclosure"):
            item.profit_disclosure = str(data["profit_disclosure"])
        pnl_low = finite_float(data.get("expected_pnl_low"))
        if pnl_low is not None:
            item.expected_pnl_low = pnl_low
        pnl_high = finite_float(data.get("expected_pnl_high"))
        if pnl_high is not None:
            item.expected_pnl_high = pnl_high
        ret_low = finite_float(data.get("expected_return_low"))
        if ret_low is not None:
            item.expected_return_low = ret_low
        ret_high = finite_float(data.get("expected_return_high"))
        if ret_high is not None:
            item.expected_return_high = ret_high
        if item.stop_loss is None:
            item.stop_loss = finite_float(data.get("display_stop_loss"))
        if item.take_profit is None:
            item.take_profit = finite_float(data.get("display_take_profit"))
        if STALE_MISSING_PRICE and item.current_price is None:
            stale = True
    return stale


async def build_open_positions_snapshot(
    email: str,
    db: AsyncSession,
    *,
    page_size: int = 50,
) -> dict:
    """Return enriched open positions + server-trusted freshness metadata."""
    refresh_started = datetime.now(timezone.utc)
    user = await get_user_by_email(db, email)
    if not user:
        now = datetime.now(timezone.utc)
        return {
            "items": [],
            "total": 0,
            "live_snapshot": _live_snapshot_meta(now=now, refresh_started=refresh_started, stale=True),
        }

    from app.services.portfolio.expiration_close import close_expired_for_user

    await close_expired_for_user(db, user.id)

    query = (
        maneuvers_for_user(user.id, staff_include_orphans=False)
        .where(Maneuver.status.in_(list(OPEN_POSITION_STATUSES)))
        .where(Maneuver.strategy_type != StrategyType.NO_TRADE)
        .order_by(Maneuver.created_at.desc())
        .limit(page_size)
    )
    result = await db.execute(query)
    maneuvers = list(result.scalars().all())
    items = [ManeuverOut.model_validate(m) for m in maneuvers]
    stale = await _attach_enrichment(db, maneuvers, items)
    now = datetime.now(timezone.utc)

    payload = {
        "items": [i.model_dump() for i in items],
        "total": len(items),
        "live_snapshot": _live_snapshot_meta(now=now, refresh_started=refresh_started, stale=stale),
    }
    logger.info(
        "live_positions_snapshot",
        email=email,
        count=len(items),
        stale=stale,
        as_of=now.isoformat(),
    )
    return payload
