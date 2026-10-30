"""Pre-trade gate preview and journal (Prompt 10)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.pretrade.journal import history
from app.services.pretrade.policy import evaluate
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user

router = APIRouter(prefix="/risk-gate", tags=["risk-gate"])


class PreviewIn(BaseModel):
    user_id: str
    ticker: str
    qty: float
    price: float
    kind: str = "manual_order"
    actor: str = "human"
    mode: str = "paper"
    confirmed: bool = False
    nav: float | None = None


@router.post("/preview")
def preview(body: PreviewIn, session_id: str = Depends(require_session_identity)) -> dict:
    if not is_enabled("qa_risk_gate"):
        raise HTTPException(status_code=404, detail="risk gate flag off")
    user_id = same_user(body.user_id, session_id)
    return evaluate(
        kind=body.kind,  # type: ignore[arg-type]
        actor=body.actor,  # type: ignore[arg-type]
        user_id=user_id,
        ticker=body.ticker,
        qty=body.qty,
        price=body.price,
        mode=body.mode,  # type: ignore[arg-type]
        confirmed=body.confirmed,
        nav=body.nav,
    ).as_dict()


@router.get("/history")
def get_history(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_risk_gate"):
        raise HTTPException(status_code=404, detail="risk gate flag off")
    return {"rows": history(user_id=user_id)}
