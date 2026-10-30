"""Read experiment status. Assignment does not accept an address."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.experiments.service import assign, status
from app.services.qa.session_user import require_session_identity

router = APIRouter(prefix="/experiments", tags=["experiments"])


def get_experiment_status() -> dict:
    return status()


def post_experiment_assign(body: dict) -> dict:
    subject = body.get("subject")
    if not isinstance(subject, str):
        subject = ""
    result = assign(subject)
    result.pop("subject_pseudo", None)
    return result


@router.get("/status")
def http_experiment_status(_user_id: str = Depends(require_session_identity)) -> dict:
    return get_experiment_status()


@router.post("/assign")
def http_experiment_assign(
    body: dict | None = None,
    user_id: str = Depends(require_session_identity),
) -> dict:
    payload = dict(body or {})
    payload.pop("subject", None)
    if any(key in payload for key in ("email", "name", "token")):
        return {"status": "rejected"}
    result = assign(user_id)
    result.pop("subject_pseudo", None)
    return result
