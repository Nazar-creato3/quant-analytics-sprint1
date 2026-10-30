from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user
from app.services.total_costs.service import analyze_costs

router = APIRouter(tags=["costs"])


@router.get("/portfolio/{portfolio_id}/costs")
def get_costs(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    year: int | None = Query(default=None),
) -> dict:
    if not is_enabled("qa_62_costs"):
        raise HTTPException(status_code=404, detail="62 flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    try:
        return analyze_costs(user_id=owner, mode=mode, year=year)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
