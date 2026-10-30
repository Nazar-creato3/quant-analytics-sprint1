"""Stable /api/* aliases for hourly health regression checks (Prompt 1)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.maneuvers import list_maneuvers
from app.core.deps import get_current_user_email, get_user_db
from app.services.chat.service import chat_service
from app.services.terminal_platform.market.quotes import fetch_indices

router = APIRouter(tags=["health-check-aliases"])


@router.get("/market/indices")
async def market_indices() -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc)
    rows = await fetch_indices(include_periods=False)
    market_as_of = rows[0].as_of if rows and rows[0].as_of else fetched_at.isoformat()
    sessions = {getattr(r, "session_status", None) for r in rows}
    # Health freshness must track *fetch* time, not last equity print (weekend/closed).
    return {
        "fetched_at": fetched_at.isoformat(),
        "last_updated": fetched_at.isoformat(),
        "as_of": market_as_of,
        "market_as_of": market_as_of,
        "sessions": sorted(s for s in sessions if s),
        "indices": [r.model_dump(mode="json") for r in rows],
    }


@router.get("/positions")
async def positions(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    return await list_maneuvers(
        ticker=None,
        status_filter="approved,filled,executing",
        page=1,
        page_size=100,
        skip_confidence_filter=False,
        include_orphans=False,
        email=email,
        db=db,
    )


class ChatHealthBody(BaseModel):
    message: str = Field(..., min_length=1)


@router.post("/chat")
async def chat_health(
    body: ChatHealthBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.core.rbac_deps import get_identity_for_email, get_user_and_role
    from app.domain.chat import MessageCreate

    user, role = await get_user_and_role(db, email)
    identity = await get_identity_for_email(db, email)
    from app.services.profile.service import ProfileService

    await ProfileService(db).get(user.id, create_if_missing=True)
    symbol = "SBER"
    if "SBER" not in body.message.upper():
        for token in body.message.upper().split():
            if len(token) >= 2 and token.isalpha():
                symbol = token
                break
    conv = await chat_service.get_or_create_for_symbol(
        db,
        symbol=symbol,
        client_profile_id=user.id,
        identity=identity,
        user_id=user.id,
        system_role=role,
    )
    await db.commit()
    _user_msg, advisor_msg = await chat_service.ask_advisor(
        db,
        conv.id,
        identity=identity,
        user_id=user.id,
        system_role=role,
        body=MessageCreate(body=body.message),
    )
    await db.commit()
    return {"response": advisor_msg.body, "advisor_message": {"body": advisor_msg.body}}
