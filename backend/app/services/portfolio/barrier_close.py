"""Auto-close filled paper positions when price hits stop-loss or take-profit.

Broker rules:
- Prefer STOP over TP on gaps that pierce both (risk-first).
- Use bar high/low when available so intra-bar pierces are not missed.
- Only paper book; live stays with broker brackets / Direct Deals.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, OHLCVBar, SignalDirection
from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users
from app.services.portfolio.expire_disposition import is_paper_maneuver
from app.services.portfolio.position_analytics import (
    finite_float,
    latest_prices,
    maneuver_stop_loss,
    maneuver_take_profit,
)

logger = get_logger(__name__)

_OPEN = (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING)


def _is_short(maneuver: Maneuver) -> bool:
    raw = maneuver.direction.value if hasattr(maneuver.direction, "value") else maneuver.direction
    return str(raw).lower() == SignalDirection.SHORT.value


def barrier_hit(maneuver: Maneuver, price: float) -> str | None:
    """Close-only check (legacy). Prefer ``barrier_hit_range``."""
    return barrier_hit_range(maneuver, high=price, low=price, close=price)


def barrier_hit_range(
    maneuver: Maneuver,
    *,
    high: float,
    low: float,
    close: float | None = None,
) -> str | None:
    """Return ``stop`` | ``take_profit`` using bar range (intra-bar pierce).

    On dual-hit gaps (high and low both breach), STOP wins.
    """
    mark = close if close is not None and close > 0 else high
    if high <= 0 or low <= 0:
        return None
    if low > high:
        low, high = high, low
    fill = finite_float(maneuver.fill_price) or finite_float(maneuver.entry_price)
    if fill is None or fill <= 0:
        return None
    sl = maneuver_stop_loss(maneuver)
    tp = maneuver_take_profit(maneuver)
    short = _is_short(maneuver)

    hit_stop = False
    hit_tp = False
    if short:
        hit_stop = sl is not None and high >= sl
        hit_tp = tp is not None and low <= tp
    else:
        hit_stop = sl is not None and low <= sl
        hit_tp = tp is not None and high >= tp

    if hit_stop and hit_tp:
        return "stop"
    if hit_stop:
        return "stop"
    if hit_tp:
        return "take_profit"
    if mark > 0:
        if short:
            if sl is not None and mark >= sl:
                return "stop"
            if tp is not None and mark <= tp:
                return "take_profit"
        else:
            if sl is not None and mark <= sl:
                return "stop"
            if tp is not None and mark >= tp:
                return "take_profit"
    return None


def _exit_price_for_reason(maneuver: Maneuver, reason: str, mark: float) -> float:
    sl = maneuver_stop_loss(maneuver)
    tp = maneuver_take_profit(maneuver)
    short = _is_short(maneuver)
    if reason == "stop" and sl is not None:
        if (short and mark > sl) or (not short and mark < sl):
            return float(sl)
        return float(mark)
    if reason == "take_profit" and tp is not None:
        if (short and mark < tp) or (not short and mark > tp):
            return float(tp)
        return float(mark)
    return float(mark)


async def latest_bar_ranges(db: AsyncSession, tickers: list[str]) -> dict[str, tuple[float, float, float]]:
    """ticker -> (high, low, close) from newest OHLCV row."""
    uniq = sorted({t.upper() for t in tickers if t})
    if not uniq:
        return {}
    sub = (
        select(OHLCVBar.ticker, func.max(OHLCVBar.timestamp).label("ts"))
        .where(OHLCVBar.ticker.in_(uniq))
        .group_by(OHLCVBar.ticker)
        .subquery()
    )
    stmt = select(OHLCVBar.ticker, OHLCVBar.high, OHLCVBar.low, OHLCVBar.close).join(
        sub, (OHLCVBar.ticker == sub.c.ticker) & (OHLCVBar.timestamp == sub.c.ts)
    )
    result = await db.execute(stmt)
    out: dict[str, tuple[float, float, float]] = {}
    for ticker, high, low, close in result.all():
        h = finite_float(high)
        lo = finite_float(low)
        c = finite_float(close)
        if h and lo and c and h > 0 and lo > 0 and c > 0:
            out[str(ticker).upper()] = (h, lo, c)
    return out


async def robot_plan_blocks_barrier(db: AsyncSession, maneuver_id: str) -> bool:
    """True when an active robot owns SL/TP. Check failure must not skip a hit stop."""
    try:
        from app.db.robot_models import RobotPlan

        owned = await db.execute(
            select(RobotPlan.id).where(
                RobotPlan.maneuver_id == maneuver_id,
                RobotPlan.status == "active",
            ).limit(1)
        )
        return owned.scalar_one_or_none() is not None
    except Exception as exc:
        logger.warning(
            "robot plan ownership check failed; close barrier anyway",
            maneuver_id=maneuver_id,
            error=str(exc)[:200],
        )
        return False


async def close_barrier_hits(db: AsyncSession, *, user_id: str | None = None) -> dict[str, int]:
    """Scan open filled book and close paper legs that hit SL/TP."""
    if user_id is not None:
        from app.services.portfolio.user_scope import maneuvers_for_user

        stmt = maneuvers_for_user(user_id).where(Maneuver.status.in_(_OPEN))
    else:
        stmt = select(Maneuver).where(Maneuver.status.in_(_OPEN))
    stmt = stmt.options(joinedload(Maneuver.report))
    result = await db.execute(stmt)
    loaded = [m for m in result.scalars().unique().all() if is_paper_maneuver(m)]
    if not loaded:
        return {"closed": 0, "checked": 0, "stops": 0, "take_profits": 0}

    tickers = [m.ticker for m in loaded]
    prices = await latest_prices(db, tickers)
    ranges = await latest_bar_ranges(db, tickers)
    closed = 0
    stops = 0
    tps = 0
    owners: set[str] = set()
    for m in loaded:
        key = str(m.ticker or "").upper()
        mark = prices.get(key)
        hlc = ranges.get(key)
        if hlc is not None:
            high, low, close = hlc
            if mark is not None:
                high = max(high, float(mark))
                low = min(low, float(mark))
                close = float(mark)
            reason = barrier_hit_range(m, high=high, low=low, close=close)
            mark_for_exit = float(mark) if mark is not None else close
        elif mark is not None:
            reason = barrier_hit(m, float(mark))
            mark_for_exit = float(mark)
        else:
            continue
        if not reason:
            continue

        exit_px = _exit_price_for_reason(m, reason, mark_for_exit)
        report = m.report
        owner = report.created_by if report is not None else None

        if await robot_plan_blocks_barrier(db, m.id):
            continue

        from app.services.robot.position_closer import close_maneuver_locked

        close_res = await close_maneuver_locked(
            db,
            maneuver_id=m.id,
            user_id=owner,
            exit_price=exit_px,
            reason=reason,
        )
        if not close_res.closed:
            continue
        closed += 1
        if reason == "stop":
            stops += 1
        else:
            tps += 1
        if owner:
            owners.add(owner)
        logger.info(
            "barrier_close",
            maneuver_id=m.id,
            ticker=m.ticker,
            reason=reason,
            mark=mark_for_exit,
            exit_price=exit_px,
            realized_pnl=close_res.realized_pnl,
            used_bar_range=hlc is not None,
        )

    if closed:
        await db.commit()
        if user_id:
            owners.add(user_id)
        if owners:
            await enqueue_position_audits_for_users(db, owners)
    return {"closed": closed, "checked": len(loaded), "stops": stops, "take_profits": tps}
