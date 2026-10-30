"""Client product events. Server events are not accepted on this route."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_admin
from app.services.product_analytics.metrics import metrics, weekly_summary
from app.services.product_analytics.service import plan, record_event
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/plan")
def get_analytics_plan(_user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_product_analytics"):
        raise HTTPException(status_code=404, detail="нет данных")
    return {"events": plan()}


@router.post("/events")
def post_analytics_event(
    body: dict,
    _user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_product_analytics"):
        raise HTTPException(status_code=404, detail="нет данных")
    properties = body.get("properties")
    return record_event(
        name=str(body.get("name") or ""),
        side="client",
        subject=str(body.get("subject") or ""),
        properties=properties if isinstance(properties, dict) else {},
        consent=body.get("consent") is True,
        do_not_track=body.get("do_not_track") is True,
    )


@router.get("/metrics")
def get_founder_metrics(_admin: dict = Depends(require_admin)) -> dict:
    if not is_enabled("qa_founder_metrics"):
        raise HTTPException(status_code=404, detail="нет данных")
    return metrics()


@router.get("/weekly")
def get_weekly_summary(_admin: dict = Depends(require_admin)) -> dict:
    if not is_enabled("qa_founder_metrics"):
        raise HTTPException(status_code=404, detail="нет данных")
    return weekly_summary()
