"""Model-risk registry and validation (Prompt 11B)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.model_risk.service import status
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/model-risk", tags=["model-risk"])


@router.get("/status")
def model_risk_status(_user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_model_risk"):
        raise HTTPException(status_code=404, detail="model_risk flag off")
    try:
        return status()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
