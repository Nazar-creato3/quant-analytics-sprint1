"""Pydantic models for terminal platform market / macro / news payloads."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class OHLCV(BaseModel):
    """Normalized OHLCV bar."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Optional[Decimal] = None
    provider: str
    currency: Optional[str] = None
    exchange: Optional[str] = None


class Quote(BaseModel):
    """Last trade / top-of-book quote."""

    symbol: str
    price: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    timestamp: datetime
    provider: str
    currency: Optional[str] = None
    exchange: Optional[str] = None
    change_pct: Optional[float] = None


class MacroSeries(BaseModel):
    """Macro time series (rates, CPI, GDP, etc.)."""

    series_id: str
    name: str
    description: Optional[str] = None
    country: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    values: list[dict[str, Any]] = Field(default_factory=list)
    provider: str
    source_url: Optional[str] = None


class Fundamentals(BaseModel):
    """Company fundamentals snapshot."""

    symbol: str
    company_name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    eps: Optional[Decimal] = None
    revenue: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    provider: str
    as_of_date: Optional[date] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None


class NewsItem(BaseModel):
    """Headline-level news item (no full article republication)."""

    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    source: str
    url: str
    published_at: datetime
    symbols: Optional[list[str]] = None
    sentiment: Optional[str] = None
    provider: str


class CalendarEvent(BaseModel):
    """Economic calendar release (FMP / free-path normalized)."""

    id: str
    title: str
    when: datetime
    region: Optional[str] = None
    importance: Optional[str] = None  # low | medium | high
    expected: Optional[str] = None
    actual: Optional[str] = None
    previous: Optional[str] = None
    provider: str = "fmp"
    currency: Optional[str] = None


class DataQuality(BaseModel):
    """Optional quality metadata attached to a fetch."""

    completeness: float = Field(..., ge=0, le=1)
    freshness_minutes: Optional[int] = Field(default=None, ge=0)
    issues: list[str] = Field(default_factory=list)


class FetchResult(BaseModel):
    """Uniform result wrapper for every provider call."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    provider: str
    duration_ms: float = 0.0
    quality: Optional[DataQuality] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    from_cache: bool = False


class ProviderHealth(BaseModel):
    """Health snapshot for one registered provider."""

    name: str
    status: str
    available: bool
    last_error: Optional[str] = None
    circuit_state: Optional[str] = None
    supported_data_types: list[str] = Field(default_factory=list)
    requires_api_key: bool = False
    api_key_configured: bool = False
