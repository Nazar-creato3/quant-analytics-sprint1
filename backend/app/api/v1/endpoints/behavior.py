"""Behavior API (Prompt 15)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.behavior.service import analyze_user
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/behavior", tags=["behavior"])


@router.get("")
def get_behavior(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    if not is_enabled("qa_behavior"):
        raise HTTPException(status_code=404, detail="behavior flag off")
    return analyze_user(user_id=user_id, mode=mode)
