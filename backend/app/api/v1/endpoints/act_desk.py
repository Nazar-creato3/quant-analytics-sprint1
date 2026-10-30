"""Act desk API (D-18-1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.act_desk.service import (
    close_maneuver,
    decide,
    execute,
    export_maneuver_pdf,
    get_profile,
    get_rules,
    journal_for,
    list_maneuvers,
    preview_trade,
    propose,
    save_profile,
    save_rules,
    send,
)
from app.services.maneuver_control.service import aggregate, user_report
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import (
    require_session_identity,
    require_session_user_id,
    same_user,
)

router = APIRouter(prefix="/act", tags=["act"])


class ProfileIn(BaseModel):
    user_id: str = "demo"
    horizon: str
    risk_tolerance: str
    max_position_pct: str
    max_crisis_loss_pct: str
    purpose: str = "учёт капитала"


class RulesIn(BaseModel):
    user_id: str = "demo"
    max_single_weight: str = "0.25"
    max_hhi: str = "0.40"
    max_var_95: str = "0.05"


class DecideIn(BaseModel):
    user_id: str = "demo"
    maneuver_id: str
    action: str
    edits: dict | None = None
    confirm: bool = False
    reject_reason: str | None = None
    reject_note: str = ""
    mode: str = "paper"


class PreviewIn(BaseModel):
    user_id: str = "demo"
    ticker: str
    qty: str
    price: str
    mode: str = "paper"


class ExecuteIn(BaseModel):
    user_id: str = "demo"
    maneuver_id: str
    mode: str = "paper"
    filled_qty: str | None = None


class ManeuverIdIn(BaseModel):
    user_id: str = "demo"
    maneuver_id: str


def _flag() -> None:
    if not is_enabled("qa_act_desk"):
        raise HTTPException(status_code=404, detail="act desk flag off")


@router.get("/profile")
def api_get_profile(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return get_profile(user_id) or {"empty": True}


@router.post("/profile")
def api_save_profile(body: ProfileIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    uid = same_user(body.user_id, session_id)
    payload = body.model_dump()
    payload["user_id"] = uid
    return save_profile(uid, payload)


@router.get("/rules")
def api_get_rules(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return get_rules(user_id)


@router.post("/rules")
def api_save_rules(body: RulesIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    uid = same_user(body.user_id, session_id)
    payload = body.model_dump()
    payload["user_id"] = uid
    return save_rules(uid, payload)


@router.post("/propose")
def api_propose(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper"),
    target_source: str = Query("user"),
    method: str = Query("equal_weight"),
) -> dict:
    _flag()
    return propose(user_id=user_id, mode=mode, target_source=target_source, method=method)


@router.post("/decide")
def api_decide(body: DecideIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return decide(
            user_id=same_user(body.user_id, session_id),
            maneuver_id=body.maneuver_id,
            action=body.action,
            edits=body.edits,
            confirm=body.confirm,
            reject_reason=body.reject_reason,
            reject_note=body.reject_note,
            mode=body.mode,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="maneuver not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview")
def api_preview(body: PreviewIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    return preview_trade(
        user_id=same_user(body.user_id, session_id),
        ticker=body.ticker,
        qty=body.qty,
        price=body.price,
        mode=body.mode,
    )


@router.post("/execute")
def api_execute(body: ExecuteIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return execute(
            user_id=same_user(body.user_id, session_id),
            maneuver_id=body.maneuver_id,
            mode=body.mode,
            filled_qty=body.filled_qty,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/journal")
def api_journal(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return {"items": journal_for(user_id), "source": "act_desk"}


@router.get("/control")
def api_control(user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    if not is_enabled("qa_maneuver_control"):
        return {"status": "off", "items": []}
    return user_report(user_id)


@router.get("/control/stats")
def api_control_stats(_user_id: str = Depends(require_session_user_id)) -> dict:
    _flag()
    return aggregate()


@router.get("/maneuvers")
def api_list_maneuvers(
    user_id: str = Depends(require_session_user_id),
    status: str | None = Query(None),
) -> dict:
    _flag()
    return {"items": list_maneuvers(user_id, status=status), "source": "act_desk"}


@router.post("/send")
def api_send(body: ManeuverIdIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return send(user_id=same_user(body.user_id, session_id), maneuver_id=body.maneuver_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="maneuver not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/close")
def api_close(body: ManeuverIdIn, session_id: str = Depends(require_session_identity)) -> dict:
    _flag()
    try:
        return close_maneuver(user_id=same_user(body.user_id, session_id), maneuver_id=body.maneuver_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="maneuver not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/journal/{maneuver_id}/pdf")
def api_journal_pdf(maneuver_id: str, user_id: str = Depends(require_session_user_id)) -> Response:
    _flag()
    blob = export_maneuver_pdf(user_id, maneuver_id)
    if blob is None:
        raise HTTPException(status_code=404, detail="maneuver not found")
    return Response(content=blob, media_type="application/pdf")
