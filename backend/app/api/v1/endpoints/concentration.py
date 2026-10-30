"""Concentration API (Prompt 14)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.concentration.service import analyze_portfolio
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/concentration", tags=["concentration"])


@router.get("")
def get_concentration(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    if not is_enabled("qa_concentration"):
        raise HTTPException(status_code=404, detail="concentration flag off")
    return analyze_portfolio(user_id=user_id, mode=mode)
