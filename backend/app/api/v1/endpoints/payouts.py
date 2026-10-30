from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.services.payouts.service import (
    cashflow_summary,
    dividend_gap,
    notify_copy,
    portfolio_cashflows,
    reinvest_scenario,
    to_ics,
)
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(tags=["payouts"])


def _guard() -> None:
    if not is_enabled("qa_payouts"):
        raise HTTPException(status_code=404, detail="payouts flag off")


@router.get("/portfolio/{portfolio_id}/cashflows")
def get_cashflows(
    portfolio_id: str,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    types: str | None = None,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    _guard()
    return portfolio_cashflows(user_id, portfolio_id, date_from=date_from, date_to=date_to, types=types)


@router.get("/portfolio/{portfolio_id}/cashflows/summary")
def get_summary(
    portfolio_id: str,
    months: int = 12,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    _guard()
    return cashflow_summary(user_id, portfolio_id, months=months)


@router.get("/portfolio/{portfolio_id}/cashflows.ics")
def get_ics(portfolio_id: str, user_id: str = Depends(require_session_user_id)) -> Response:
    _guard()
    book = portfolio_cashflows(user_id, portfolio_id)
    body = to_ics(book.get("events") or [])
    return Response(content=body, media_type="text/calendar")


@router.get("/dividends/{ticker}/gap")
def get_gap(ticker: str, user_id: str = Depends(require_session_user_id)) -> dict:
    _guard()
    return dividend_gap(ticker)


@router.get("/portfolio/{portfolio_id}/cashflows/reinvest")
def get_reinvest(portfolio_id: str, user_id: str = Depends(require_session_user_id)) -> dict:
    _guard()
    return reinvest_scenario(user_id)


@router.get("/payouts/notify-copy")
def get_notify(kind: str = "last_buy", user_id: str = Depends(require_session_user_id)) -> dict:
    _guard()
    return {"text": notify_copy(kind=kind, amount=2800.0 if kind == "pay" else None), "user_id": user_id}
