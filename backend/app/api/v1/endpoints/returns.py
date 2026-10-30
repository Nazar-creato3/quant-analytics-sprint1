"""Returns API (Prompt 08)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.benchmark_alt.service import as_dict as alts_as_dict
from app.services.benchmark_alt.service import compare_simple_alternatives
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id
from app.services.returns.service import as_dict, compute_returns

router = APIRouter(prefix="/returns", tags=["returns"])


@router.get("")
def get_returns(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    period: str = Query("inception"),
) -> dict:
    if not is_enabled("qa_returns"):
        raise HTTPException(status_code=404, detail="returns flag off")
    if period not in {"month", "quarter", "year", "inception", "custom"}:
        raise HTTPException(status_code=400, detail="bad period")
    try:
        result = compute_returns(user_id=user_id, mode=mode, period=period)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return as_dict(result)


@router.get("/simple-alts")
def get_simple_alts(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper", pattern="^(paper|live)$"),
    period: str = Query("inception"),
) -> dict:
    if not is_enabled("qa_k1_benchmark"):
        raise HTTPException(status_code=404, detail="k1 flag off")
    if period not in {"month", "quarter", "year", "inception", "custom"}:
        raise HTTPException(status_code=400, detail="bad period")
    try:
        payload = compare_simple_alternatives(user_id=user_id, mode=mode, period=period)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return alts_as_dict(payload)
