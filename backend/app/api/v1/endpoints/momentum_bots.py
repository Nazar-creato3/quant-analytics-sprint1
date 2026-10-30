"""Standalone momentum bot management."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.access_deps import require_access
from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.db.models import User
from app.domain.access_policy import AccessAction
from app.services.bots.common import build_summary, init_activity_state
from app.services.bots.momentum import apply_momentum_tick, new_runtime
from app.services.bots.store import assert_bot_owner, load_bots, load_user_bots, save_bots
from app.utils.audit import AuditAction, audit

logger = get_logger(__name__)
router = APIRouter(prefix="/momentum", tags=["momentum bots"])

_MOMENTUM_KEY = "momentum:bots"
_memory_bots: dict[str, dict] = {}


class CreateMomentumRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    total_capital: float = Field(..., gt=0)
    position_size_pct: float = Field(0.5, gt=0, le=1.0)
    lookback_ticks: int = Field(20, ge=5, le=200)
    entry_momentum_pct: float = Field(0.03, ge=0.001, le=0.5)
    take_profit_pct: float = Field(0.06, ge=0.001, le=1.0)
    stop_loss_pct: float = Field(0.04, ge=0.001, le=0.5)
    current_price: float = Field(..., gt=0)


class MomentumSummaryOut(BaseModel):
    bot_id: str
    ticker: str
    total_capital: float
    is_active: bool
    is_paused: bool = False
    total_trades: int
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    last_price: float | None
    last_activity_at: str | None = None
    session_pnl: float = 0.0
    executor_state: str = "watching"
    entries_count: int = 0
    position_qty: float = 0.0


class MomentumActivityOut(MomentumSummaryOut):
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    pnl_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    paper_trades: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


def _summary_out(bot_id: str, data: dict[str, Any]) -> MomentumSummaryOut:
    s = build_summary(bot_id, data)
    runtime = data.get("runtime", {})
    s["entries_count"] = 1 if float(runtime.get("position_qty", 0) or 0) > 0 else 0
    return MomentumSummaryOut(**s)


@router.post("", response_model=MomentumSummaryOut, status_code=status.HTTP_201_CREATED)
async def create_momentum_bot(
    body: CreateMomentumRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumSummaryOut:
    bot_id = str(uuid.uuid4())
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    bots[bot_id] = {
        "config": {
            "ticker": body.ticker.upper(),
            "total_capital": body.total_capital,
            "position_size_pct": body.position_size_pct,
            "lookback_ticks": body.lookback_ticks,
            "entry_momentum_pct": body.entry_momentum_pct,
            "take_profit_pct": body.take_profit_pct,
            "stop_loss_pct": body.stop_loss_pct,
            "entry_price": body.current_price,
        },
        "runtime": new_runtime(body.current_price),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
        "created_by": email,
        "bot_id": bot_id,
    }
    init_activity_state(bots[bot_id], message=f"Momentum bot created for {body.ticker.upper()}")
    tick_price = body.current_price
    try:
        from app.services.market_data.client import get_grid_tick_quote
        from app.services.market_data.quote_utils import extract_quote_price

        quote = await get_grid_tick_quote(body.ticker.upper())
        resolved = extract_quote_price(quote)
        if resolved and resolved > 0:
            tick_price = resolved
    except Exception as exc:
        logger.debug("Momentum create quote fallback", error=str(exc))

    bots[bot_id] = apply_momentum_tick(bots[bot_id], tick_price, bot_id=bot_id)
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)
    await audit.log(
        db,
        action=AuditAction.PIPELINE_TRIGGERED,
        details={"event": "momentum_bot_created", "bot_id": bot_id, "ticker": body.ticker.upper()},
    )
    return _summary_out(bot_id, bots[bot_id])


@router.get("", response_model=list[MomentumSummaryOut])
async def list_momentum_bots(
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> list[MomentumSummaryOut]:
    bots = await load_user_bots(_MOMENTUM_KEY, _memory_bots, email)
    return [_summary_out(bot_id, data) for bot_id, data in bots.items()]


@router.get("/{bot_id}", response_model=MomentumActivityOut)
async def get_momentum_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumActivityOut:
    bots = await load_user_bots(_MOMENTUM_KEY, _memory_bots, email)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(data, email)
    summary = build_summary(bot_id, data)
    runtime = data.get("runtime", {})
    summary["entries_count"] = 1 if float(runtime.get("position_qty", 0) or 0) > 0 else 0
    return MomentumActivityOut(
        **summary,
        recent_events=list(data.get("recent_events") or []),
        pnl_snapshots=list(data.get("pnl_snapshots") or []),
        paper_trades=list(data.get("paper_trades") or [])[-20:],
        config=dict(data.get("config") or {}),
        runtime=dict(runtime),
    )


@router.post("/{bot_id}/pause", response_model=MomentumSummaryOut)
async def pause_momentum_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumSummaryOut:
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(data, email)
    data["is_paused"] = True
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/resume", response_model=MomentumSummaryOut)
async def resume_momentum_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumSummaryOut:
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(data, email)
    data["is_paused"] = False
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/stop", response_model=MomentumSummaryOut)
async def stop_momentum_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumSummaryOut:
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(data, email)
    data["is_active"] = False
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_momentum_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> None:
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    if bot_id not in bots:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(bots[bot_id], email)
    del bots[bot_id]
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)


@router.post("/{bot_id}/price", response_model=MomentumSummaryOut)
async def manual_momentum_tick(
    bot_id: str,
    price: float,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> MomentumSummaryOut:
    if price <= 0:
        raise HTTPException(400, "price must be positive")
    bots = await load_bots(_MOMENTUM_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "Momentum bot not found")
    assert_bot_owner(data, email)
    bots[bot_id] = apply_momentum_tick(data, price, bot_id=bot_id)
    await save_bots(_MOMENTUM_KEY, _memory_bots, bots)
    return _summary_out(bot_id, bots[bot_id])
