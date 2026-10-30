"""Sandbox, personal limits, calendar, digest (Prompt 21). Flags default off."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.digest.service import preview as digest_preview
from app.services.digest.service import set_prefs as digest_prefs
from app.services.instrument_calendar.service import events_for_user, subscribe
from app.services.personal_limits.service import breaches, evaluate_limits, get_limits, set_limits
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user
from app.services.risk_history.service import series as risk_series
from app.services.sandbox.service import compare, list_variants, save_variant, simulate

router = APIRouter(tags=["sandbox-limits"])


class HoldingsIn(BaseModel):
    user_id: str = "demo"
    mode: str = "paper"
    holdings: list[dict] | None = None


class VariantIn(BaseModel):
    user_id: str = "demo"
    name: str
    holdings: list[dict] | None = None
    mode: str = "paper"


class LimitsIn(BaseModel):
    user_id: str = "demo"
    crisis_loss: float | None = None
    concentration: float | None = None
    leverage: float | None = None
    drawdown: float | None = None


class DigestIn(BaseModel):
    user_id: str = "demo"
    cadence: str = "weekly"
    channel: str = "email"


class CalSubIn(BaseModel):
    user_id: str = "demo"
    ticker: str


def _need(flag: str) -> None:
    if not is_enabled(flag):
        raise HTTPException(status_code=404, detail=f"{flag} off")


@router.post("/sandbox/simulate")
def post_simulate(body: HoldingsIn, session_id: str = Depends(require_session_identity)) -> dict:
    _need("qa_sandbox")
    uid = same_user(body.user_id, session_id)
    return simulate(user_id=uid, mode=body.mode, holdings=body.holdings)


@router.post("/sandbox/variants")
def post_variant(body: VariantIn, session_id: str = Depends(require_session_identity)) -> dict:
    _need("qa_sandbox")
    uid = same_user(body.user_id, session_id)
    payload = simulate(user_id=uid, mode=body.mode, holdings=body.holdings)
    return save_variant(user_id=uid, name=body.name, payload=payload)


@router.get("/sandbox/variants")
def get_variants(user_id: str = Depends(require_session_user_id)) -> dict:
    _need("qa_sandbox")
    return compare(user_id=user_id)


@router.get("/personal-limits")
def get_user_limits(user_id: str = Depends(require_session_user_id)) -> dict:
    _need("qa_personal_limits")
    return get_limits(user_id=user_id)


@router.put("/personal-limits")
def put_user_limits(body: LimitsIn, session_id: str = Depends(require_session_identity)) -> dict:
    _need("qa_personal_limits")
    return set_limits(
        user_id=same_user(body.user_id, session_id),
        crisis_loss=body.crisis_loss,
        concentration=body.concentration,
        leverage=body.leverage,
        drawdown=body.drawdown,
    )


@router.post("/personal-limits/check")
def post_check(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    _need("qa_personal_limits")
    out = evaluate_limits(user_id=user_id, mode=mode)
    out["history"] = breaches(user_id=user_id)
    return out


@router.get("/instrument-calendar")
def get_calendar(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    _need("qa_calendar")
    return events_for_user(user_id=user_id, mode=mode)


@router.post("/instrument-calendar/subscribe")
def post_cal_sub(body: CalSubIn, session_id: str = Depends(require_session_identity)) -> dict:
    _need("qa_calendar")
    return subscribe(user_id=same_user(body.user_id, session_id), ticker=body.ticker)


@router.get("/digest")
def get_digest(user_id: str = Depends(require_session_user_id), mode: str = Query("paper")) -> dict:
    _need("qa_digest")
    return digest_preview(user_id=user_id, mode=mode)


@router.post("/digest/prefs")
def post_digest_prefs(body: DigestIn, session_id: str = Depends(require_session_identity)) -> dict:
    _need("qa_digest")
    try:
        return digest_prefs(user_id=same_user(body.user_id, session_id), cadence=body.cadence, channel=body.channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/risk-history")
def get_risk_history(user_id: str = Depends(require_session_user_id)) -> dict:
    if not (is_enabled("qa_digest") or is_enabled("qa_sandbox") or is_enabled("qa_personal_limits")):
        raise HTTPException(status_code=404, detail="risk_history flag off")
    return risk_series(user_id=user_id)
