"""Pure graph edge builders for MarketGraph."""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from typing import Mapping, Sequence

from app.services.factor.types import FactorExposureRow
from app.services.market_graph.nodes import factor_node, instrument_node, sector_node
from app.services.market_graph.types import EdgeType, GraphEdgeRow
from app.services.quant_math import correlation, log_return


def returns_from_closes(closes: Sequence[float]) -> list[float]:
    """Convert close prices to log-return series aligned with price bars."""
    if len(closes) < 2:
        return []
    returns: list[float] = []
    for index in range(1, len(closes)):
        prev = closes[index - 1]
        curr = closes[index]
        if prev <= 0.0 or curr <= 0.0:
            returns.append(0.0)
        else:
            returns.append(log_return(curr, prev))
    return returns


def build_correlation_edges(
    returns_by_instrument: Mapping[int, Sequence[float]],
    *,
    updated_at: datetime | None = None,
) -> list[GraphEdgeRow]:
    """Build pairwise instrument correlation edges."""
    timestamp = updated_at or datetime.now(timezone.utc)
    edges: list[GraphEdgeRow] = []
    instrument_ids = sorted(returns_by_instrument.keys())
    for left_id, right_id in combinations(instrument_ids, 2):
        left_returns = returns_by_instrument[left_id]
        right_returns = returns_by_instrument[right_id]
        if len(left_returns) < 2 or len(right_returns) < 2:
            continue
        length = min(len(left_returns), len(right_returns))
        weight = correlation(left_returns[-length:], right_returns[-length:])
        left_node = instrument_node(left_id)
        right_node = instrument_node(right_id)
        edges.extend(
            [
                GraphEdgeRow(left_node, right_node, EdgeType.CORRELATION, weight, timestamp),
                GraphEdgeRow(right_node, left_node, EdgeType.CORRELATION, weight, timestamp),
            ]
        )
    return edges


def build_sector_membership_edges(
    sector_by_instrument: Mapping[int, str],
    *,
    updated_at: datetime | None = None,
) -> list[GraphEdgeRow]:
    """Connect instruments to their sector nodes."""
    timestamp = updated_at or datetime.now(timezone.utc)
    edges: list[GraphEdgeRow] = []
    for instrument_id, sector in sector_by_instrument.items():
        instrument = instrument_node(instrument_id)
        sector_id = sector_node(sector)
        edges.extend(
            [
                GraphEdgeRow(instrument, sector_id, EdgeType.SECTOR_MEMBERSHIP, 1.0, timestamp),
                GraphEdgeRow(sector_id, instrument, EdgeType.SECTOR_MEMBERSHIP, 1.0, timestamp),
            ]
        )
    return edges


def build_factor_exposure_edges(
    exposures: Sequence[FactorExposureRow],
    *,
    updated_at: datetime | None = None,
) -> list[GraphEdgeRow]:
    """Connect instruments to factor nodes using latest betas."""
    timestamp = updated_at or datetime.now(timezone.utc)
    edges: list[GraphEdgeRow] = []
    for row in exposures:
        instrument = instrument_node(row.instrument_id)
        factor = factor_node(row.factor_name.value)
        edges.extend(
            [
                GraphEdgeRow(instrument, factor, EdgeType.FACTOR_EXPOSURE, row.beta, timestamp),
                GraphEdgeRow(factor, instrument, EdgeType.FACTOR_EXPOSURE, row.beta, timestamp),
            ]
        )
    return edges


def find_correlated_cluster(
    seed_instrument_id: int,
    correlation_edges: Sequence[GraphEdgeRow],
    *,
    threshold: float,
) -> list[int]:
    """Return instrument IDs connected to seed via |correlation| >= threshold."""
    seed_node = instrument_node(seed_instrument_id)
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for edge in correlation_edges:
        if edge.edge_type != EdgeType.CORRELATION:
            continue
        adjacency.setdefault(edge.from_node, []).append((edge.to_node, edge.weight))

    visited: set[str] = {seed_node}
    queue: list[str] = [seed_node]
    while queue:
        current = queue.pop(0)
        for neighbor, weight in adjacency.get(current, []):
            if abs(weight) < threshold:
                continue
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)

    cluster: list[int] = []
    for node_id in sorted(visited):
        instrument_id = _instrument_id_from_node(node_id)
        if instrument_id is not None:
            cluster.append(instrument_id)
    return cluster


def average_intra_sector_correlation(
    peer_ids: Sequence[int],
    correlation_edges: Sequence[GraphEdgeRow],
) -> float:
    """Average absolute pairwise correlation among sector peers."""
    if len(peer_ids) < 2:
        return 0.0
    lookup: dict[tuple[int, int], float] = {}
    for edge in correlation_edges:
        if edge.edge_type != EdgeType.CORRELATION:
            continue
        left_id = _instrument_id_from_node(edge.from_node)
        right_id = _instrument_id_from_node(edge.to_node)
        if left_id is None or right_id is None:
            continue
        if left_id > right_id:
            left_id, right_id = right_id, left_id
        lookup[(left_id, right_id)] = edge.weight

    values: list[float] = []
    for left_id, right_id in combinations(sorted(peer_ids), 2):
        weight = lookup.get((left_id, right_id))
        if weight is not None:
            values.append(abs(weight))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _instrument_id_from_node(node_id: str) -> int | None:
    prefix = "instrument:"
    if not node_id.startswith(prefix):
        return None
    try:
        return int(node_id[len(prefix) :])
    except ValueError:
        return None
