"""K3 RF tax demo API. Flag qa_tax_rf off by default ([ЮРИСТ])."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.qa.session_user import require_session_user_id
from app.services.tax_rf.service import demo_tax_payload

router = APIRouter(tags=["tax-rf"])


@router.get("/tax/demo")
def get_tax_demo(user_id: str = Depends(require_session_user_id)) -> dict:
    """Always 200. Flag off → status=flag_off (no demo numbers)."""
    return demo_tax_payload(user_id)
