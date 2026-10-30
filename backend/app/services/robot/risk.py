"""Robot risk — plan kill-switch + portfolio day/month kill + exposure gates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, new_uuid
from app.db.robot_models import PortfolioRiskState, RobotPlan
from app.services.portfolio.expire_disposition import is_paper_maneuver
from app.services.portfolio.lot_ledger import book_snapshot
from app.services.portfolio.position_analytics import latest_prices
from app.services.robot.plan import complete_plans_for_maneuver
from app.services.robot.position_closer import close_maneuver_locked

logger = get_logger(__name__)


class PortfolioKillSwitchActive(Exception):
    """Portfolio-level kill blocks new adds."""


class ExposureLimitExceeded(Exception):
    """Symbol/venue/correlation exposure gate."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def drawdown_pct(*, peak: float, equity: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak * 100.0)


async def _plan_equity_usd(
    db: AsyncSession, plan: RobotPlan, mark: float | None
) -> float | None:
    snap = await book_snapshot(db, user_id=plan.user_id, ticker=plan.ticker, side=plan.side)
    if snap.qty <= 0 or snap.avg_entry is None:
        return None
    if mark is None or mark <= 0:
        return snap.cost_basis_usd
    if plan.side == "short":
        unreal = (snap.avg_entry - mark) * snap.qty
    else:
        unreal = (mark - snap.avg_entry) * snap.qty
    return snap.cost_basis_usd + unreal


async def get_or_create_risk_state(db: AsyncSession, user_id: str) -> PortfolioRiskState:
    res = await db.execute(
        select(PortfolioRiskState).where(PortfolioRiskState.user_id == user_id)
    )
    row = res.scalar_one_or_none()
    if row is not None:
        return row
    row = PortfolioRiskState(id=new_uuid(), user_id=user_id)
    db.add(row)
    await db.flush()
    return row


async def _user_portfolio_equity(db: AsyncSession, user_id: str) -> float:
    """Sum cost basis + unrealized across open paper maneuvers for user."""
    from app.services.portfolio.user_scope import maneuvers_for_user

    stmt = maneuvers_for_user(user_id).where(
        Maneuver.status.in_((ManeuverStatus.FILLED, ManeuverStatus.EXECUTING))
    )
    result = await db.execute(stmt)
    mans = [m for m in result.scalars().all() if is_paper_maneuver(m)]
    if not mans:
        return 0.0
    prices = await latest_prices(db, [m.ticker for m in mans])
    total = 0.0
    for m in mans:
        size = float(m.position_size_usd or 0.0)
        mark = prices.get(str(m.ticker or "").upper())
        entry = float(m.fill_price or m.entry_price or 0.0)
        if mark and entry > 0 and size > 0:
            qty = size / entry
            side = str(getattr(m.direction, "value", m.direction) or "long").lower()
            if side == "short":
                total += size + (entry - mark) * qty
            else:
                total += size + (mark - entry) * qty
        else:
            total += size
    return total


async def check_portfolio_kill_switch(
    db: AsyncSession, *, user_id: str, flatten: bool = True
) -> dict[str, Any]:
    """Day −5% / month −15% portfolio kill. Optionally flatten all paper positions."""
    state = await get_or_create_risk_state(db, user_id)
    now = _now()
    day_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    equity = await _user_portfolio_equity(db, user_id)

    if state.day_anchor_date != day_key:
        if state.equity_start_of_day is None or state.day_anchor_date is not None:
            state.equity_start_of_day = equity if equity > 0 else (state.equity_start_of_day or equity)
        state.day_anchor_date = day_key
    if state.month_anchor != month_key:
        if state.equity_start_of_month is None or state.month_anchor is not None:
            state.equity_start_of_month = equity if equity > 0 else (state.equity_start_of_month or equity)
        state.month_anchor = month_key

    day_base = float(state.equity_start_of_day or 0.0)
    month_base = float(state.equity_start_of_month or 0.0)
    day_pnl_pct = ((equity - day_base) / day_base * 100.0) if day_base > 0 else 0.0
    month_pnl_pct = ((equity - month_base) / month_base * 100.0) if month_base > 0 else 0.0

    reason = None
    if day_base > 0 and day_pnl_pct <= -float(state.day_limit_pct):
        reason = f"day_pnl={day_pnl_pct:.2f}% <= -{state.day_limit_pct}%"
    elif month_base > 0 and month_pnl_pct <= -float(state.month_limit_pct):
        reason = f"month_pnl={month_pnl_pct:.2f}% <= -{state.month_limit_pct}%"

    out: dict[str, Any] = {
        "triggered": False,
        "reason": None,
        "equity": equity,
        "day_pnl_pct": round(day_pnl_pct, 4),
        "month_pnl_pct": round(month_pnl_pct, 4),
        "closed": 0,
    }
    peak = max(equity, day_base, month_base)
    dd_frac = ((peak - equity) / peak) if peak > 0 else 0.0
    try:
        from app.services.ops_desk.live_hooks import halt_reason, live_sensors, write_pnl_snapshot

        write_pnl_snapshot(day_pnl_frac=day_pnl_pct / 100.0, dd_frac=dd_frac, equity=equity)
        ops_halt = halt_reason(
            {
                **live_sensors(),
                "day_pnl_frac": day_pnl_pct / 100.0,
                "dd_frac": dd_frac,
            }
        )
        if ops_halt and reason is None:
            reason = f"ops:{ops_halt}"
    except Exception as exc:
        logger.warning("ops halt check failed; trip kill", error=str(exc)[:200])
        if reason is None:
            reason = "ops:unavailable"
    if reason is None and not state.kill_switch_triggered:
        state.updated_at = now
        return out

    if reason:
        state.kill_switch_triggered = True
        state.kill_switch_reason = reason
        state.updated_at = now
        out["triggered"] = True
        out["reason"] = reason
        logger.warning("portfolio_kill_switch", user_id=user_id, reason=reason, equity=equity)

    if flatten and state.kill_switch_triggered:
        from app.services.portfolio.user_scope import maneuvers_for_user

        stmt = maneuvers_for_user(user_id).where(
            Maneuver.status.in_((ManeuverStatus.FILLED, ManeuverStatus.EXECUTING))
        )
        result = await db.execute(stmt)
        mans = [m for m in result.scalars().all() if is_paper_maneuver(m)]
        prices = await latest_prices(db, [m.ticker for m in mans])
        for m in mans:
            mark = prices.get(str(m.ticker or "").upper()) or float(
                m.fill_price or m.entry_price or 0.0
            )
            if mark <= 0:
                continue
            res = await close_maneuver_locked(
                db,
                maneuver_id=m.id,
                user_id=user_id,
                exit_price=float(mark),
                reason="portfolio_kill_switch",
            )
            if res.closed:
                out["closed"] += 1
    return out


async def check_exposure_limits(
    db: AsyncSession,
    *,
    user_id: str,
    symbol: str,
    venue: str = "paper",
    add_notional: float = 0.0,
    correlation: float | None = None,
) -> None:
    """Raise ExposureLimitExceeded / PortfolioKillSwitchActive when gates fail."""
    state = await get_or_create_risk_state(db, user_id)
    if state.kill_switch_triggered:
        raise PortfolioKillSwitchActive(state.kill_switch_reason or "active")

    equity = await _user_portfolio_equity(db, user_id)
    if equity <= 0:
        equity = max(add_notional, 1.0)

    snap = await book_snapshot(db, user_id=user_id, ticker=symbol)
    symbol_exp = float(snap.cost_basis_usd or 0.0) + abs(add_notional)
    symbol_pct = symbol_exp / equity * 100.0
    if symbol_pct > float(state.max_exposure_symbol_pct):
        raise ExposureLimitExceeded(
            f"symbol {symbol} exposure {symbol_pct:.1f}% > {state.max_exposure_symbol_pct}%"
        )

    # Venue concentration: approximate via signal_meta venue tags on open mans
    from app.services.portfolio.user_scope import maneuvers_for_user

    stmt = maneuvers_for_user(user_id).where(
        Maneuver.status.in_((ManeuverStatus.FILLED, ManeuverStatus.EXECUTING))
    )
    result = await db.execute(stmt)
    venue_usd = abs(add_notional)
    for m in result.scalars().all():
        meta = m.signal_meta if isinstance(m.signal_meta, dict) else {}
        v = str(meta.get("venue") or "paper")
        if v == venue:
            venue_usd += float(m.position_size_usd or 0.0)
    venue_pct = venue_usd / equity * 100.0
    if venue_pct > float(state.max_exposure_venue_pct):
        raise ExposureLimitExceeded(
            f"venue {venue} exposure {venue_pct:.1f}% > {state.max_exposure_venue_pct}%"
        )

    if correlation is not None and correlation > float(state.max_correlation):
        raise ExposureLimitExceeded(
            f"correlation {correlation:.2f} > {state.max_correlation}"
        )


async def enforce_kill_switches(db: AsyncSession) -> dict[str, int]:
    """Scan active paper plans; flatten when DD from peak ≥ kill_switch_pct."""
    # Portfolio kill first (all users with active plans)
    users = await db.execute(select(RobotPlan.user_id).where(RobotPlan.status == "active").distinct())
    for uid in users.scalars().all():
        try:
            await check_portfolio_kill_switch(db, user_id=uid, flatten=True)
        except Exception as exc:
            logger.warning("portfolio_kill_scan_failed", user_id=uid, error=str(exc)[:160])

    result = await db.execute(
        select(RobotPlan).where(
            RobotPlan.status == "active",
            RobotPlan.mode == "paper",
            RobotPlan.kill_switch_pct.is_not(None),
        )
    )
    plans = list(result.scalars().all())
    if not plans:
        return {"checked": 0, "tripped": 0, "updated_peaks": 0}

    prices = await latest_prices(db, [p.ticker for p in plans])
    tripped = 0
    updated = 0
    owners: set[str] = set()

    for plan in plans:
        limit = float(plan.kill_switch_pct or 0.0)
        if limit <= 0:
            continue
        mark = prices.get(plan.ticker.upper())
        equity = await _plan_equity_usd(db, plan, mark)
        if equity is None:
            continue

        peak = float(plan.peak_equity_usd) if plan.peak_equity_usd is not None else equity
        if equity > peak:
            plan.peak_equity_usd = equity
            plan.updated_at = _now()
            peak = equity
            updated += 1

        dd = drawdown_pct(peak=peak, equity=equity)
        if dd < limit:
            continue

        maneuver = None
        if plan.maneuver_id:
            mres = await db.execute(select(Maneuver).where(Maneuver.id == plan.maneuver_id))
            maneuver = mres.scalar_one_or_none()
        if maneuver is None or not is_paper_maneuver(maneuver):
            plan.status = "cancelled"
            plan.closed_at = _now()
            plan.notes = (plan.notes or "") + f" | kill_switch dd={dd:.2f}%"
            tripped += 1
            continue
        if maneuver.status not in (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING):
            await complete_plans_for_maneuver(db, maneuver_id=maneuver.id, reason="kill_switch")
            tripped += 1
            continue

        exit_px = float(mark) if mark and mark > 0 else float(
            (await book_snapshot(db, user_id=plan.user_id, ticker=plan.ticker)).avg_entry or 0
        )
        if exit_px <= 0:
            continue
        close_res = await close_maneuver_locked(
            db,
            maneuver_id=maneuver.id,
            user_id=plan.user_id,
            exit_price=exit_px,
            reason="kill_switch",
            plan_id=plan.id,
            cancel_open_levels=True,
        )
        if close_res.closed or close_res.already_closed:
            levels = list(plan.levels or [])
            for lv in levels:
                if str(lv.get("status")) in {"watching", "pending", "armed"}:
                    lv["status"] = "cancelled"
                    lv["cancelled_at"] = _now().isoformat()
                    lv["cancel_reason"] = "kill_switch"
            plan.levels = levels
            tripped += 1
            owners.add(plan.user_id)
            logger.warning(
                "robot_kill_switch",
                plan_id=plan.id,
                ticker=plan.ticker,
                dd_pct=round(dd, 3),
                limit_pct=limit,
                peak=peak,
                equity=equity,
            )

    if tripped or updated:
        await db.commit()
        if owners:
            try:
                from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users

                await enqueue_position_audits_for_users(db, owners)
            except Exception as exc:
                logger.warning("position audit enqueue failed after kill", error=str(exc)[:200])
    return {"checked": len(plans), "tripped": tripped, "updated_peaks": updated}
