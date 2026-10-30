"""Robot Core API — plans, lot book, monitor tick."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.schemas.schemas import BaseSchema
from pydantic import Field
from typing import Any, Optional

router = APIRouter(prefix="/robot", tags=["robot"])


class RobotPlanOut(BaseSchema):
    id: str
    ticker: str
    maneuver_id: Optional[str] = None
    status: str
    side: str
    mode: str
    levels: list[dict[str, Any]] = Field(default_factory=list)
    kill_switch_pct: Optional[float] = None
    notes: Optional[str] = None
    plan_type: str = "custom"
    plan_params: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    is_legacy: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LotBookOut(BaseSchema):
    ticker: str
    side: str
    qty: float = 0.0
    avg_entry: Optional[float] = None
    cost_basis_usd: float = 0.0
    fee_usd: float = 0.0
    funding_usd: float = 0.0
    open_lots: int = 0
    breakeven: Optional[float] = None
    lots: list[dict[str, Any]] = Field(default_factory=list)
    plans: list[RobotPlanOut] = Field(default_factory=list)
    avg_long: Optional[float] = None
    avg_short: Optional[float] = None
    qty_long: float = 0.0
    qty_short: float = 0.0
    breakeven_long: Optional[float] = None
    breakeven_short: Optional[float] = None
    net_breakeven: Optional[float] = None
    dual: bool = False


@router.get("/book/{ticker}", response_model=LotBookOut)
async def get_robot_book(
    ticker: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> LotBookOut:
    from app.services.portfolio.lot_ledger import book_snapshot
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.plan import list_active_plans, plan_to_dict

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    snap = await book_snapshot(db, user_id=user.id, ticker=ticker)
    plans = await list_active_plans(db, user_id=user.id, ticker=ticker)
    return LotBookOut(
        **snap.to_dict(),
        plans=[RobotPlanOut.model_validate(plan_to_dict(p)) for p in plans],
    )


@router.get("/plans", response_model=list[RobotPlanOut])
async def get_robot_plans(
    ticker: str | None = Query(None),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> list[RobotPlanOut]:
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.plan import list_active_plans, plan_to_dict

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    plans = await list_active_plans(db, user_id=user.id, ticker=ticker)
    return [RobotPlanOut.model_validate(plan_to_dict(p)) for p in plans]


@router.post("/monitor/tick")
async def robot_monitor_tick(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict:
    """Operator/debug: run one LevelMonitor pass (also on celery beat)."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.robot.monitor import tick_robot_plans

    _user, role = await get_user_and_role(db, email)
    if not is_staff_admin_role(role):
        raise HTTPException(status_code=403, detail="Нужны права сотрудника")
    return await tick_robot_plans(db)


class FreqtradePlanIn(BaseSchema):
    ticker: str
    entry: float
    side: str = "long"
    mode: str = "paper"
    minimal_roi: Optional[dict[str, float]] = None
    stoploss: float = -0.08
    trailing_stop: bool = True
    trailing_stop_positive: Optional[float] = 0.015
    trailing_stop_positive_offset: Optional[float] = None
    maneuver_id: Optional[str] = None
    use_apex_defaults: bool = False


@router.post("/plans/from-freqtrade", response_model=RobotPlanOut)
async def create_freqtrade_plan(
    body: FreqtradePlanIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> RobotPlanOut:
    """Build an active RobotPlan from Freqtrade ROI/stoploss patterns (no GPL runtime)."""
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.freqtrade_bridge import APEX_SIGNAL_BRIDGE_DEFAULTS
    from app.services.robot.plan import create_plan_from_freqtrade, plan_to_dict

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    if body.entry <= 0:
        raise HTTPException(status_code=400, detail="Цена входа должна быть больше нуля")

    roi = body.minimal_roi
    stoploss = body.stoploss
    trail_pos = body.trailing_stop_positive
    if body.use_apex_defaults:
        roi = {k: v for k, v in APEX_SIGNAL_BRIDGE_DEFAULTS["minimal_roi"].items() if v}
        stoploss = float(APEX_SIGNAL_BRIDGE_DEFAULTS["stoploss"])
        trail_pos = float(APEX_SIGNAL_BRIDGE_DEFAULTS["trailing_stop_positive"])

    plan = await create_plan_from_freqtrade(
        db,
        user_id=user.id,
        ticker=body.ticker,
        entry=body.entry,
        side=body.side,
        mode=body.mode,
        minimal_roi=roi,
        stoploss=stoploss,
        trailing_stop=body.trailing_stop,
        trailing_stop_positive=trail_pos,
        trailing_stop_positive_offset=body.trailing_stop_positive_offset,
        maneuver_id=body.maneuver_id,
    )
    await db.commit()
    return RobotPlanOut.model_validate(plan_to_dict(plan))


class TypedPlanIn(BaseSchema):
    ticker: str
    entry: float
    side: str = "long"
    mode: str = "paper"
    plan_type: str = "custom"  # custom | grid | dca
    plan_params: dict[str, Any] = Field(default_factory=dict)
    maneuver_id: Optional[str] = None


@router.post("/plans/typed", response_model=RobotPlanOut)
async def create_typed_plan(
    body: TypedPlanIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> RobotPlanOut:
    """Create RobotPlan as custom / grid / dca (replaces legacy bot runtimes)."""
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.plan import create_plan_typed, plan_to_dict

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    if body.entry <= 0:
        raise HTTPException(status_code=400, detail="Цена входа должна быть больше нуля")
    if body.plan_type not in {"custom", "grid", "dca"}:
        raise HTTPException(status_code=400, detail="Неверный тип плана")
    plan = await create_plan_typed(
        db,
        user_id=user.id,
        ticker=body.ticker,
        entry=body.entry,
        side=body.side,
        mode=body.mode,
        plan_type=body.plan_type,
        plan_params=body.plan_params,
        maneuver_id=body.maneuver_id,
    )
    await db.commit()
    return RobotPlanOut.model_validate(plan_to_dict(plan))


class ShadowBarIn(BaseSchema):
    high: float
    low: float
    close: float


class ShadowRunIn(BaseSchema):
    levels: Optional[list[dict[str, Any]]] = None
    bars: list[ShadowBarIn]
    side: str = "long"
    entry: Optional[float] = None
    qty: float = 1.0
    fee_rate: float = 0.0
    kill_switch_pct: Optional[float] = 5.0
    use_apex_defaults: bool = False
    slippage_pct: float = 0.0
    latency_bars: int = 0
    partial_fill_min: float = 1.0
    seed: Optional[int] = 42


@router.post("/shadow")
async def run_shadow_backtest(
    body: ShadowRunIn,
    email: str = Depends(get_current_user_email),
) -> dict[str, Any]:
    """Event-driven RobotPlan replay over OHLC (shadow / paper research)."""
    from app.services.robot.freqtrade_bridge import levels_from_apex_signal_bridge
    from app.services.robot.shadow import run_robot_shadow, shadow_to_dict

    _ = email  # auth required
    levels = body.levels
    if not levels:
        if body.entry is None or body.entry <= 0:
            raise HTTPException(status_code=400, detail="Нужны цена входа или уровни")
        if body.use_apex_defaults:
            levels = levels_from_apex_signal_bridge(entry=body.entry, side=body.side)
        else:
            raise HTTPException(status_code=400, detail="Нужны уровни или значения по умолчанию")
    if len(body.bars) < 2:
        raise HTTPException(status_code=400, detail="Недостаточно истории цены")
    result = run_robot_shadow(
        [{"high": b.high, "low": b.low, "close": b.close} for b in body.bars],
        levels=levels,
        side=body.side,
        qty=body.qty,
        fee_rate=body.fee_rate,
        kill_switch_pct=body.kill_switch_pct,
        slippage_pct=body.slippage_pct,
        latency_bars=body.latency_bars,
        partial_fill_min=body.partial_fill_min,
        seed=body.seed,
    )
    return shadow_to_dict(result)


@router.get("/plans/{plan_id}/capabilities")
async def get_plan_capabilities(
    plan_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.db.robot_models import RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.capabilities import capabilities_for_plan

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    return capabilities_for_plan(plan)


@router.get("/plans/{plan_id}/levels")
async def get_plan_levels(
    plan_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.db.robot_models import RobotLevelFill, RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email
    from sqlalchemy import select

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    fills = await db.execute(
        select(RobotLevelFill).where(RobotLevelFill.plan_id == plan_id)
    )
    fill_rows = [
        {
            "id": f.id,
            "level_id": f.level_id,
            "action": f.action,
            "qty": f.qty,
            "price": f.price,
            "fee_usd": f.fee_usd,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in fills.scalars().all()
    ]
    return {"plan_id": plan_id, "levels": plan.levels or [], "fills": fill_rows, "status": plan.status}


@router.post("/plans/{plan_id}/levels/{level_id}/pause")
async def pause_plan_level(
    plan_id: str,
    level_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.db.robot_models import RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.session import append_session_event

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    levels = list(plan.levels or [])
    found = False
    for lv in levels:
        if str(lv.get("id")) == str(level_id):
            lv["status"] = "paused"
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Уровень не найден")
    plan.levels = levels
    await append_session_event(
        db, plan=plan, action="pause_level", detail={"level_id": level_id}, actor=user.id
    )
    await db.commit()
    return {"ok": True, "level_id": level_id, "status": "paused"}


@router.post("/plans/{plan_id}/pause")
async def pause_plan(
    plan_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.db.robot_models import RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.session import append_session_event

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    plan.status = "paused"
    await append_session_event(db, plan=plan, action="pause_plan", actor=user.id)
    await db.commit()
    return {"ok": True, "status": "paused"}


@router.post("/plans/{plan_id}/cancel")
async def cancel_plan(
    plan_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.db.robot_models import RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.session import append_session_event

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    levels = list(plan.levels or [])
    now = datetime.now(timezone.utc).isoformat()
    for lv in levels:
        if str(lv.get("status")) in {"watching", "pending", "armed"}:
            lv["status"] = "cancelled"
            lv["cancelled_at"] = now
    plan.levels = levels
    plan.status = "cancelled"
    plan.closed_at = datetime.now(timezone.utc)
    await append_session_event(
        db, plan=plan, action="cancel_plan", close_session=True, actor=user.id
    )
    await db.commit()
    return {"ok": True, "status": "cancelled"}


@router.get("/sessions")
async def list_sessions(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> list[dict[str, Any]]:
    from app.db.robot_models import StrategySession
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.session import session_to_dict
    from sqlalchemy import select

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    res = await db.execute(
        select(StrategySession)
        .where(StrategySession.user_id == user.id)
        .order_by(StrategySession.started_at.desc())
        .limit(50)
    )
    return [session_to_dict(s) for s in res.scalars().all()]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.db.robot_models import StrategySession
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.session import session_to_dict

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    sess = await db.get(StrategySession, session_id)
    if sess is None or sess.user_id != user.id:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return session_to_dict(sess)


@router.get("/plans/{plan_id}/equity-curve")
async def plan_equity_curve(
    plan_id: str,
    mode: str = Query("live"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Equity series from robot fills meta (live) or empty for shadow (client runs shadow)."""
    from app.db.models import Maneuver
    from app.db.robot_models import RobotPlan
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    plan = await db.get(RobotPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="План не найден")
    curve: list[dict[str, Any]] = []
    if plan.maneuver_id:
        m = await db.get(Maneuver, plan.maneuver_id)
        meta = m.signal_meta if m and isinstance(m.signal_meta, dict) else {}
        fills = list(meta.get("robot_fills") or [])
        pnl = 0.0
        for f in fills:
            pnl += float(f.get("realized_pnl") or 0.0)
            curve.append({"at": f.get("at"), "equity": pnl, "kind": f.get("kind")})
    return {"plan_id": plan_id, "mode": mode, "curve": curve}


@router.post("/governance/flatten")
async def governance_flatten(
    body: dict[str, Any],
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.governance import governance_to_dict, request_flatten

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    log = await request_flatten(
        db,
        initiated_by=user.id,
        reason=str(body.get("reason") or "emergency"),
        plan_ids=list(body.get("plan_ids") or []),
        required_approvals=int(body.get("required_approvals") or 2),
    )
    await db.commit()
    return governance_to_dict(log)


@router.post("/governance/approve")
async def governance_approve(
    body: dict[str, Any],
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.robot.governance import approve_governance

    user, role = await get_user_and_role(db, email)
    if not is_staff_admin_role(role):
        raise HTTPException(status_code=403, detail="Нужны права сотрудника")
    log_id = str(body.get("log_id") or "")
    if not log_id:
        raise HTTPException(status_code=400, detail="Нужен идентификатор записи")
    out = await approve_governance(db, log_id=log_id, approver_id=user.id)
    await db.commit()
    return out


@router.get("/risk/portfolio")
async def portfolio_risk_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.robot.risk import check_portfolio_kill_switch, get_or_create_risk_state

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    state = await get_or_create_risk_state(db, user.id)
    scan = await check_portfolio_kill_switch(db, user_id=user.id, flatten=False)
    await db.commit()
    return {
        "kill_switch_triggered": state.kill_switch_triggered,
        "kill_switch_reason": state.kill_switch_reason,
        "day_limit_pct": state.day_limit_pct,
        "month_limit_pct": state.month_limit_pct,
        "max_exposure_symbol_pct": state.max_exposure_symbol_pct,
        **scan,
    }


@router.post("/enrich/{ticker}")
async def enrich_market(
    ticker: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.services.robot.enricher import enrich_ticker

    _ = email
    out = await enrich_ticker(db, ticker=ticker)
    await db.commit()
    return out
