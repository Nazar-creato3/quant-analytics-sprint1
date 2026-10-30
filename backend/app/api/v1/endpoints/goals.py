"""Goals with probability API (prompt K5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.goals.service import explain_goal
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/goals", tags=["goals"])

_NOT_FOUND_RU = "Раздел временно недоступен"


class GoalIn(BaseModel):
    target_amount: float = Field(gt=0)
    target_date: str
    monthly_contrib: float = 0.0
    mode: str = Field(default="paper", pattern="^(paper|live)$")


@router.post("")
def post_goal(body: GoalIn, user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_goals", user_id=user_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    return explain_goal(
        user_id,
        target_amount=body.target_amount,
        target_date=body.target_date,
        monthly_contrib=body.monthly_contrib,
        mode=body.mode,
    )
