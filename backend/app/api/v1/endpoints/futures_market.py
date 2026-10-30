"""Futures market analytics API (prompt 58B)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.futures_market.service import explain_market
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/futures", tags=["futures-market"])

_NOT_FOUND_RU = "Раздел временно недоступен"


@router.get("/market")
def get_futures_market(
    ticker: str = Query(..., min_length=1, max_length=32),
    user_token: bool = Query(False),
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_futures_market", user_id=user_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    return explain_market(ticker, user_token=user_token)
