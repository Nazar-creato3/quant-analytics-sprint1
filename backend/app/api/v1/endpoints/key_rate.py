"""Key-rate scenario API (prompt 63)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.key_rate.service import explain_shift
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user

router = APIRouter(tags=["key-rate"])


class PathBody(BaseModel):
    mode: str = Field(default="paper", pattern="^(paper|live)$")
    shift_bp: int | None = None
    path: list[int] = Field(default_factory=list)
    key_rate: float | None = None
    meta: dict[str, dict] | None = None


@router.get("/portfolio/{portfolio_id}/key-rate")
def get_key_rate(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    shift_bp: int = Query(100),
    mode: str = Query("paper", pattern="^(paper|live)$"),
) -> dict:
    if not is_enabled("qa_key_rate", user_id=user_id):
        raise HTTPException(status_code=404, detail="key-rate flag off")
    owner = user_id if portfolio_id in {"me", user_id} else same_user(portfolio_id, user_id)
    return explain_shift(owner, mode=mode, shift_bp=shift_bp)


@router.post("/portfolio/{portfolio_id}/key-rate")
def post_key_rate(
    portfolio_id: str,
    body: PathBody,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_key_rate", user_id=user_id):
        raise HTTPException(status_code=404, detail="key-rate flag off")
    owner = user_id if portfolio_id in {"me", user_id} else same_user(portfolio_id, user_id)
    shift = body.shift_bp if body.shift_bp is not None else (body.path[-1] if body.path else 0)
    return explain_shift(owner, mode=body.mode, shift_bp=int(shift), path=body.path, meta=body.meta, key_rate=body.key_rate)
