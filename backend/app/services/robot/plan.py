"""Robot plan builder — levels from maneuver (entry / add / SL / TP / trailing stop).

Governance: plans are auditable JSON; no market-manipulation helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, SignalDirection
from app.db.robot_models import RobotPlan
from app.services.portfolio.position_analytics import (
    finite_float,
    maneuver_stop_loss,
    maneuver_take_profit,
)

logger = get_logger(__name__)


def _side(direction: Any) -> str:
    raw = direction.value if hasattr(direction, "value") else str(direction or "")
    return "short" if raw.lower() == SignalDirection.SHORT.value else "long"


def build_levels_from_maneuver(maneuver: Maneuver, *, entry_price: float | None = None) -> list[dict[str, Any]]:
    """Construct a conservative RobotPlan level set from a filled/approved maneuver."""
    side = _side(maneuver.direction)
    entry = (
        finite_float(entry_price)
        or finite_float(maneuver.fill_price)
        or finite_float(maneuver.entry_zone_high)
        or finite_float(maneuver.entry_zone_low)
    )
    # Optional Freqtrade-style params on signal_meta → ROI ladder
    meta = maneuver.signal_meta if isinstance(maneuver.signal_meta, dict) else {}
    ft = meta.get("freqtrade") if isinstance(meta.get("freqtrade"), dict) else None
    if ft and entry is not None:
        from app.services.robot.freqtrade_bridge import levels_from_freqtrade_params

        levels = levels_from_freqtrade_params(
            entry=entry,
            side=side,
            minimal_roi=ft.get("minimal_roi"),
            stoploss=float(ft.get("stoploss") if ft.get("stoploss") is not None else -0.08),
            trailing_stop=bool(ft.get("trailing_stop", True)),
            trailing_stop_positive=ft.get("trailing_stop_positive"),
            trailing_stop_positive_offset=ft.get("trailing_stop_positive_offset"),
            add_zone_pct=ft.get("add_zone_pct", 0.025),
        )
        # Preserve filled entry status from maneuver fill
        for lv in levels:
            if lv.get("kind") == "entry":
                lv["status"] = "filled" if finite_float(maneuver.fill_price) else "pending"
                lv["fill_price"] = finite_float(maneuver.fill_price)
                lv["filled_at"] = maneuver.filled_at.isoformat() if maneuver.filled_at else None
        return levels

    sl = maneuver_stop_loss(maneuver)
    tp = maneuver_take_profit(maneuver)
    zone_lo = finite_float(maneuver.entry_zone_low)
    zone_hi = finite_float(maneuver.entry_zone_high)

    levels: list[dict[str, Any]] = []
    if entry is not None:
        levels.append(
            {
                "id": "entry",
                "kind": "entry",
                "side": "sell" if side == "short" else "buy",
                "price": entry,
                "size_pct": 100.0,
                "status": "filled" if finite_float(maneuver.fill_price) else "pending",
                "fill_price": finite_float(maneuver.fill_price),
                "filled_at": maneuver.filled_at.isoformat() if maneuver.filled_at else None,
            }
        )
    # Optional add zone: midpoint between entry and favorable zone edge (DCA-lite).
    if entry is not None and zone_lo is not None and zone_hi is not None:
        if side == "long" and zone_lo < entry:
            add_px = round((entry + zone_lo) / 2.0, 6)
            levels.append(
                {
                    "id": "add_1",
                    "kind": "add",
                    "side": "buy",
                    "price": add_px,
                    "size_pct": 50.0,
                    "status": "watching",
                }
            )
        elif side == "short" and zone_hi > entry:
            add_px = round((entry + zone_hi) / 2.0, 6)
            levels.append(
                {
                    "id": "add_1",
                    "kind": "add",
                    "side": "sell",
                    "price": add_px,
                    "size_pct": 50.0,
                    "status": "watching",
                }
            )
    if tp is not None:
        # P2: scale-out 50/50 — first half at TP, runner managed by trail
        levels.append(
            {
                "id": "tp_1",
                "kind": "tp",
                "side": "buy" if side == "short" else "sell",
                "price": tp,
                "size_pct": 50.0,
                "status": "watching",
            }
        )
    if sl is not None:
        levels.append(
            {
                "id": "sl",
                "kind": "sl",
                "side": "buy" if side == "short" else "sell",
                "price": sl,
                "size_pct": 100.0,
                "status": "watching",
            }
        )
    # Trail: arms after TP1 (or when price reaches activate_at); protects runner
    if entry is not None and tp is not None:
        levels.append(
            {
                "id": "trail",
                "kind": "trail",
                "side": "buy" if side == "short" else "sell",
                "price": None,
                "trail_pct": 1.5,
                "activate_at": tp,
                "peak_price": None,
                "size_pct": 50.0,
                "status": "pending",
            }
        )
    return levels


async def create_plan_from_freqtrade(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    entry: float,
    side: str = "long",
    mode: str = "paper",
    minimal_roi: dict[str, float] | None = None,
    stoploss: float = -0.08,
    trailing_stop: bool = True,
    trailing_stop_positive: float | None = 0.015,
    trailing_stop_positive_offset: float | None = None,
    maneuver_id: str | None = None,
    notes: str | None = None,
) -> RobotPlan:
    from app.services.robot.capabilities import default_capabilities
    from app.services.robot.freqtrade_bridge import levels_from_freqtrade_params

    levels = levels_from_freqtrade_params(
        entry=entry,
        side=side,
        minimal_roi=minimal_roi,
        stoploss=stoploss,
        trailing_stop=trailing_stop,
        trailing_stop_positive=trailing_stop_positive,
        trailing_stop_positive_offset=trailing_stop_positive_offset,
    )
    plan = RobotPlan(
        user_id=user_id,
        ticker=ticker.strip().upper(),
        maneuver_id=maneuver_id,
        status="active",
        side="short" if str(side).lower() in {"short", "sell"} else "long",
        mode=mode,
        levels=levels,
        kill_switch_pct=5.0,
        notes=notes or "freqtrade pattern bridge",
        plan_type="freqtrade",
        capabilities=default_capabilities(mode),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(plan)
    await db.flush()
    logger.info("robot_plan_from_freqtrade", plan_id=plan.id, ticker=plan.ticker)
    return plan


def levels_from_grid_params(
    *,
    entry: float,
    side: str = "long",
    lower: float,
    upper: float,
    grid_count: int = 10,
    qty_pct: float = 10.0,
) -> list[dict[str, Any]]:
    """Build watching add levels between lower/upper (RobotPlan grid mode)."""
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    n = max(int(grid_count), 2)
    lo, hi = min(float(lower), float(upper)), max(float(lower), float(upper))
    step = (hi - lo) / (n - 1)
    levels: list[dict[str, Any]] = [
        {
            "id": "entry",
            "kind": "entry",
            "price": float(entry),
            "size_pct": 100.0,
            "status": "filled",
            "side": "sell" if side_n == "short" else "buy",
        }
    ]
    for i in range(n):
        px = round(lo + step * i, 6)
        if abs(px - float(entry)) < 1e-9:
            continue
        levels.append(
            {
                "id": f"grid_{i}",
                "kind": "add",
                "price": px,
                "size_pct": float(qty_pct),
                "status": "watching",
                "side": "sell" if side_n == "short" else "buy",
            }
        )
    return levels


def levels_from_dca_params(
    *,
    entry: float,
    side: str = "long",
    steps: int = 4,
    step_pct: float = 2.0,
    qty_multiplier: float = 1.0,
) -> list[dict[str, Any]]:
    """DCA ladder below (long) / above (short) entry."""
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    levels: list[dict[str, Any]] = [
        {
            "id": "entry",
            "kind": "entry",
            "price": float(entry),
            "size_pct": 100.0,
            "status": "filled",
        }
    ]
    for i in range(1, max(int(steps), 1) + 1):
        frac = (float(step_pct) / 100.0) * i
        px = float(entry) * (1.0 - frac) if side_n == "long" else float(entry) * (1.0 + frac)
        levels.append(
            {
                "id": f"dca_{i}",
                "kind": "add",
                "price": round(px, 6),
                "size_pct": round(50.0 * (float(qty_multiplier) ** (i - 1)), 2),
                "status": "watching",
            }
        )
    return levels


async def create_plan_typed(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    entry: float,
    side: str = "long",
    mode: str = "paper",
    plan_type: str = "custom",
    plan_params: dict[str, Any] | None = None,
    maneuver_id: str | None = None,
) -> RobotPlan:
    from app.services.robot.capabilities import default_capabilities

    params = plan_params or {}
    pt = (plan_type or "custom").lower()
    if pt == "grid":
        levels = levels_from_grid_params(
            entry=entry,
            side=side,
            lower=float(params.get("lower") or entry * 0.95),
            upper=float(params.get("upper") or entry * 1.05),
            grid_count=int(params.get("grid_count") or 10),
            qty_pct=float(params.get("qty_pct") or 10.0),
        )
    elif pt == "dca":
        levels = levels_from_dca_params(
            entry=entry,
            side=side,
            steps=int(params.get("steps") or 4),
            step_pct=float(params.get("step_pct") or 2.0),
            qty_multiplier=float(params.get("qty_multiplier") or 1.0),
        )
    else:
        levels = [
            {
                "id": "entry",
                "kind": "entry",
                "price": float(entry),
                "size_pct": 100.0,
                "status": "filled",
            }
        ]
    plan = RobotPlan(
        user_id=user_id,
        ticker=ticker.strip().upper(),
        maneuver_id=maneuver_id,
        status="active",
        side="short" if str(side).lower() in {"short", "sell"} else "long",
        mode=mode,
        levels=levels,
        plan_type=pt,
        plan_params=params,
        capabilities=default_capabilities(mode),
        kill_switch_pct=5.0,
        notes=f"plan_type={pt}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(plan)
    await db.flush()
    return plan


async def ensure_plan_for_maneuver(
    db: AsyncSession,
    *,
    user_id: str,
    maneuver: Maneuver,
    mode: str = "paper",
) -> RobotPlan:
    existing = await db.execute(
        select(RobotPlan).where(
            RobotPlan.maneuver_id == maneuver.id,
            RobotPlan.user_id == user_id,
        ).limit(1)
    )
    plan = existing.scalar_one_or_none()
    levels = build_levels_from_maneuver(maneuver)
    if plan is None:
        from app.services.robot.capabilities import default_capabilities

        plan = RobotPlan(
            user_id=user_id,
            ticker=str(maneuver.ticker).upper(),
            maneuver_id=maneuver.id,
            status="active",
            side=_side(maneuver.direction),
            mode=mode,
            levels=levels,
            kill_switch_pct=5.0,
            notes="auto from maneuver approve/fill",
            plan_type="custom",
            capabilities=default_capabilities(mode),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        await db.flush()
        logger.info("robot_plan_created", plan_id=plan.id, maneuver_id=maneuver.id)
        return plan
    # Refresh levels that are still watching; keep filled history
    filled = {str(lv.get("id")): lv for lv in (plan.levels or []) if lv.get("status") == "filled"}
    merged = []
    for lv in levels:
        prev = filled.get(str(lv.get("id")))
        merged.append(prev if prev else lv)
    plan.levels = merged
    plan.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return plan


async def list_active_plans(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str | None = None,
) -> list[RobotPlan]:
    stmt = select(RobotPlan).where(
        RobotPlan.user_id == user_id,
        RobotPlan.status == "active",
    )
    if ticker:
        stmt = stmt.where(RobotPlan.ticker == ticker.strip().upper())
    result = await db.execute(stmt.order_by(RobotPlan.created_at.desc()))
    return list(result.scalars().all())


async def complete_plans_for_maneuver(
    db: AsyncSession,
    *,
    maneuver_id: str,
    reason: str = "closed",
) -> int:
    result = await db.execute(
        select(RobotPlan).where(
            RobotPlan.maneuver_id == maneuver_id,
            RobotPlan.status == "active",
        )
    )
    plans = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for plan in plans:
        plan.status = "completed"
        plan.closed_at = now
        plan.updated_at = now
        plan.notes = (plan.notes or "") + f" | {reason}"
    if plans:
        await db.flush()
    return len(plans)


def plan_to_dict(plan: RobotPlan) -> dict[str, Any]:
    from app.services.robot.capabilities import capabilities_for_plan

    return {
        "id": plan.id,
        "ticker": plan.ticker,
        "maneuver_id": plan.maneuver_id,
        "status": plan.status,
        "side": plan.side,
        "mode": plan.mode,
        "levels": plan.levels or [],
        "kill_switch_pct": plan.kill_switch_pct,
        "notes": plan.notes,
        "plan_type": getattr(plan, "plan_type", None) or "custom",
        "plan_params": getattr(plan, "plan_params", None) or {},
        "capabilities": capabilities_for_plan(plan),
        "session_id": getattr(plan, "session_id", None),
        "is_legacy": bool(getattr(plan, "is_legacy", False)),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
