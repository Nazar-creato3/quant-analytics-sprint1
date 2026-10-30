"""Stress library API (Prompt 13)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id
from app.services.stress_library.service import list_scenarios, run_portfolio

router = APIRouter(prefix="/stress-library", tags=["stress-library"])


@router.get("")
def get_stress(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    if not is_enabled("qa_stress_library"):
        raise HTTPException(status_code=404, detail="stress library flag off")
    payload = run_portfolio(user_id=user_id, mode=mode)
    payload["catalog"] = list_scenarios()
    return payload
