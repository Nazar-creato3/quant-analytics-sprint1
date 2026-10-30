"""News impact edge provider interface for MarketGraph."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.news_impact import NewsImpactHistoryORM
from app.services.market_graph.nodes import instrument_node, news_node
from app.services.market_graph.types import EdgeType, GraphEdgeRow


class NewsImpactEdgeProvider(Protocol):
    """Interface for wiring news-event impact edges into the market graph."""

    async def fetch_edges(self, session: AsyncSession) -> list[GraphEdgeRow]:
        """Return news -> instrument impact edges."""


class DatabaseNewsImpactEdgeProvider:
    """Load recent news impact predictions from news_impact_history."""

    def __init__(self, *, lookback_hours: int = 72) -> None:
        self._lookback_hours = lookback_hours

    async def fetch_edges(self, session: AsyncSession) -> list[GraphEdgeRow]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._lookback_hours)
        stmt = (
            select(NewsImpactHistoryORM)
            .where(
                NewsImpactHistoryORM.predicted_at >= cutoff,
                NewsImpactHistoryORM.instrument_id.is_not(None),
            )
            .order_by(NewsImpactHistoryORM.predicted_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        edges: list[GraphEdgeRow] = []
        for row in rows:
            if row.instrument_id is None or row.news_id is None:
                continue
            probability = row.posterior_probability or row.predicted_probability
            news = news_node(str(row.news_id))
            instrument = instrument_node(row.instrument_id)
            timestamp = row.predicted_at
            edges.extend(
                [
                    GraphEdgeRow(news, instrument, EdgeType.NEWS_IMPACT, float(probability), timestamp),
                    GraphEdgeRow(instrument, news, EdgeType.NEWS_IMPACT, float(probability), timestamp),
                ]
            )
        return edges


class StubNewsImpactEdgeProvider:
    """No-op provider when news impact edges are not yet required."""

    async def fetch_edges(self, session: AsyncSession) -> list[GraphEdgeRow]:
        return []
