"""In-app notification center (Prompts 07 and 23)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.event_bus.notifications import circuit_state, get_store
from app.services.notify_center.service import bind_telegram, command, deliver, prefs, set_prefs, telegram_code, unsubscribe_email
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PrefsIn(BaseModel):
    user_id: str = "demo"
    channels: list[str] = ["in_app"]
    types: list[str] | None = None
    quiet_from: int | None = None
    quiet_to: int | None = None


class DeliverIn(BaseModel):
    user_id: str = "demo"
    event_name: str
    payload: dict | None = None
    hour_utc: int | None = None


class TgBindIn(BaseModel):
    code: str


class TgCmdIn(BaseModel):
    user_id: str = "demo"
    text: str


def _flag() -> None:
    if not is_enabled("qa_event_bus"):
        raise HTTPException(status_code=404, detail="event_bus flag off")


@router.get("")
def list_notifications(user_id: str = Depends(require_session_user_id), event_name: str | None = None) -> dict:
    _flag()
    rows = get_store().for_user(user_id)
    if event_name:
        rows = [r for r in rows if r.event_name == event_name]
    return {
        "items": [
            {
                "id": r.id,
                "event_name": r.event_name,
                "text": r.text,
                "read": r.read,
                "created_at": r.created_at.isoformat(),
                "href": "/portfolio-risk" if "risk" in r.event_name else "/portfolio-report",
            }
            for r in rows
        ],
        "count": len(rows),
        "circuit": circuit_state(),
        "prefs": prefs(user_id=user_id),
    }


@router.put("/prefs")
def put_prefs(body: PrefsIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    return set_prefs(user_id=same_user(body.user_id, session_id), channels=body.channels, types=body.types, quiet_from=body.quiet_from, quiet_to=body.quiet_to)


@router.post("/deliver")
def post_deliver(body: DeliverIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    return deliver(user_id=same_user(body.user_id, session_id), event_name=body.event_name, payload=body.payload, hour_utc=body.hour_utc)


@router.get("/telegram/code")
def get_tg_code(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return telegram_code(user_id=user_id)


@router.post("/telegram/bind")
def post_tg_bind(body: TgBindIn) -> dict:
    _flag()
    result = bind_telegram(code=body.code)
    if not result.get("bound"):
        raise HTTPException(status_code=403, detail=result.get("reason") or "нет данных")
    return result


@router.post("/telegram/command")
def post_tg_cmd(body: TgCmdIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    return command(user_id=same_user(body.user_id, session_id), text=body.text)


@router.post("/email/unsubscribe")
def post_unsub(token: str = Query(...)) -> dict:
    _flag()
    result = unsubscribe_email(token=token)
    if not result.get("unsubscribed"):
        raise HTTPException(status_code=403, detail=result.get("reason") or "нет данных")
    return {"unsubscribed": True}
