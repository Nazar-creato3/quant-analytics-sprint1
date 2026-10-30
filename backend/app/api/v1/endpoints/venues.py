"""Venue registry and connect preview (Prompt 06)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id
from app.services.venue_adapters.errors import WithdrawKeyRejected
from app.services.venue_adapters.registry import list_venues
from app.services.venue_adapters.tbank import connect_preview

router = APIRouter(prefix="/venues", tags=["venues"])


class TbankPreviewIn(BaseModel):
    user_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["read"])
    operations: list[dict] = Field(default_factory=list)
    readonly: bool = False
    sandbox: bool = True


@router.get("")
def venues() -> dict:
    if not is_enabled("qa_venue_adapters"):
        raise HTTPException(status_code=404, detail="venue adapters flag off")
    return {
        "venues": [
            {
                "id": v.id,
                "title": v.title,
                "support": v.support,
                "capabilities": sorted(v.capabilities),
                "history_note": v.history_note,
                "reason": v.reason,
            }
            for v in list_venues()
        ]
    }


@router.post("/tbank/preview")
def tbank_preview(
    body: TbankPreviewIn,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_venue_adapters"):
        raise HTTPException(status_code=404, detail="venue adapters flag off")
    try:
        return connect_preview(
            user_id=user_id,
            scopes=body.scopes,
            operations=body.operations,
            readonly=body.readonly,
            sandbox=body.sandbox,
        )
    except WithdrawKeyRejected as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
