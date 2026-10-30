"""Public anonymized track record endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.track_record.service import TrackRecordService
from app.services.track_record.types import PublicTrackRecordSummary

router = APIRouter(prefix="/track-record", tags=["track-record"])


@router.get("/public")
async def get_public_track_record() -> dict[str, object]:
    """Public aggregate validation metrics — no authentication required."""
    summary: PublicTrackRecordSummary = TrackRecordService().get_public_summary()
    return summary.to_dict()
