"""Persistence layer for market_graph_edges."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_graph import MarketGraphEdgeORM
from app.services.market_graph.nodes import (
    instrument_node,
    parse_instrument_node,
    parse_sector_node,
    sector_node,
)
from app.services.market_graph.types import EdgeType, GraphEdgeRow


class MarketGraphRepository:
    """Read/write market graph edges."""

    async def replace_edges_of_type(
        self,
        session: AsyncSession,
        edges: list[GraphEdgeRow],
        *,
        edge_type: EdgeType,
    ) -> int:
        await session.execute(
            delete(MarketGraphEdgeORM).where(MarketGraphEdgeORM.edge_type == edge_type.value)
        )
        if not edges:
            await session.commit()
            return 0
        return await self._insert_edges(session, edges)

    async def upsert_edges(self, session: AsyncSession, edges: list[GraphEdgeRow]) -> int:
        if not edges:
            return 0
        return await self._insert_edges(session, edges)

    async def list_edges(
        self,
        session: AsyncSession,
        *,
        edge_type: EdgeType | None = None,
    ) -> list[GraphEdgeRow]:
        stmt = select(MarketGraphEdgeORM)
        if edge_type is not None:
            stmt = stmt.where(MarketGraphEdgeORM.edge_type == edge_type.value)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            GraphEdgeRow(
                from_node=row.from_node,
                to_node=row.to_node,
                edge_type=EdgeType(row.edge_type),
                weight=float(row.weight),
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_sector_for_instrument(
        self,
        session: AsyncSession,
        instrument_id: int,
    ) -> str | None:
        stmt = (
            select(MarketGraphEdgeORM.to_node)
            .where(
                MarketGraphEdgeORM.from_node == instrument_node(instrument_id),
                MarketGraphEdgeORM.edge_type == EdgeType.SECTOR_MEMBERSHIP.value,
            )
            .limit(1)
        )
        node = (await session.execute(stmt)).scalar_one_or_none()
        if node is None:
            return None
        return parse_sector_node(node)

    async def get_sector_peers(
        self,
        session: AsyncSession,
        *,
        sector: str,
        exclude_instrument_id: int | None = None,
    ) -> list[int]:
        stmt = select(MarketGraphEdgeORM.to_node).where(
            MarketGraphEdgeORM.from_node == sector_node(sector),
            MarketGraphEdgeORM.edge_type == EdgeType.SECTOR_MEMBERSHIP.value,
        )
        rows = (await session.execute(stmt)).scalars().all()
        peers: list[int] = []
        for node in rows:
            instrument_id = parse_instrument_node(node)
            if instrument_id is None:
                continue
            if exclude_instrument_id is not None and instrument_id == exclude_instrument_id:
                continue
            peers.append(instrument_id)
        return sorted(peers)

    async def _insert_edges(self, session: AsyncSession, edges: list[GraphEdgeRow]) -> int:
        now = datetime.now(timezone.utc)
        payload = [
            {
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "edge_type": edge.edge_type.value,
                "weight": Decimal(str(round(edge.weight, 8))),
                "updated_at": edge.updated_at or now,
            }
            for edge in edges
        ]
        stmt = insert(MarketGraphEdgeORM).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["from_node", "to_node", "edge_type"],
            set_={
                "weight": stmt.excluded.weight,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
        return len(edges)
