"""Support intake. A posted address is rejected."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.qa.session_user import require_session_user_id
from app.services.support_desk.service import known_issues, report

router = APIRouter(prefix="/support", tags=["support"])
_MISSING = "нет данных"


@router.get("/status")
def get_support_status(_user_id: str = Depends(require_session_user_id)) -> dict:
    return {"known_issues": known_issues()}


def _cut(value: object, limit: int) -> str:
    return str(value or "")[:limit]


@router.post("/report")
async def post_support_report_route(body: dict, request: Request) -> dict:
    # Open to signed-out visitors: cap the rate per address (fields are capped below).
    from app.core.client_ip import get_client_ip
    from app.utils.cache import rate_limit_check

    allowed, _ = await rate_limit_check(f"support_report:{get_client_ip(request) or 'na'}", 10, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="Слишком много обращений. Повторите позже.")
    return post_support_report(body)


def post_support_report(body: dict) -> dict:
    if any(key in body for key in ("email", "token", "secret")):
        return {"status": "rejected", "reason": _MISSING}
    errors = body.get("errors")
    if not isinstance(errors, list):
        errors = []
    return report(
        page=_cut(body.get("page"), 300),
        version=_cut(body.get("version"), 64),
        request_id=_cut(body.get("request_id"), 64),
        errors=[_cut(item, 500) for item in errors[:20]],
        description=_cut(body.get("description"), 4000),
        screenshot_consent=body.get("screenshot_consent") is True,
        screenshot=_cut(body.get("screenshot"), 100_000),
    )
