"""Asset-manager desk: report, IPS, promotion, monitor, runbooks."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["platform"])

_PROMOTE_LABEL = "triple_barrier+meta_label"
_PROMOTE_CV = "nested_combinatorial_purged_cv"
_PROMOTE_FAIL_RU = "Не удалось подтвердить выпуск модели. Проверьте данные и повторите."


class IpsIn(BaseModel):
    deploy_cap: float | None = None
    max_risk_pct: float = Field(default=2.0, ge=0.1, le=25.0)
    banned_tickers: list[str] = Field(default_factory=list)
    esg_keywords: list[str] = Field(default_factory=list)
    max_name_frac: float = Field(default=0.10, ge=0.01, le=1.0)


class PromoteIn(BaseModel):
    name: str
    feature_freeze_id: str
    feature_lineage: str = ""
    confirm: bool = False
    n_train: int = 0
    outer_accuracy: float = 0.0
    outer_n: float = 0.0
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 21])
    totp_code: str | None = None
    note: str = ""


def _public_promote_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip recipe/CV internals before returning to the UI (GA16-347)."""
    out = {k: v for k, v in raw.items() if k not in {"model_card", "params", "tags"}}
    card = raw.get("model_card")
    if isinstance(card, dict):
        out["model"] = {
            "name": card.get("name"),
            "version": card.get("version"),
            "promoted": card.get("promoted"),
        }
    signoff = raw.get("signoff")
    if isinstance(signoff, dict):
        out["signoff"] = {
            "reviewer": signoff.get("reviewer"),
            "mfa": signoff.get("mfa"),
        }
    return out


async def _current_user(db: AsyncSession, email: str) -> User | None:
    from app.services.portfolio.user_scope import get_user_by_email

    return await get_user_by_email(db, email)


def _uid(user: User | None, email: str) -> str:
    if user is not None and getattr(user, "id", None):
        return str(user.id)
    return email or "paper"


def _verify_user_totp(user: User | None, code: str | None) -> bool | None:
    if user is None or not getattr(user, "two_factor_enabled", False):
        return None
    if not code or not getattr(user, "two_factor_secret", None):
        return False
    from app.services.two_factor import decrypt_totp_secret, verify_totp

    return bool(verify_totp(decrypt_totp_secret(user.two_factor_secret), code))


@router.get("/desk")
async def platform_desk(
    refresh: bool = False,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.desk import evaluate_platform

    user = await _current_user(db, email)
    return evaluate_platform(user_id=_uid(user, email), refresh_monitor=refresh)


@router.get("/ips")
async def get_ips(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.mandate import load_ips

    user = await _current_user(db, email)
    return load_ips(_uid(user, email)).to_dict()


@router.put("/ips")
async def put_ips(
    body: IpsIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.mandate import IPS, save_ips

    user = await _current_user(db, email)
    cap = body.deploy_cap
    if cap is not None and cap <= 0:
        cap = None
    ips = save_ips(
        IPS(
            user_id=_uid(user, email),
            deploy_cap=cap,
            max_risk_pct=body.max_risk_pct,
            banned_tickers=tuple(body.banned_tickers),
            esg_keywords=tuple(body.esg_keywords),
            max_name_frac=body.max_name_frac,
            updated_at="",
        )
    )
    return ips.to_dict()


@router.get("/report")
async def client_report(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.nightly import run_nightly_platform
    from app.services.platform_desk.reporting import load_latest_client_pack

    user = await _current_user(db, email)
    uid = _uid(user, email)
    pack = load_latest_client_pack(user_id=uid)
    if pack is None:
        pack = run_nightly_platform(user_id=uid).get("report") or {"user_id": uid}
    return pack


@router.get("/monitor")
async def platform_monitor(
    refresh: bool = False,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.monitor import load_snapshot, persist_snapshot, snapshot

    user = await _current_user(db, email)
    uid = _uid(user, email)
    if refresh:
        return persist_snapshot(user_id=uid)
    return load_snapshot(user_id=uid) or {**snapshot(), "user_id": uid}


@router.get("/runbook")
async def platform_runbook(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.runbook import desks

    user = await _current_user(db, email)
    return {"desks": desks(), "user_id": _uid(user, email)}


@router.get("/promotion")
async def promotion_queue(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.platform_desk.promotion import research_queue

    user = await _current_user(db, email)
    uid = _uid(user, email)
    return research_queue(reviewer=email or uid)


@router.post("/promote")
async def platform_promote(
    body: PromoteIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    from app.services.alpha.model_card import build_card
    from app.services.platform_desk.promotion import promote_with_signoff

    user = await _current_user(db, email)
    card = build_card(
        name=body.name,
        metrics={"accuracy": body.outer_accuracy, "outer_accuracy": body.outer_accuracy, "outer_n": body.outer_n},
        n_train=body.n_train,
        feature_lineage=body.feature_lineage,
        feature_freeze_id=body.feature_freeze_id,
        label_recipe=_PROMOTE_LABEL,
        cv_method=_PROMOTE_CV,
        horizons=body.horizons,
        promoted=False,
    )
    try:
        raw = promote_with_signoff(
            card,
            confirm=body.confirm,
            reviewer=email,
            totp_ok=_verify_user_totp(user, body.totp_code),
            note=body.note,
        )
        return _public_promote_result(raw if isinstance(raw, dict) else {"ok": True})
    except ValueError as exc:
        logger.info("platform_promote_refused: %s", exc)
        raise HTTPException(status_code=400, detail=_PROMOTE_FAIL_RU) from exc
