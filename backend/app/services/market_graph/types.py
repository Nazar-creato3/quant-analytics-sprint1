"""Market graph types for Prompt 20."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NodeKind(StrEnum):
    """Supported node kinds in the market graph."""

    INSTRUMENT = "instrument"
    SECTOR = "sector"
    MACRO = "macro"
    FACTOR = "factor"
    NEWS = "news"


class EdgeType(StrEnum):
    """Supported edge kinds in the market graph."""

    CORRELATION = "correlation"
    SECTOR_MEMBERSHIP = "sector_membership"
    FACTOR_EXPOSURE = "factor_exposure"
    NEWS_IMPACT = "news_impact"


@dataclass(frozen=True, slots=True)
class GraphEdgeRow:
    """Single edge to persist or query."""

    from_node: str
    to_node: str
    edge_type: EdgeType
    weight: float
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SectorContext:
    """Aggregate sector metrics for an instrument."""

    instrument_id: int
    sector: str
    peer_instrument_ids: tuple[int, ...]
    peer_count: int
    average_intra_sector_correlation: float
    factor_exposure_summary: dict[str, float]
    updated_at: datetime | None = None
