"""Normalized regulatory data models — no vendor-specific fields exposed to clients."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SecFiling(BaseModel):
    symbol: str = ""
    form_type: str = ""
    filing_date: Optional[str] = None
    accepted_date: Optional[str] = None
    link: Optional[str] = None
    cik: Optional[str] = None


class FinraShortInterestRecord(BaseModel):
    symbol: str = ""
    settlement_date: Optional[str] = None
    current_short_position: Optional[float] = None
    previous_short_position: Optional[float] = None
    days_to_cover: Optional[float] = None
    avg_daily_share_volume: Optional[float] = None


class RegulatoryDataResult(BaseModel):
    """Unified response for SEC/FINRA endpoints — mirrors terminal FetchResult shape."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    source_enabled: bool = True
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
