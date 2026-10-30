"""User risk settings API. Regulated-profile fields (age, income, savings…) are not accepted."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.investment_profile.service import (
    due_for_review,
    get_profile,
    history_for,
    save_profile,
    warnings_vs_portfolio,
)
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user

router = APIRouter(prefix="/investment-profile", tags=["investment-profile"])


class ProfileIn(BaseModel):
    user_id: str = "demo"
    horizon: str
    risk_tolerance: str
    expected_return: str = ""
    max_position_pct: str
    max_crisis_loss_pct: str
    banned_tickers: str = ""
    banned_sectors: str = ""
    banned_issuers: str = ""
    max_sector_pct: str = ""
    currencies: str = ""
    account_type: str = "regular"
    iis_type: str = ""
    liquidity_days: str = ""
    tax_pref: str = ""
    qualified_investor: bool = False
    qualified_docs_verified: bool = False
    purpose: str = "учёт капитала"
    mode: str = "paper"


def _flag() -> None:
    if not is_enabled("qa_investment_profile"):
        raise HTTPException(status_code=404, detail="investment profile flag off")


@router.get("")
def api_get(user_id: str = Depends(require_session_user_id), mode: str = "paper") -> dict:
    _flag()
    row = get_profile(user_id)
    if row is None:
        return {"empty": True, "data_status": "нет данных"}
    return {
        **row,
        "warnings": warnings_vs_portfolio(user_id, mode=mode),
        "review": due_for_review(user_id, mode=mode),
        "history": history_for(user_id),
    }


@router.post("")
def api_save(body: ProfileIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    uid = same_user(body.user_id, session_id)
    payload = body.model_dump()
    payload["user_id"] = uid
    saved = save_profile(uid, payload, actor="user")
    return {
        **saved,
        "warnings": warnings_vs_portfolio(uid, mode=body.mode),
        "review": due_for_review(uid, mode=body.mode),
        "history": history_for(uid),
    }
