"""Partner offer API. The lawyer flag stays off."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.partners.service import public_view, record_click
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/partners", tags=["partners"])


class ClickIn(BaseModel):
    partner_id: str
    source: str
    consent: bool = False


@router.get("/offer")
def get_partner_offer(_user_id: str = Depends(require_session_user_id)) -> dict:
    return public_view()


@router.post("/click")
def post_partner_click(body: ClickIn, user_id: str = Depends(require_session_user_id)) -> dict:
    return record_click(user_id=user_id, partner_id=body.partner_id, source=body.source, consent=body.consent)
