"""Attach the e2e/demo fixture book. 404 unless QA_E2E_DEMO is on."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.services.e2e_demo.seed import apply_demo_book
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/e2e", tags=["e2e-demo"])


@router.post("/demo-book")
def demo_book(user_id: str = Depends(require_session_user_id)) -> dict:
    if not settings.QA_E2E_DEMO:
        raise HTTPException(status_code=404, detail="not found")
    return apply_demo_book(user_id)
