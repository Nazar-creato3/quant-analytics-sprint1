"""Local performance budget and in-process 1000-session load."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.perf_budget.service import budget_run, last_budget
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/ops/perf", tags=["ops-perf"])


@router.get("")
def get_perf_budget(user_id: str = Depends(require_session_user_id)) -> dict:
    del user_id
    return last_budget()


@router.post("/run")
def post_perf_budget(user_id: str = Depends(require_session_user_id)) -> dict:
    del user_id
    return budget_run()
