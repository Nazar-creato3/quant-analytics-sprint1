"""Paper bot entry. Does not send a live order."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.bot_core.service import list_bots, open_paper
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/bot-core", tags=["bot-core"])


@router.get("")
def get_bot_core(user_id: str = Depends(require_session_user_id)) -> dict:
    rows = []
    for row in list_bots(user_id):
        public = dict(row)
        public.pop("user_id", None)
        rows.append(public)
    return {"bots": rows, "live": False}


@router.post("/paper")
def post_bot_core_paper(
    ticker: str,
    qty: str,
    price: str,
    ccy: str = "RUB",
    user_id: str = Depends(require_session_user_id),
) -> dict:
    row = open_paper(user_id=user_id, ticker=ticker, qty=qty, price=price, ccy=ccy)
    row.pop("user_id", None)
    return row
