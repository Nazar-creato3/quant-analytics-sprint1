"""Regulatory data API — SEC filings and FINRA short interest (internal source, client-agnostic)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.services.fundamental_data.factory import get_fundamental_data_provider
from app.services.fundamental_data.models import RegulatoryDataResult
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/regulatory", tags=["regulatory"])


@router.get("/status")
async def regulatory_status(
    _user_id: str = Depends(require_session_user_id),
) -> dict[str, bool]:
    """Lightweight check whether the regulatory data source is enabled."""
    provider = get_fundamental_data_provider()
    return {"enabled": provider.source_enabled}


@router.get("/sec-filings/{ticker}", response_model=RegulatoryDataResult)
async def get_sec_filings(
    ticker: str,
    limit: int = Query(20, ge=1, le=100),
    form_type: Optional[str] = Query(None, max_length=32),
    _user_id: str = Depends(require_session_user_id),
) -> RegulatoryDataResult:
    """Latest SEC filings for a US ticker."""
    return await get_fundamental_data_provider().get_sec_filings(
        ticker,
        limit=limit,
        form_type=form_type,
    )


@router.get("/finra-short-interest/{ticker}", response_model=RegulatoryDataResult)
async def get_finra_short_interest(
    ticker: str,
    limit: int = Query(12, ge=1, le=52),
    _user_id: str = Depends(require_session_user_id),
) -> RegulatoryDataResult:
    """FINRA short interest history for a US ticker."""
    return await get_fundamental_data_provider().get_finra_short_interest(ticker, limit=limit)
