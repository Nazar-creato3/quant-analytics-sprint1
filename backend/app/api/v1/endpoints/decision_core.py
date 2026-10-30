"""Decision core API. Analytics only."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.decision_core.journal import record_action, settle
from app.services.decision_core.service import collect_signals
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/decision-core", tags=["decision-core"])


class ActionIn(BaseModel):
    action: str = Field(pattern="^(opened|noted|dismissed)$")


@router.get("")
def get_signals(
    mode: str = "paper",
    portfolio_id: str | None = None,
    goal_amount: float | None = None,
    goal_date: str | None = None,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if mode not in {"paper", "live"}:
        raise HTTPException(status_code=422, detail="mode")
    if not is_enabled("qa_decision_core", user_id=user_id):
        raise HTTPException(status_code=404, detail="decision core flag off")
    extra: dict = {}
    if goal_amount is not None and goal_date:
        extra["goal_amount"] = goal_amount
        extra["goal_date"] = goal_date
    return collect_signals(user_id=user_id, mode=mode, portfolio_id=portfolio_id, extra=extra)


@router.post("/journal/{entry_id}/action")
def post_action(
    entry_id: str,
    body: ActionIn,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_decision_core", user_id=user_id):
        raise HTTPException(status_code=404, detail="decision core flag off")
    row = record_action(user_id, entry_id, body.action)
    if row is None:
        raise HTTPException(status_code=404, detail="нет записи")
    return row


@router.post("/journal/settle")
def post_settle(
    mode: str = "paper",
    as_of: date | None = None,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_decision_core", user_id=user_id):
        raise HTTPException(status_code=404, detail="decision core flag off")
    return {"entries": settle(user_id, mode=mode, as_of=as_of)}
