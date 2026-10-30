"""Beta admin reads. Posted secrets are ignored."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.beta_admin.service import analyst_snapshot, list_users, system_state
from app.services.qa.session_user import require_session_identity

router = APIRouter(prefix="/beta-admin", tags=["beta-admin"])
_MISSING = "нет данных"


def _clean(body: dict) -> dict[str, str] | None:
    if any(key in body for key in ("email", "token", "secret", "password")):
        return {"status": "rejected", "reason": _MISSING}
    return None


def get_beta_health(actor_id: str) -> dict:
    return system_state(actor_id)


def post_beta_users(body: dict) -> dict:
    blocked = _clean(body)
    if blocked:
        return blocked
    actor = body.get("actor_id")
    return list_users(actor if isinstance(actor, str) else "")


def post_beta_snapshot(body: dict) -> dict:
    blocked = _clean(body)
    if blocked:
        return blocked
    actor = body.get("actor_id")
    return analyst_snapshot(actor if isinstance(actor, str) else "")


@router.get("/health")
def http_beta_health(user_id: str = Depends(require_session_identity)) -> dict:
    return get_beta_health(user_id)


@router.post("/users")
def http_beta_users(
    body: dict | None = None,
    user_id: str = Depends(require_session_identity),
) -> dict:
    payload = dict(body or {})
    blocked = _clean(payload)
    if blocked:
        return blocked
    return list_users(user_id)


@router.post("/snapshot")
def http_beta_snapshot(
    body: dict | None = None,
    user_id: str = Depends(require_session_identity),
) -> dict:
    payload = dict(body or {})
    blocked = _clean(payload)
    if blocked:
        return blocked
    return analyst_snapshot(user_id)
