"""Asset Cockpit aggregate API (Prompt 9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.schemas.cockpit import AssetCockpitOut
from app.services.cockpit.service import AssetCockpitService

router = APIRouter(prefix="/cockpit", tags=["cockpit"])
_service = AssetCockpitService()


@router.get("/{symbol}", response_model=AssetCockpitOut)
async def get_asset_cockpit(
    symbol: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> AssetCockpitOut:
    """Aggregate read model for the Asset Cockpit UI."""
    return await _service.build(db, symbol)
