"""Pydantic schemas for Macro Registry API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MacroSourceCreate(BaseModel):
    source_id: str
    category: str
    symbol: str
    endpoint: str
    refresh_interval: str = "0 8 * * *"
    priority: int = 100
    is_free: bool = True
    fallback_source: Optional[str] = None
    transformer: str
    is_active: bool = True


class MacroSourceUpdate(BaseModel):
    category: Optional[str] = None
    symbol: Optional[str] = None
    endpoint: Optional[str] = None
    refresh_interval: Optional[str] = None
    priority: Optional[int] = None
    is_free: Optional[bool] = None
    fallback_source: Optional[str] = None
    transformer: Optional[str] = None
    is_active: Optional[bool] = None


class MacroSourceOut(BaseModel):
    source_id: str
    category: str
    symbol: str
    endpoint: str
    refresh_interval: str
    priority: int
    is_free: bool
    fallback_source: Optional[str] = None
    transformer: str
    is_active: bool
    last_successful_refresh: Optional[datetime] = None
    reliability_score: float = 1.0

    model_config = {"from_attributes": True}


class MacroSeriesOut(BaseModel):
    instrument: str
    value: float
    unit: str
    quality_flag: str
    confidence: float
    release_time: datetime
    observation_time: datetime
    period: str
    revision: int
    source_id: str


class MacroReportOut(BaseModel):
    as_of: datetime
    mode: str
    report: dict[str, Any]
    markdown: Optional[str] = None
    html: Optional[str] = None


class MacroBlockOut(BaseModel):
    """Macro block for forecast API."""
    indicators: dict[str, float] = Field(default_factory=dict)
    report_mode: str = "daily"
    missing_resources: list[str] = Field(default_factory=list)
    upcoming_releases: list[dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[datetime] = None


class MacroHealthOut(BaseModel):
    status: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    last_refresh: dict[str, str] = Field(default_factory=dict)
    quality_gate_failures: dict[str, int] = Field(default_factory=dict)
    queue_lag_seconds: dict[str, float] = Field(default_factory=dict)
    reliability_scores: dict[str, float] = Field(default_factory=dict)
