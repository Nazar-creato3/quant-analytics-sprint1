"""K3 tax API (prompt K3). Demo/paper only; flag qa_k3_tax."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user
from app.services.tax_ru.service import explain_tax

router = APIRouter(tags=["tax"])


@router.get("/tax")
@router.get("/portfolio/{portfolio_id}/tax")
def get_tax(
    portfolio_id: str = "me",
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    resident: bool = Query(True),
    account_type: str | None = Query(None),
    iis_opened_on: str | None = Query(None),
    iis_contribution: str | None = Query(None),
) -> dict:
    if not is_enabled("qa_k3_tax", user_id=user_id):
        raise HTTPException(status_code=404, detail="tax flag off")
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    opened: date | None = None
    if iis_opened_on:
        try:
            opened = date.fromisoformat(iis_opened_on[:10])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="iis_opened_on") from exc
    contrib: Decimal | None = None
    if iis_contribution not in (None, ""):
        contrib = Decimal(str(iis_contribution))
    return explain_tax(
        owner,
        mode=mode,
        resident=resident,
        account_type=account_type,
        iis_opened_on=opened,
        iis_contribution=contrib,
    )
