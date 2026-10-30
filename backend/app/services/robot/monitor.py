"""Level monitor — paper Level Robot: execute add / SL / TP from RobotPlan.

Risk-first: SL before TP before add. Idempotent level fills via status + lot meta.
Ethical: paper mode only; no spoofing / wash helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus
from app.db.robot_models import PositionLot, RobotPlan
from app.services.portfolio.barrier_close import latest_bar_ranges
from app.services.portfolio.expire_disposition import is_paper_maneuver
from app.services.portfolio.lot_ledger import open_lot
from app.services.portfolio.position_analytics import (
    finite_float,
    latest_prices,
    position_quantity,
)
from app.services.robot.capabilities import FeatureNotAvailableInLiveMode, assert_action_allowed
from app.services.robot.idempotency import claim_level_fill
from app.services.robot.position_closer import close_maneuver_locked
from app.services.robot.reconcile import reconcile_maneuver_with_ledger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _level_hit(level: dict[str, Any], *, high: float, low: float, side_book: str) -> bool:
    kind = str(level.get("kind") or "")
    price = finite_float(level.get("price"))
    if price is None or price <= 0:
        return False
    status = str(level.get("status") or "")
    if status not in {"watching", "pending", "armed"}:
        return False
    if kind in {"add", "entry"}:
        if side_book == "short":
            return high >= price
        return low <= price
    if kind == "tp":
        if side_book == "short":
            return low <= price
        return high >= price
    if kind == "sl":
        if side_book == "short":
            return high >= price
        return low <= price
    return False


def _exit_px(level: dict[str, Any], mark: float) -> float:
    px = finite_float(level.get("price"))
    if px is None or px <= 0:
        return float(mark)
    # Gap: fill at level (conservative) when mark pierces beyond
    kind = str(level.get("kind") or "")
    if kind == "sl":
        return float(px)
    if kind == "tp":
        return float(px)
    return float(mark)


def _kind_priority(kind: str) -> int:
    # Lower = sooner. Risk-first.
    return {"sl": 0, "tp": 1, "add": 2, "entry": 3, "trail": 9}.get(kind, 5)


async def _already_filled_level(
    db: AsyncSession, *, plan_id: str, level_id: str | None
) -> bool:
    if not level_id:
        return False
    lots = await db.execute(
        select(PositionLot).where(
            PositionLot.robot_plan_id == plan_id,
            PositionLot.source == "robot_add",
        )
    )
    for lot in lots.scalars().all():
        meta = lot.meta or {}
        if str(meta.get("level_id")) == str(level_id):
            return True
    return False


async def _base_qty_for_add(
    db: AsyncSession, *, plan: RobotPlan, maneuver: Maneuver | None
) -> float | None:
    """Add size_pct is of the *initial* entry qty, not the grown book."""
    result = await db.execute(
        select(PositionLot)
        .where(
            PositionLot.robot_plan_id == plan.id,
            PositionLot.source == "maneuver",
        )
        .order_by(PositionLot.opened_at.asc())
        .limit(1)
    )
    entry_lot = result.scalar_one_or_none()
    if entry_lot is not None and float(entry_lot.qty_initial) > 0:
        return float(entry_lot.qty_initial)
    if plan.maneuver_id:
        result2 = await db.execute(
            select(PositionLot)
            .where(
                PositionLot.maneuver_id == plan.maneuver_id,
                PositionLot.source == "maneuver",
            )
            .order_by(PositionLot.opened_at.asc())
            .limit(1)
        )
        lot = result2.scalar_one_or_none()
        if lot is not None and float(lot.qty_initial) > 0:
            return float(lot.qty_initial)
    if maneuver is not None:
        meta = maneuver.signal_meta if isinstance(maneuver.signal_meta, dict) else {}
        fills = meta.get("robot_fills") or []
        added_usd = sum(float(f.get("usd") or 0) for f in fills if isinstance(f, dict))
        # Reconstruct original notional if we already bumped size
        raw_size = float(maneuver.position_size_usd or 0.0) - added_usd
        if raw_size > 0:
            entry = finite_float(maneuver.fill_price) or finite_float(maneuver.entry_price)
            if entry and entry > 0:
                return raw_size / entry
        return position_quantity(maneuver)
    return None


def parse_exit_size_pct(level: dict[str, Any]) -> float | None:
    """GA16-319: require explicit size_pct — never invent 100% from empty."""
    raw_size = level.get("size_pct")
    if raw_size is None or raw_size == "":
        return None
    try:
        size_pct = float(raw_size)
    except (TypeError, ValueError):
        return None
    if size_pct <= 0:
        return None
    return size_pct


async def _paper_close_maneuver(
    db: AsyncSession,
    *,
    plan: RobotPlan,
    maneuver: Maneuver,
    level: dict[str, Any],
    mark: float,
    levels: list[dict[str, Any]] | None = None,
    celery_task_id: str = "",
) -> str:
    """Full or partial exit via PositionCloser / FIFO reduce (single authority)."""
    from app.services.portfolio.lot_ledger import book_snapshot, reduce_lots_fifo
    from app.services.robot.fees import fee_for_fill
    from app.services.robot.session import append_session_event, ensure_session

    kind = str(level.get("kind") or "")
    action = "sl" if kind in {"sl", "trail"} else "tp"
    reason = "stop" if kind in {"sl", "trail"} else "take_profit"
    exit_px = _exit_px(level, mark)
    level_id = str(level.get("id") or action)
    size_pct = parse_exit_size_pct(level)
    if size_pct is None:
        logger.warning(
            "robot_exit_missing_size_pct",
            plan_id=plan.id,
            level_id=level_id,
            kind=kind,
        )
        return "skipped_missing_size_pct"
    snap = await book_snapshot(db, user_id=plan.user_id, ticker=plan.ticker, side=plan.side)
    book_qty = float(snap.qty or 0.0)
    partial = kind == "tp" and size_pct < 99.5 and book_qty > 0

    try:
        assert_action_allowed(
            mode=plan.mode,
            action="partial" if partial else ("trail" if kind == "trail" else action),
        )
    except FeatureNotAvailableInLiveMode:
        logger.warning("robot_live_block", plan_id=plan.id, action=action)
        return "blocked_live"

    claim = await claim_level_fill(
        db,
        plan_id=plan.id,
        level_id=level_id,
        action="tp_partial" if partial else action,
        celery_task_id=celery_task_id,
        qty=0.0,
        price=exit_px,
        maneuver_id=maneuver.id,
    )
    if not claim.claimed:
        level["status"] = "filled"
        return "duplicate"

    await ensure_session(db, plan=plan, entry_reason="monitor")

    if partial:
        close_qty = book_qty * (size_pct / 100.0)
        if close_qty <= 0:
            level["status"] = "filled"
            return reason
        fee = await fee_for_fill(
            db, venue="paper", symbol=plan.ticker, notional=close_qty * exit_px, liquidity="taker"
        )
        out = await reduce_lots_fifo(
            db,
            user_id=plan.user_id,
            ticker=plan.ticker,
            side=plan.side,
            qty=close_qty,
            exit_price=exit_px,
            reason=reason,
            maneuver_id=maneuver.id,
            fee_usd=fee,
        )
        realized_part = float(out.get("realized_pnl") or 0.0)
        if claim.fill is not None:
            claim.fill.qty = close_qty
            claim.fill.fee_usd = fee
        meta = dict(maneuver.signal_meta or {}) if isinstance(maneuver.signal_meta, dict) else {}
        fills = list(meta.get("robot_fills") or [])
        fills.append(
            {
                "kind": "tp_partial",
                "level_id": level.get("id"),
                "price": exit_px,
                "qty": close_qty,
                "usd": round(close_qty * exit_px, 2),
                "realized_pnl": realized_part,
                "at": _now_iso(),
                "plan_id": plan.id,
                "idempotency_key": claim.idempotency_key,
            }
        )
        meta["robot_fills"] = fills[-40:]
        maneuver.signal_meta = meta
        level["status"] = "filled"
        level["fill_price"] = exit_px
        level["filled_at"] = _now_iso()
        level["fill_qty"] = close_qty
        level["exit_reason"] = "take_profit_partial"
        be = snap.breakeven or snap.avg_entry or exit_px
        if levels:
            for lv in levels:
                k = str(lv.get("kind") or "")
                if k == "sl" and str(lv.get("status")) == "watching" and be:
                    lv["price"] = float(be)
                    lv["ratcheted"] = "breakeven"
                if k == "trail" and str(lv.get("status")) in {"pending", "watching"}:
                    lv["status"] = "armed"
                    lv["armed_at"] = _now_iso()
                    lv["peak_price"] = float(mark)
                    trail_pct = float(lv.get("trail_pct") or 1.5) / 100.0
                    if plan.side == "short":
                        lv["price"] = float(mark) * (1.0 + trail_pct)
                    else:
                        lv["price"] = float(mark) * (1.0 - trail_pct)
        await reconcile_maneuver_with_ledger(
            db, maneuver_id=maneuver.id, user_id=plan.user_id, mark_price=exit_px
        )
        snap2 = await book_snapshot(db, user_id=plan.user_id, ticker=plan.ticker, side=plan.side)
        if snap2.qty <= 1e-8:
            await close_maneuver_locked(
                db,
                maneuver_id=maneuver.id,
                user_id=plan.user_id,
                exit_price=exit_px,
                reason=reason,
                level_id=level_id,
                plan_id=plan.id,
            )
        await append_session_event(
            db, plan=plan, action="tp_partial", detail={"qty": close_qty, "price": exit_px}
        )
        logger.info(
            "robot_level_partial_tp",
            plan_id=plan.id,
            maneuver_id=maneuver.id,
            qty=close_qty,
            exit_price=exit_px,
            realized=realized_part,
        )
        return "take_profit_partial"

    close_res = await close_maneuver_locked(
        db,
        maneuver_id=maneuver.id,
        user_id=plan.user_id,
        exit_price=exit_px,
        reason=reason,
        level_id=level_id,
        plan_id=plan.id,
        cancel_open_levels=True,
    )
    level["status"] = "filled"
    level["fill_price"] = exit_px
    level["filled_at"] = _now_iso()
    level["exit_reason"] = reason
    if claim.fill is not None:
        claim.fill.qty = float(snap.qty or 0.0)
        claim.fill.price = exit_px
    await append_session_event(
        db,
        plan=plan,
        action=action,
        detail={"exit_price": exit_px, "closed": close_res.closed},
        close_session=True,
    )
    logger.info(
        "robot_level_close",
        plan_id=plan.id,
        maneuver_id=maneuver.id,
        kind=kind,
        exit_price=exit_px,
        reason=reason,
        closed=close_res.closed,
    )
    return reason if close_res.closed or close_res.already_closed else "noop"


def _update_trail_level(
    level: dict[str, Any], *, high: float, low: float, close: float, side_book: str
) -> bool:
    """Arm / ratchet trail. Hit uses *previous* stop so same-bar highs don't false-trigger."""
    status = str(level.get("status") or "")
    trail_pct = float(level.get("trail_pct") or 1.5) / 100.0
    activate = finite_float(level.get("activate_at"))
    prev_stop = finite_float(level.get("price"))

    if status == "pending":
        armed = False
        if activate is not None:
            if side_book == "short":
                armed = low <= activate
            else:
                armed = high >= activate
        if not armed:
            return False
        level["status"] = "armed"
        level["armed_at"] = _now_iso()
        status = "armed"
        prev_stop = None  # never fill on the arming bar

    if status != "armed":
        return False

    # Hit check against stop carried from prior tick
    hit = False
    if prev_stop is not None and prev_stop > 0:
        if side_book == "short":
            hit = high >= prev_stop
        else:
            hit = low <= prev_stop

    peak = finite_float(level.get("peak_price"))
    if side_book == "short":
        new_peak = low if peak is None else min(peak, low)
        level["peak_price"] = new_peak
        level["price"] = round(new_peak * (1.0 + trail_pct), 6)
    else:
        new_peak = high if peak is None else max(peak, high)
        level["peak_price"] = new_peak
        level["price"] = round(new_peak * (1.0 - trail_pct), 6)

    return hit


async def _paper_add(
    db: AsyncSession,
    *,
    plan: RobotPlan,
    maneuver: Maneuver | None,
    level: dict[str, Any],
    close: float,
    celery_task_id: str = "",
) -> bool:
    from app.services.robot.fees import fee_for_fill
    from app.services.robot.risk import (
        ExposureLimitExceeded,
        PortfolioKillSwitchActive,
        check_exposure_limits,
    )
    from app.services.robot.session import append_session_event, ensure_session

    try:
        assert_action_allowed(mode=plan.mode, action="add")
    except FeatureNotAvailableInLiveMode:
        logger.warning("robot_live_block_add", plan_id=plan.id)
        return False

    level_id = str(level.get("id") or "")
    if await _already_filled_level(db, plan_id=plan.id, level_id=level_id or None):
        level["status"] = "filled"
        return False

    base_qty = await _base_qty_for_add(db, plan=plan, maneuver=maneuver)
    size_pct = float(level.get("size_pct") or 50.0) / 100.0
    add_price = float(level.get("price") or close)
    if not base_qty or base_qty <= 0 or add_price <= 0:
        return False

    add_qty = base_qty * size_pct
    notional = add_qty * add_price
    try:
        await check_exposure_limits(
            db, user_id=plan.user_id, symbol=plan.ticker, add_notional=notional
        )
    except (ExposureLimitExceeded, PortfolioKillSwitchActive) as exc:
        logger.warning("robot_add_blocked", plan_id=plan.id, error=str(exc)[:160])
        level["status"] = "blocked"
        level["block_reason"] = str(exc)[:120]
        return False

    claim = await claim_level_fill(
        db,
        plan_id=plan.id,
        level_id=level_id,
        action="add",
        celery_task_id=celery_task_id,
        qty=add_qty,
        price=add_price,
        maneuver_id=plan.maneuver_id,
    )
    if not claim.claimed:
        level["status"] = "filled"
        return False

    fee = await fee_for_fill(
        db, venue="paper", symbol=plan.ticker, notional=notional, liquidity="taker"
    )
    if claim.fill is not None:
        claim.fill.fee_usd = fee

    await open_lot(
        db,
        user_id=plan.user_id,
        ticker=plan.ticker,
        side=plan.side,
        qty=add_qty,
        price=add_price,
        source="robot_add",
        maneuver_id=plan.maneuver_id,
        robot_plan_id=plan.id,
        fee_usd=fee,
        meta={"level_id": level_id, "kind": "add", "idempotency_key": claim.idempotency_key},
    )
    await ensure_session(db, plan=plan, entry_reason="add")
    if maneuver is not None:
        await reconcile_maneuver_with_ledger(
            db, maneuver_id=maneuver.id, user_id=plan.user_id, mark_price=add_price
        )
        meta = dict(maneuver.signal_meta or {}) if isinstance(maneuver.signal_meta, dict) else {}
        fills = list(meta.get("robot_fills") or [])
        fills.append(
            {
                "kind": "add",
                "level_id": level_id,
                "price": add_price,
                "qty": add_qty,
                "usd": round(notional, 2),
                "at": _now_iso(),
                "plan_id": plan.id,
                "idempotency_key": claim.idempotency_key,
            }
        )
        meta["robot_fills"] = fills[-40:]
        maneuver.signal_meta = meta

    level["status"] = "filled"
    level["fill_price"] = add_price
    level["filled_at"] = _now_iso()
    level["fill_qty"] = add_qty
    await append_session_event(
        db, plan=plan, action="add", detail={"qty": add_qty, "price": add_price}
    )
    logger.info(
        "robot_level_add",
        plan_id=plan.id,
        level_id=level_id,
        qty=add_qty,
        price=add_price,
    )
    return True


def _cancel_open_levels(levels: list[dict[str, Any]], *, except_id: str | None = None) -> None:
    for lv in levels:
        if except_id and str(lv.get("id")) == except_id:
            continue
        st = str(lv.get("status") or "")
        if st in {"watching", "pending", "armed", "triggered"}:
            lv["status"] = "cancelled"
            lv["cancelled_at"] = _now_iso()


async def tick_robot_plans(db: AsyncSession, *, celery_task_id: str = "") -> dict[str, int]:
    from app.services.robot.risk import enforce_kill_switches

    kill = await enforce_kill_switches(db)

    result = await db.execute(
        select(RobotPlan).where(RobotPlan.status == "active", RobotPlan.mode == "paper")
    )
    plans = list(result.scalars().all())
    if not plans:
        return {"plans": 0, "adds": 0, "closes": 0, "marked": 0}

    tickers = [p.ticker for p in plans]
    prices = await latest_prices(db, tickers)
    ranges = await latest_bar_ranges(db, tickers)
    adds = 0
    closes = 0
    marked = 0
    owners: set[str] = set()
    task_id = celery_task_id or ""

    for plan in plans:
        key = plan.ticker.upper()
        mark = prices.get(key)
        hlc = ranges.get(key)
        if hlc:
            high, low, close = hlc
            if mark is not None:
                high = max(high, float(mark))
                low = min(low, float(mark))
                close = float(mark)
        elif mark is not None:
            high = low = close = float(mark)
        else:
            continue

        levels = list(plan.levels or [])
        changed = False
        closed_now = False

        maneuver = None
        if plan.maneuver_id:
            mres = await db.execute(
                select(Maneuver).where(Maneuver.id == plan.maneuver_id).with_for_update()
            )
            maneuver = mres.scalar_one_or_none()
            if maneuver is not None and not is_paper_maneuver(maneuver):
                continue
            if maneuver is not None and maneuver.status not in (
                ManeuverStatus.FILLED,
                ManeuverStatus.EXECUTING,
            ):
                if plan.status == "active":
                    plan.status = "completed"
                    plan.closed_at = datetime.now(timezone.utc)
                    plan.updated_at = datetime.now(timezone.utc)
                    changed = True
                if changed:
                    plan.levels = levels
                continue

        for lv in levels:
            if str(lv.get("kind")) != "trail":
                continue
            hit = _update_trail_level(
                lv, high=high, low=low, close=close, side_book=plan.side
            )
            changed = True
            if hit and maneuver is not None and str(lv.get("status")) == "armed":
                await _paper_close_maneuver(
                    db,
                    plan=plan,
                    maneuver=maneuver,
                    level=lv,
                    mark=close,
                    levels=levels,
                    celery_task_id=task_id,
                )
                _cancel_open_levels(levels, except_id=str(lv.get("id")))
                closes += 1
                marked += 1
                closed_now = True
                owners.add(plan.user_id)

        if not closed_now:
            ordered = sorted(
                enumerate(levels),
                key=lambda pair: (_kind_priority(str(pair[1].get("kind") or "")), pair[0]),
            )
            for idx, lv in ordered:
                if closed_now:
                    break
                kind = str(lv.get("kind") or "")
                if kind == "trail":
                    continue
                if not _level_hit(lv, high=high, low=low, side_book=plan.side):
                    continue
                if kind == "sl" and maneuver is not None:
                    await _paper_close_maneuver(
                        db,
                        plan=plan,
                        maneuver=maneuver,
                        level=lv,
                        mark=close,
                        levels=levels,
                        celery_task_id=task_id,
                    )
                    levels[idx] = lv
                    _cancel_open_levels(levels, except_id=str(lv.get("id")))
                    closes += 1
                    marked += 1
                    changed = True
                    closed_now = True
                    owners.add(plan.user_id)
                elif kind == "tp" and maneuver is not None:
                    result_reason = await _paper_close_maneuver(
                        db,
                        plan=plan,
                        maneuver=maneuver,
                        level=lv,
                        mark=close,
                        levels=levels,
                        celery_task_id=task_id,
                    )
                    levels[idx] = lv
                    marked += 1
                    changed = True
                    owners.add(plan.user_id)
                    if result_reason == "take_profit_partial":
                        pass
                    else:
                        _cancel_open_levels(levels, except_id=str(lv.get("id")))
                        closes += 1
                        closed_now = True
                elif kind == "add" and str(lv.get("status")) == "watching":
                    ok = await _paper_add(
                        db,
                        plan=plan,
                        maneuver=maneuver,
                        level=lv,
                        close=close,
                        celery_task_id=task_id,
                    )
                    levels[idx] = lv
                    if ok:
                        adds += 1
                        marked += 1
                        changed = True
                        owners.add(plan.user_id)
                    elif str(lv.get("status")) in {"filled", "blocked"}:
                        changed = True

        if changed:
            plan.levels = levels
            plan.updated_at = datetime.now(timezone.utc)

    if adds or closes or marked:
        await db.commit()
        if owners:
            try:
                from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users

                await enqueue_position_audits_for_users(db, owners)
            except Exception:
                pass

    return {
        "plans": len(plans),
        "adds": adds,
        "closes": closes,
        "marked": marked,
        "kill_checked": kill.get("checked", 0),
        "kill_tripped": kill.get("tripped", 0),
    }
