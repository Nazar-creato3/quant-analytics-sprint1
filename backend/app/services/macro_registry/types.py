"""Shared types for Macro Registry pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MacroCategory(str, Enum):
    RATE = "rate"
    INFLATION = "inflation"
    FX = "fx"
    ENERGY = "energy"
    COMMODITY = "commodity"
    CREDIT = "credit"
    VOLATILITY_INDEX = "volatility_index"
    EMPLOYMENT = "employment"
    CALENDAR = "calendar"


class QualityFlag(str, Enum):
    OK = "ok"
    SUSPECT = "suspect"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class RawResponse:
    """HTTP response from a macro source before transformation."""

    source_id: str
    payload: str
    content_type: str
    http_status: int
    fetched_at: datetime
    payload_hash: str = ""


@dataclass(frozen=True, slots=True)
class InternalObservation:
    """Adapter output ready for normalization layer."""

    instrument: str
    value: float
    currency: str | None
    unit: str
    release_time: datetime
    observation_time: datetime
    period: str
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    """Post-transformer observation before quality gate."""

    instrument: str
    source_id: str
    value: float
    currency: str | None
    unit: str
    release_time: datetime
    observation_time: datetime
    period: str
    revision: int
    confidence: float
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """Upcoming release from MacroCalendarAdapter."""

    instrument: str
    expected_release_time: datetime
    period_covered: str | None
    source_id: str
    consensus_estimate: float | None = None


@dataclass(frozen=True, slots=True)
class MacroSourceConfig:
    """Runtime view of macro_source_registry row."""

    source_id: str
    category: str
    symbol: str
    endpoint: str
    refresh_interval: str
    priority: int
    is_free: bool
    fallback_source: str | None
    transformer: str
    is_active: bool = True
