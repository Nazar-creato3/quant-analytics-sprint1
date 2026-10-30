"""Unified risk API (Prompt 09)."""
from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id
from app.services.risk_engine.hooks import register
from app.services.risk_engine.service import backtests, compute_risk_for_user, compute_what_if
from app.services.risk_engine.shadow import diffs

router = APIRouter(prefix="/risk", tags=["risk"])
register()
logger = get_logger(__name__)
_UNAVAILABLE = "Нет данных"


class WhatIfHolding(BaseModel):
    ticker: str
    qty: str | float | None = None
    price: str | float | None = None
    ccy: str = "RUB"
    value: str | float | None = None


class WhatIfRequest(BaseModel):
    mode: str = Field(default="paper", pattern="^(paper|live)$")
    holdings: list[WhatIfHolding] | None = None
    remove: list[str] | None = None
    add: list[WhatIfHolding] | None = None
    set_weight: dict[str, float] | None = None
    add_cash_rub: float | None = None


@router.get("")
def get_risk(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
) -> dict:
    if not is_enabled("qa_risk_engine"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    try:
        return compute_risk_for_user(user_id, mode)
    except Exception as exc:
        logger.warning("risk compute failed", error=str(exc), user_id=user_id)
        raise HTTPException(status_code=400, detail=_UNAVAILABLE) from exc


@router.post("/what-if")
def post_what_if(
    body: WhatIfRequest,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_risk_engine") or not is_enabled("qa_k4_risk_attribution"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    started = perf_counter()
    try:
        payload = compute_what_if(
            user_id=user_id,
            mode=body.mode,
            holdings=[h.model_dump() for h in body.holdings] if body.holdings is not None else None,
            remove=body.remove,
            add=[h.model_dump() for h in body.add] if body.add else None,
            set_weight=body.set_weight,
            add_cash_rub=body.add_cash_rub,
        )
    except Exception as exc:
        logger.warning("risk what-if failed", error=str(exc), user_id=user_id)
        raise HTTPException(status_code=400, detail=_UNAVAILABLE) from exc
    payload["elapsed_ms"] = round((perf_counter() - started) * 1000.0, 3)
    return payload


@router.get("/backtests")
def get_backtests(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_risk_engine"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return {"user_id": user_id, "scenarios": backtests()}


@router.get("/shadow")
def get_shadow(user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_risk_engine"):
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return {"user_id": user_id, "rows": diffs(user_id=user_id)}
