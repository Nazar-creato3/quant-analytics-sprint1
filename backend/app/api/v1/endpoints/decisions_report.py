"""Decisions report API."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.decisions_report.service import analyze_decisions
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id, same_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])

_NOT_FOUND_RU = "Раздел временно недоступен"
_BAD_REQUEST_RU = "Не удалось построить отчёт. Проверьте параметры и повторите."


@router.get("/portfolio/{portfolio_id}/decisions")
def get_decisions(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict:
    if not is_enabled("qa_59_decisions"):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    try:
        return analyze_decisions(user_id=owner, mode=mode, date_from=date_from, date_to=date_to)
    except Exception as exc:
        logger.info("decisions_report_failed: %s", exc)
        raise HTTPException(status_code=400, detail=_BAD_REQUEST_RU) from exc


@router.get("/portfolio/{portfolio_id}/decisions/trades")
def get_decision_trades(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    metric: str = Query("disposition"),
) -> dict:
    if not is_enabled("qa_59_decisions"):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    owner = user_id if portfolio_id in {"me", "paper", user_id} else same_user(portfolio_id, user_id)
    try:
        payload = analyze_decisions(user_id=owner, mode=mode, metric=metric)
    except Exception as exc:
        logger.info("decisions_trades_failed: %s", exc)
        raise HTTPException(status_code=400, detail=_BAD_REQUEST_RU) from exc
    return {"metric": metric, "trades": payload.get("trades") or []}
