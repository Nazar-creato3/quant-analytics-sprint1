"""Subscription quote API. Does not create a live charge."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.qa.session_user import require_session_user_id
from app.services.subscription_billing.service import account, quote

router = APIRouter(prefix="/subscription", tags=["subscription"])


@router.get("/quote")
def get_subscription_quote(
    plan: str = "personal",
    period: str = "month",
    user_id: str = Depends(require_session_user_id),
) -> dict:
    return quote(user_id=user_id, plan=plan, period=period)


@router.get("/account")
def get_subscription_account(user_id: str = Depends(require_session_user_id)) -> dict:
    row = account(user_id)
    if row is None:
        return {"status": "нет данных"}
    public = dict(row)
    public.pop("user_id", None)
    return public
