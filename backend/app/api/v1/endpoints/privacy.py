"""Privacy export / erase / data map (Prompt 28)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.privacy.service import PUBLIC_DATA_MAP, erase_user_local, export_user_bundle
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/privacy", tags=["privacy"])

_UNAVAILABLE = "Нет данных"


@router.get("/data-map")
def get_data_map(_user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_privacy"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return {"items": PUBLIC_DATA_MAP, "localization": "RU"}


@router.get("/export")
def export_privacy(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_privacy"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    try:
        return export_user_bundle(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/erase")
def erase_privacy(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_privacy"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    try:
        return erase_user_local(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
