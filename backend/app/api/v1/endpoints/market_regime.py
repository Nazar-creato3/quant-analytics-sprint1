"""Unified market regime API (Prompt 12)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.market_regime.service import snapshot
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity

router = APIRouter(prefix="/regime", tags=["regime"])
_UNAVAILABLE = "Нет данных"


@router.get("")
def get_regime(
    ticker: str | None = Query(None),
    _user_id: str = Depends(require_session_identity),
) -> dict:
    if not is_enabled("qa_market_regime"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return snapshot(ticker=ticker)
