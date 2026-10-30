"""Connect-capital onboarding API (Prompt 19)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.onboarding.service import connect_key, funnel_snapshot, start, status, sync_once, try_demo
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class StartIn(BaseModel):
    user_id: str = "demo"
    path: str
    venue: str | None = None


class KeyIn(BaseModel):
    user_id: str = "demo"
    venue: str
    accepted: bool = True
    withdraw_allowed: bool = False
    venue_up: bool = True
    has_history: bool = True


class SyncIn(BaseModel):
    user_id: str = "demo"
    slow: bool = False


def _flag() -> None:
    if not is_enabled("qa_onboarding"):
        raise HTTPException(status_code=404, detail="нет данных")


@router.get("/status")
def get_status(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return status(user_id)


@router.post("/start")
def post_start(body: StartIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return start(same_user(body.user_id, session_id), body.path, body.venue)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/key")
def post_key(body: KeyIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    return connect_key(
        same_user(body.user_id, session_id),
        venue=body.venue,
        accepted=body.accepted,
        withdraw_allowed=body.withdraw_allowed,
        venue_up=body.venue_up,
        has_history=body.has_history,
    )


@router.post("/sync")
def post_sync(body: SyncIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return sync_once(same_user(body.user_id, session_id), slow=body.slow)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="нет сессии") from exc


@router.post("/demo")
def post_demo(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return try_demo(user_id)


@router.get("/funnel")
def get_funnel(_user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return {"events": funnel_snapshot()}
