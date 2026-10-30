"""Internal forecast_log summary (public page is Prompt 11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.forecast_log.summary import internal_summary
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/forecast-log", tags=["forecast-log"])


@router.get("/summary")
def forecast_log_summary(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_forecast_log", user_id=user_id):
        raise HTTPException(status_code=404, detail="нет данных")
    out = internal_summary()
    out.pop("public", None)
    return out
