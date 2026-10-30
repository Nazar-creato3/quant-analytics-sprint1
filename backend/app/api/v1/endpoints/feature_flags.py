"""Admin/global feature-flag snapshot and toggle (Prompt 01)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.access_deps import require_owner_admin
from app.db.models import User
from app.services.beta_admin.service import LEGAL_LOCKED
from app.services.qa import feature_flags

router = APIRouter(prefix="/ops/feature-flags", tags=["ops"])


class FlagPatch(BaseModel):
    name: str
    enabled: bool
    user_id: str | None = None


def apply_ops_flag_patch(name: str, enabled: bool, user_id: str | None = None) -> dict:
    if name in LEGAL_LOCKED:
        raise HTTPException(status_code=403, detail="нет данных")
    if user_id:
        feature_flags.set_user(name, enabled, user_id)
    else:
        feature_flags.set_global(name, enabled)
    return feature_flags.snapshot()


@router.get("")
async def list_flags(_admin: User = Depends(require_owner_admin)) -> dict:
    return feature_flags.snapshot()


@router.post("")
async def set_flag(body: FlagPatch, _admin: User = Depends(require_owner_admin)) -> dict:
    return apply_ops_flag_patch(body.name, body.enabled, body.user_id)
