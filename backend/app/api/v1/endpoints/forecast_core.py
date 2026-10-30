"""Unified forecast + public accuracy (Prompt 11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.logging import get_logger
from app.services.forecast_core.service import forecast, public_accuracy
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id

router = APIRouter(tags=["forecast-core"])
logger = get_logger(__name__)


@router.get("/forecast-core")
def get_forecast_core(
    ticker: str = Query(...),
    horizon_days: int = Query(1),
    _user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_forecast_core"):
        raise HTTPException(status_code=404, detail="нет данных")
    try:
        return forecast(ticker, horizon_days, section="forecast")
    except Exception as exc:
        logger.warning("forecast-core failed", error=str(exc))
        raise HTTPException(status_code=400, detail="нет данных") from exc


@router.get("/forecast-accuracy")
def get_forecast_accuracy(_user_id: str = Depends(require_session_identity)) -> dict:
    if not is_enabled("qa_forecast_core"):
        raise HTTPException(status_code=404, detail="нет данных")
    return public_accuracy()
