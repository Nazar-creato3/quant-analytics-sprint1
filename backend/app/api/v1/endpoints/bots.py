"""Unified bots API — grid / dca / momentum catalog."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.access_deps import require_access
from app.core.deps import get_current_user_email, get_db
from app.domain.access_policy import AccessAction
from app.services.bots.unified import create_bot, delete_bot, get_bot, list_bots, patch_bot
from app.utils.audit import AuditAction, audit

router = APIRouter(prefix="/bots", tags=["bots"])


class CreateBotRequest(BaseModel):
    bot_type: str = Field(..., min_length=3, max_length=16)
    symbol: str = Field(..., min_length=1, max_length=24)
    params: dict[str, Any] = Field(default_factory=dict)
    balance_allocated: float = Field(..., gt=0)


class PatchBotRequest(BaseModel):
    status: str | None = Field(None, min_length=3, max_length=16)
    params: dict[str, Any] | None = None


class BotOut(BaseModel):
    id: str
    bot_type: str
    symbol: str
    status: str
    params: dict[str, Any] = Field(default_factory=dict)
    total_trades: int = 0
    pnl: float = 0.0
    balance_allocated: float = 0.0
    created_at: str | None = None


def _user_id(user: Any) -> str | None:
    raw = getattr(user, "id", None)
    return str(raw) if raw is not None else None


@router.post("", response_model=BotOut, status_code=201)
async def create_unified_bot(
    body: CreateBotRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    user: Any = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> BotOut:
    out = await create_bot(
        db=db,
        email=email,
        user_id=_user_id(user),
        bot_type=body.bot_type,
        symbol=body.symbol,
        params=body.params,
        balance_allocated=body.balance_allocated,
    )
    await audit.log(
        db,
        action=AuditAction.PIPELINE_TRIGGERED,
        details={"event": "bot_created", "bot_id": out["id"], "bot_type": out["bot_type"], "symbol": out["symbol"]},
    )
    return BotOut(**out)


@router.get("", response_model=list[BotOut])
async def list_unified_bots(
    bot_type: str | None = Query(None),
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: Any = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> list[BotOut]:
    items = await list_bots(db=db, email=email, bot_type=bot_type)
    return [BotOut(**item) for item in items]


@router.get("/{bot_id}", response_model=BotOut)
async def get_unified_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: Any = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> BotOut:
    return BotOut(**await get_bot(db=db, email=email, bot_id=bot_id))


@router.patch("/{bot_id}", response_model=BotOut)
async def patch_unified_bot(
    bot_id: str,
    body: PatchBotRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    user: Any = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> BotOut:
    return BotOut(
        **await patch_bot(
            db=db,
            email=email,
            user_id=_user_id(user),
            bot_id=bot_id,
            status_value=body.status,
            params=body.params,
        )
    )


@router.delete("/{bot_id}", status_code=204)
async def delete_unified_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: Any = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> None:
    await delete_bot(db=db, email=email, bot_id=bot_id)
