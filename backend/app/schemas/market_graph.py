"""Market graph API schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CorrelatedClusterOut(BaseModel):
    instrument_id: int
    threshold: float
    cluster_instrument_ids: list[int] = Field(default_factory=list)


class SectorContextOut(BaseModel):
    instrument_id: int
    sector: str
    peer_instrument_ids: list[int] = Field(default_factory=list)
    peer_count: int
    average_intra_sector_correlation: float
    factor_exposure_summary: dict[str, float] = Field(default_factory=dict)
    updated_at: datetime | None = None


class MarketGraphRebuildOut(BaseModel):
    counts: dict[str, int]
