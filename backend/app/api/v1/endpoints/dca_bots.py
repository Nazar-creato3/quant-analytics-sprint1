"""Standalone DCA bot management — separate from grid hybrid dca_enabled."""
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
from app.services.bots.dca import apply_dca_tick, new_runtime
from app.services.bots.store import assert_bot_owner, load_bots, load_user_bots, save_bots
from app.utils.audit import AuditAction, audit

logger = get_logger(__name__)
router = APIRouter(prefix="/dca", tags=["dca bots"])

_DCA_KEY = "dca:bots"
_memory_bots: dict[str, dict] = {}


class CreateDcaRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    total_capital: float = Field(..., gt=0)
    order_size_usd: float = Field(500.0, gt=0)
    max_entries: int = Field(10, ge=1, le=100)
    interval_ticks: int = Field(5, ge=1, le=1000, description="Simulated hours via Celery ticks")
    dip_pct: float = Field(0.02, ge=0.0, le=0.5)
    take_profit_pct: float = Field(0.05, ge=0.001, le=1.0)
    current_price: float = Field(..., gt=0)


class DcaSummaryOut(BaseModel):
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
    executor_state: str = "accumulating"
    entries_count: int = 0
    position_qty: float = 0.0
    is_legacy: bool = True
    migration_hint: str = "Legacy DCA bot — migrate to RobotPlan (plan_type=dca)"


class DcaActivityOut(DcaSummaryOut):
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    pnl_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    paper_trades: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


def _summary_out(bot_id: str, data: dict[str, Any]) -> DcaSummaryOut:
    s = build_summary(bot_id, data)
    return DcaSummaryOut(**s)


async def _get_bot(bot_id: str, email: str) -> dict[str, Any]:
    bots = await load_user_bots(_DCA_KEY, _memory_bots, email)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DCA bot not found")
    assert_bot_owner(data, email)
    return data


@router.post("", response_model=DcaSummaryOut, status_code=status.HTTP_201_CREATED)
async def create_dca_bot(
    body: CreateDcaRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaSummaryOut:
    if body.order_size_usd * body.max_entries > body.total_capital + 1e-6:
        raise HTTPException(400, "order_size_usd * max_entries exceeds total_capital")

    bot_id = str(uuid.uuid4())
    bots = await load_bots(_DCA_KEY, _memory_bots)
    bots[bot_id] = {
        "config": {
            "ticker": body.ticker.upper(),
            "total_capital": body.total_capital,
            "order_size_usd": body.order_size_usd,
            "max_entries": body.max_entries,
            "interval_ticks": body.interval_ticks,
            "dip_pct": body.dip_pct,
            "take_profit_pct": body.take_profit_pct,
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
    init_activity_state(bots[bot_id], message=f"DCA bot created for {body.ticker.upper()}")
    tick_price = body.current_price
    try:
        from app.services.market_data.client import get_grid_tick_quote
        from app.services.market_data.quote_utils import extract_quote_price

        quote = await get_grid_tick_quote(body.ticker.upper())
        resolved = extract_quote_price(quote)
        if resolved and resolved > 0:
            tick_price = resolved
    except Exception as exc:
        logger.debug("DCA create quote fallback", error=str(exc))

    bots[bot_id] = apply_dca_tick(bots[bot_id], tick_price, bot_id=bot_id)
    await save_bots(_DCA_KEY, _memory_bots, bots)
    await audit.log(
        db,
        action=AuditAction.PIPELINE_TRIGGERED,
        details={"event": "dca_bot_created", "bot_id": bot_id, "ticker": body.ticker.upper()},
    )
    return _summary_out(bot_id, bots[bot_id])


@router.get("", response_model=list[DcaSummaryOut])
async def list_dca_bots(
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> list[DcaSummaryOut]:
    bots = await load_user_bots(_DCA_KEY, _memory_bots, email)
    return [_summary_out(bot_id, data) for bot_id, data in bots.items()]


@router.get("/{bot_id}", response_model=DcaActivityOut)
async def get_dca_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaActivityOut:
    data = await _get_bot(bot_id, email)
    summary = build_summary(bot_id, data)
    return DcaActivityOut(
        **summary,
        recent_events=list(data.get("recent_events") or []),
        pnl_snapshots=list(data.get("pnl_snapshots") or []),
        paper_trades=list(data.get("paper_trades") or [])[-20:],
        config=dict(data.get("config") or {}),
        runtime=dict(data.get("runtime") or {}),
    )


@router.post("/{bot_id}/pause", response_model=DcaSummaryOut)
async def pause_dca_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaSummaryOut:
    bots = await load_bots(_DCA_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "DCA bot not found")
    assert_bot_owner(data, email)
    data["is_paused"] = True
    await save_bots(_DCA_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/resume", response_model=DcaSummaryOut)
async def resume_dca_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaSummaryOut:
    bots = await load_bots(_DCA_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "DCA bot not found")
    assert_bot_owner(data, email)
    data["is_paused"] = False
    await save_bots(_DCA_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/stop", response_model=DcaSummaryOut)
async def stop_dca_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaSummaryOut:
    bots = await load_bots(_DCA_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "DCA bot not found")
    assert_bot_owner(data, email)
    data["is_active"] = False
    await save_bots(_DCA_KEY, _memory_bots, bots)
    return _summary_out(bot_id, data)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dca_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> None:
    bots = await load_bots(_DCA_KEY, _memory_bots)
    if bot_id not in bots:
        raise HTTPException(404, "DCA bot not found")
    assert_bot_owner(bots[bot_id], email)
    del bots[bot_id]
    await save_bots(_DCA_KEY, _memory_bots, bots)


@router.post("/{bot_id}/price", response_model=DcaSummaryOut)
async def manual_dca_tick(
    bot_id: str,
    price: float,
    email: str = Depends(get_current_user_email),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> DcaSummaryOut:
    if price <= 0:
        raise HTTPException(400, "price must be positive")
    bots = await load_bots(_DCA_KEY, _memory_bots)
    data = bots.get(bot_id)
    if not data:
        raise HTTPException(404, "DCA bot not found")
    assert_bot_owner(data, email)
    bots[bot_id] = apply_dca_tick(data, price, bot_id=bot_id)
    await save_bots(_DCA_KEY, _memory_bots, bots)
    return _summary_out(bot_id, bots[bot_id])
