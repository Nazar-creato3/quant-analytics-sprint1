"""Factor lens API (prompt 65)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.factor_lens.service import explain_portfolio
from app.services.factor_lens.store import snapshot
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user

router = APIRouter(tags=["factors"])


@router.get("/factors/returns")
def get_factor_returns(
    user_id: str = Depends(require_session_user_id),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict:
    if not is_enabled("qa_factor_lens", user_id=user_id):
        raise HTTPException(status_code=404, detail="factor flag off")
    return snapshot(start=date_from, end=date_to)


@router.get("/portfolio/{portfolio_id}/factors")
def get_portfolio_factors(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
) -> dict:
    if not is_enabled("qa_factor_lens", user_id=user_id):
        raise HTTPException(status_code=404, detail="factor flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    return explain_portfolio(owner, mode=mode)
