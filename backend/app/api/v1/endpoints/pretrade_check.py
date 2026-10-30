from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.pretrade_check.service import check_basket, list_scenarios, save_scenario
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user

router = APIRouter(tags=["pretrade-check"])


class BasketIn(BaseModel):
    trades: list[dict[str, Any]]
    funding: str | None = None
    mode: str = "paper"


@router.post("/portfolio/{portfolio_id}/pretrade")
def post_pretrade(
    portfolio_id: str,
    body: BasketIn,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_60_pretrade"):
        raise HTTPException(status_code=404, detail="60 flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    try:
        return check_basket(user_id=owner, mode=body.mode, trades=body.trades, funding=body.funding)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/portfolio/{portfolio_id}/pretrade/scenarios")
def post_scenario(
    portfolio_id: str,
    body: BasketIn,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_60_pretrade"):
        raise HTTPException(status_code=404, detail="60 flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    table = check_basket(user_id=owner, mode=body.mode, trades=body.trades, funding=body.funding)
    return save_scenario(user_id=owner, payload={"trades": body.trades, "table": table})


@router.get("/portfolio/{portfolio_id}/pretrade/scenarios")
def get_scenarios(portfolio_id: str, user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_60_pretrade"):
        raise HTTPException(status_code=404, detail="60 flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    return {"items": list_scenarios(user_id=owner)}
