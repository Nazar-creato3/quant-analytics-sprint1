"""Look-through HTTP API (prompt 61)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.fund_lookthrough.service import fund_holdings_payload, lookthrough_portfolio
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user

router = APIRouter(tags=["fund-lookthrough"])

_UNAVAILABLE = "Раздел временно недоступен"


@router.get("/portfolio/{portfolio_id}/lookthrough")
def get_lookthrough(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    by: str = Query("issuer", pattern="^(issuer|sector|asset_class|currency|country)$"),
    view: str = Query("lookthrough", pattern="^(lookthrough|broker)$"),
) -> dict:
    if not is_enabled("qa_fund_lookthrough", user_id=user_id):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    return lookthrough_portfolio(owner, mode=mode, by=by, view=view)


@router.get("/funds/{figi}/holdings")
def get_fund_holdings(
    figi: str,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_fund_lookthrough", user_id=user_id):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return fund_holdings_payload(figi)
