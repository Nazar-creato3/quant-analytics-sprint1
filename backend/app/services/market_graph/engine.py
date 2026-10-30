"""MarketGraph read-model engine (Prompt 20)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.market_data import FactorExposureORM, MarketOhlcvORM, SectorMappingORM
from app.services.factor.types import FactorExposureRow, FactorName
from app.services.market_graph.builder import (
    average_intra_sector_correlation,
    build_correlation_edges,
    build_factor_exposure_edges,
    build_sector_membership_edges,
    find_correlated_cluster,
    returns_from_closes,
)
from app.services.market_graph.cache import (
    get_cached_cluster,
    get_cached_sector_context,
    invalidate_market_graph_cache,
    set_cached_cluster,
    set_cached_sector_context,
)
from app.services.market_graph.news_impact_provider import (
    DatabaseNewsImpactEdgeProvider,
    NewsImpactEdgeProvider,
)
from app.services.market_graph.repository import MarketGraphRepository
from app.services.market_graph.types import EdgeType, GraphEdgeRow, SectorContext


@dataclass(frozen=True, slots=True)
class MarketGraphConfig:
    """Runtime parameters for graph rebuild and cache."""

    timeframe: str = "1d"
    lookback_bars: int = 60
    cache_ttl_seconds: int = 300
    min_rebuild_interval_seconds: int = 300
    news_impact_lookback_hours: int = 72


class MarketGraph:
    """Build and query the market relationship graph."""

    def __init__(
        self,
        *,
        config: MarketGraphConfig | None = None,
        repository: MarketGraphRepository | None = None,
        news_impact_provider: NewsImpactEdgeProvider | None = None,
    ) -> None:
        self._config = config or MarketGraphConfig(
            cache_ttl_seconds=settings.MARKET_GRAPH_CACHE_TTL_SECONDS,
            min_rebuild_interval_seconds=settings.MARKET_GRAPH_MIN_REBUILD_INTERVAL_SECONDS,
            lookback_bars=settings.MARKET_GRAPH_CORRELATION_WINDOW,
            news_impact_lookback_hours=settings.MARKET_GRAPH_NEWS_IMPACT_LOOKBACK_HOURS,
        )
        self._repository = repository or MarketGraphRepository()
        self._news_impact_provider = news_impact_provider or DatabaseNewsImpactEdgeProvider(
            lookback_hours=self._config.news_impact_lookback_hours,
        )
        self._last_rebuild_at: datetime | None = None

    def build_from_synthetic(
        self,
        *,
        returns_by_instrument: dict[int, Sequence[float]],
        sector_by_instrument: dict[int, str],
        factor_exposures: Sequence[FactorExposureRow] | None = None,
        updated_at: datetime | None = None,
    ) -> list[GraphEdgeRow]:
        """Pure builder path for unit tests."""
        timestamp = updated_at or datetime.now(timezone.utc)
        edges = build_correlation_edges(returns_by_instrument, updated_at=timestamp)
        edges.extend(build_sector_membership_edges(sector_by_instrument, updated_at=timestamp))
        if factor_exposures:
            edges.extend(build_factor_exposure_edges(factor_exposures, updated_at=timestamp))
        return edges

    async def rebuild(self, session: AsyncSession, *, force: bool = False) -> dict[str, int]:
        """Rebuild graph edges from DB sources and refresh Redis cache."""
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._last_rebuild_at is not None
            and (now - self._last_rebuild_at).total_seconds() < self._config.min_rebuild_interval_seconds
        ):
            return {"skipped": 1}

        sector_rows = await session.execute(select(SectorMappingORM))
        sector_by_instrument = {
            row.instrument_id: row.sector for row in sector_rows.scalars().all()
        }
        instrument_ids = list(sector_by_instrument.keys())
        returns_by_instrument = await self._load_returns(session, instrument_ids)
        latest_exposures = await self._load_latest_factor_exposures(session, instrument_ids)

        timestamp = now
        correlation_edges = build_correlation_edges(returns_by_instrument, updated_at=timestamp)
        sector_edges = build_sector_membership_edges(sector_by_instrument, updated_at=timestamp)
        factor_edges = build_factor_exposure_edges(latest_exposures, updated_at=timestamp)
        news_edges = await self._news_impact_provider.fetch_edges(session)

        counts = {
            EdgeType.CORRELATION.value: await self._repository.replace_edges_of_type(
                session, correlation_edges, edge_type=EdgeType.CORRELATION
            ),
            EdgeType.SECTOR_MEMBERSHIP.value: await self._repository.replace_edges_of_type(
                session, sector_edges, edge_type=EdgeType.SECTOR_MEMBERSHIP
            ),
            EdgeType.FACTOR_EXPOSURE.value: await self._repository.replace_edges_of_type(
                session, factor_edges, edge_type=EdgeType.FACTOR_EXPOSURE
            ),
            EdgeType.NEWS_IMPACT.value: await self._repository.replace_edges_of_type(
                session, news_edges, edge_type=EdgeType.NEWS_IMPACT
            ),
        }
        await invalidate_market_graph_cache()
        self._last_rebuild_at = now
        return counts

    async def get_correlated_cluster(
        self,
        session: AsyncSession,
        instrument_id: int,
        threshold: float,
        *,
        use_cache: bool = True,
    ) -> list[int]:
        """Return instrument IDs in the same correlation cluster above threshold."""
        if use_cache:
            cached = await get_cached_cluster(instrument_id, threshold)
            if cached is not None:
                return cached

        correlation_edges = await self._repository.list_edges(
            session,
            edge_type=EdgeType.CORRELATION,
        )
        cluster = find_correlated_cluster(
            instrument_id,
            correlation_edges,
            threshold=threshold,
        )
        if use_cache:
            await set_cached_cluster(
                instrument_id,
                threshold,
                cluster,
                ttl=self._config.cache_ttl_seconds,
            )
        return cluster

    async def get_sector_context(
        self,
        session: AsyncSession,
        instrument_id: int,
        *,
        use_cache: bool = True,
    ) -> SectorContext | None:
        """Return aggregate sector metrics for an instrument."""
        if use_cache:
            cached = await get_cached_sector_context(instrument_id)
            if cached is not None:
                return SectorContext(
                    instrument_id=int(cached["instrument_id"]),
                    sector=str(cached["sector"]),
                    peer_instrument_ids=tuple(int(value) for value in cached["peer_instrument_ids"]),
                    peer_count=int(cached["peer_count"]),
                    average_intra_sector_correlation=float(cached["average_intra_sector_correlation"]),
                    factor_exposure_summary={
                        str(key): float(value)
                        for key, value in cached["factor_exposure_summary"].items()
                    },
                    updated_at=datetime.fromisoformat(cached["updated_at"])
                    if cached.get("updated_at")
                    else None,
                )

        sector = await self._repository.get_sector_for_instrument(session, instrument_id)
        if sector is None:
            return None

        peers = await self._repository.get_sector_peers(
            session,
            sector=sector,
            exclude_instrument_id=instrument_id,
        )
        all_peer_ids = sorted([instrument_id, *peers])
        correlation_edges = await self._repository.list_edges(
            session,
            edge_type=EdgeType.CORRELATION,
        )
        avg_corr = average_intra_sector_correlation(all_peer_ids, correlation_edges)
        factor_summary = await self._load_factor_summary(session, all_peer_ids)

        context = SectorContext(
            instrument_id=instrument_id,
            sector=sector,
            peer_instrument_ids=tuple(peers),
            peer_count=len(peers),
            average_intra_sector_correlation=avg_corr,
            factor_exposure_summary=factor_summary,
            updated_at=datetime.now(timezone.utc),
        )
        if use_cache:
            await set_cached_sector_context(
                instrument_id,
                {
                    "instrument_id": context.instrument_id,
                    "sector": context.sector,
                    "peer_instrument_ids": list(context.peer_instrument_ids),
                    "peer_count": context.peer_count,
                    "average_intra_sector_correlation": context.average_intra_sector_correlation,
                    "factor_exposure_summary": context.factor_exposure_summary,
                    "updated_at": context.updated_at.isoformat() if context.updated_at else None,
                },
                ttl=self._config.cache_ttl_seconds,
            )
        return context

    async def _load_returns(
        self,
        session: AsyncSession,
        instrument_ids: list[int],
    ) -> dict[int, list[float]]:
        if not instrument_ids:
            return {}
        stmt = (
            select(MarketOhlcvORM)
            .where(
                MarketOhlcvORM.instrument_id.in_(instrument_ids),
                MarketOhlcvORM.timeframe == self._config.timeframe,
            )
            .order_by(MarketOhlcvORM.instrument_id, MarketOhlcvORM.time)
        )
        rows = (await session.execute(stmt)).scalars().all()
        closes_by_instrument: dict[int, list[float]] = {}
        for row in rows:
            if row.close is None:
                continue
            closes_by_instrument.setdefault(row.instrument_id, []).append(float(row.close))

        returns_by_instrument: dict[int, list[float]] = {}
        for instrument_id, closes in closes_by_instrument.items():
            if len(closes) > self._config.lookback_bars:
                closes = closes[-self._config.lookback_bars :]
            returns = returns_from_closes(closes)
            if returns:
                returns_by_instrument[instrument_id] = returns
        return returns_by_instrument

    async def _load_latest_factor_exposures(
        self,
        session: AsyncSession,
        instrument_ids: list[int],
    ) -> list[FactorExposureRow]:
        if not instrument_ids:
            return []
        latest_time_subq = (
            select(
                FactorExposureORM.instrument_id,
                func.max(FactorExposureORM.time).label("max_time"),
            )
            .where(FactorExposureORM.instrument_id.in_(instrument_ids))
            .group_by(FactorExposureORM.instrument_id)
            .subquery()
        )
        stmt = (
            select(FactorExposureORM)
            .join(
                latest_time_subq,
                (FactorExposureORM.instrument_id == latest_time_subq.c.instrument_id)
                & (FactorExposureORM.time == latest_time_subq.c.max_time),
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            FactorExposureRow(
                instrument_id=row.instrument_id,
                time=row.time,
                factor_name=FactorName(row.factor_name),
                beta=float(row.beta),
                r_squared_of_model=float(row.r_squared_of_model),
            )
            for row in rows
        ]

    async def _load_factor_summary(
        self,
        session: AsyncSession,
        instrument_ids: list[int],
    ) -> dict[str, float]:
        exposures = await self._load_latest_factor_exposures(session, instrument_ids)
        if not exposures:
            return {}
        grouped: dict[str, list[float]] = {}
        for row in exposures:
            grouped.setdefault(row.factor_name.value, []).append(row.beta)
        return {
            factor_name: sum(values) / len(values)
            for factor_name, values in grouped.items()
        }
