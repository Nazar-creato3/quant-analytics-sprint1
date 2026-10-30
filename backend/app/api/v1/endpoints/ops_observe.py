"""Operations snapshot and runbook drills. Collector may be absent."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.access_deps import require_ops_read
from app.db.models import User
from app.services.ops_observe.service import admin_view, drill
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/ops/observe", tags=["ops-observe"])


def _client_safe_observe(view: dict[str, Any]) -> dict[str, Any]:
    """Drop flag names and OTEL internals from the HTTP surface (GA16-351)."""
    out = {k: v for k, v in view.items() if k not in {"live", "partners", "otel"}}
    return out


@router.get("")
async def get_ops_observe(
    _: User = Depends(require_ops_read),
    user_id: str = Depends(require_session_user_id),
) -> dict:
    del user_id
    return _client_safe_observe(admin_view())


@router.post("/drill/{name}")
async def post_ops_drill(
    name: str,
    _: User = Depends(require_ops_read),
    user_id: str = Depends(require_session_user_id),
) -> dict:
    del user_id
    try:
        return drill(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="нет данных") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="нет данных") from exc
