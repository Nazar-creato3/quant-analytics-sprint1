"""Tests for Prompt 20 MarketGraph."""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.factor.types import FactorExposureRow, FactorName
from app.services.market_graph import MarketGraph, StubNewsImpactEdgeProvider
from app.services.market_graph.builder import (
    build_correlation_edges,
    build_sector_membership_edges,
    find_correlated_cluster,
)
from app.services.market_graph.types import EdgeType, GraphEdgeRow


def _synthetic_returns(base: float, drift: float, noise: float, count: int) -> list[float]:
    return [base + drift * index + noise * math.sin(index * 0.5) for index in range(count)]


def _aligned_trend(count: int, *, start: float, step: float) -> list[float]:
    return [start + step * index for index in range(count)]


def _inverse_trend(count: int, *, start: float, step: float) -> list[float]:
    return [start - step * index for index in range(count)]


def _noisy_returns(count: int, *, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, 0.01) for _ in range(count)]


class TestMarketGraphBuilder:
    def test_builds_correlation_edges_for_synthetic_instruments(self):
        returns = {
            1: _aligned_trend(30, start=0.01, step=0.001),
            2: _aligned_trend(30, start=0.012, step=0.0011),
            3: _inverse_trend(30, start=0.2, step=0.002),
        }
        edges = build_correlation_edges(returns)
        correlation_pairs = {
            (edge.from_node, edge.to_node): edge.weight
            for edge in edges
            if edge.edge_type == EdgeType.CORRELATION
        }
        assert correlation_pairs[("instrument:1", "instrument:2")] > 0.9
        assert correlation_pairs[("instrument:1", "instrument:3")] < 0.5

    def test_builds_sector_membership_edges(self):
        edges = build_sector_membership_edges({1: "tech", 2: "tech", 3: "energy"})
        membership = {
            (edge.from_node, edge.to_node)
            for edge in edges
            if edge.edge_type == EdgeType.SECTOR_MEMBERSHIP
        }
        assert ("instrument:1", "sector:tech") in membership
        assert ("sector:tech", "instrument:2") in membership
        assert ("instrument:3", "sector:energy") in membership

    def test_find_correlated_cluster_respects_threshold(self):
        returns = {
            1: _aligned_trend(30, start=0.01, step=0.001),
            2: _aligned_trend(30, start=0.012, step=0.0011),
            3: _noisy_returns(30, seed=17),
        }
        edges = build_correlation_edges(returns)
        high_threshold_cluster = find_correlated_cluster(1, edges, threshold=0.8)
        low_threshold_cluster = find_correlated_cluster(1, edges, threshold=0.0)

        assert high_threshold_cluster == [1, 2]
        assert set(low_threshold_cluster) == {1, 2, 3}

    def test_synthetic_graph_build_includes_factor_edges(self):
        graph = MarketGraph(news_impact_provider=StubNewsImpactEdgeProvider())
        exposures = [
            FactorExposureRow(
                instrument_id=1,
                time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                factor_name=FactorName.MARKET_BETA,
                beta=0.8,
                r_squared_of_model=0.7,
            )
        ]
        edges = graph.build_from_synthetic(
            returns_by_instrument={
                1: _synthetic_returns(0.01, 0.001, 0.0001, 20),
                2: _synthetic_returns(0.012, 0.0011, 0.0001, 20),
            },
            sector_by_instrument={1: "tech", 2: "tech"},
            factor_exposures=exposures,
        )
        edge_types = {edge.edge_type for edge in edges}
        assert EdgeType.CORRELATION in edge_types
        assert EdgeType.SECTOR_MEMBERSHIP in edge_types
        assert EdgeType.FACTOR_EXPOSURE in edge_types


class TestMarketGraphQueries:
    @pytest.mark.asyncio
    async def test_get_correlated_cluster_from_persisted_edges(self):
        graph = MarketGraph(news_impact_provider=StubNewsImpactEdgeProvider())
        edges = build_correlation_edges(
            {
                10: _synthetic_returns(0.01, 0.001, 0.0001, 25),
                11: _synthetic_returns(0.012, 0.0011, 0.0001, 25),
                12: _synthetic_returns(-0.02, 0.0002, 0.002, 25),
            }
        )
        repository = graph._repository
        repository.list_edges = AsyncMock(return_value=edges)

        with patch(
            "app.services.market_graph.engine.get_cached_cluster",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.market_graph.engine.set_cached_cluster",
            new=AsyncMock(),
        ):
            cluster = await graph.get_correlated_cluster(
                session=AsyncMock(),
                instrument_id=10,
                threshold=0.8,
            )
        assert cluster == [10, 11]

    @pytest.mark.asyncio
    async def test_get_sector_context_aggregates_peers(self):
        graph = MarketGraph(news_impact_provider=StubNewsImpactEdgeProvider())
        correlation_edges = build_correlation_edges(
            {
                20: _synthetic_returns(0.01, 0.001, 0.0001, 25),
                21: _synthetic_returns(0.012, 0.0011, 0.0001, 25),
                22: _synthetic_returns(0.011, 0.00105, 0.0001, 25),
            }
        )
        repository = graph._repository
        repository.get_sector_for_instrument = AsyncMock(return_value="tech")
        repository.get_sector_peers = AsyncMock(return_value=[21, 22])
        repository.list_edges = AsyncMock(return_value=correlation_edges)
        graph._load_factor_summary = AsyncMock(
            return_value={"market_beta": 0.75, "sector_factor": 0.4}
        )

        with patch(
            "app.services.market_graph.engine.get_cached_sector_context",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.market_graph.engine.set_cached_sector_context",
            new=AsyncMock(),
        ):
            context = await graph.get_sector_context(
                session=AsyncMock(),
                instrument_id=20,
            )

        assert context is not None
        assert context.sector == "tech"
        assert context.peer_instrument_ids == (21, 22)
        assert context.peer_count == 2
        assert context.average_intra_sector_correlation > 0.8
        assert context.factor_exposure_summary["market_beta"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_rebuild_skips_when_called_too_soon(self):
        graph = MarketGraph(news_impact_provider=StubNewsImpactEdgeProvider())
        graph._last_rebuild_at = datetime.now(timezone.utc)
        counts = await graph.rebuild(AsyncMock(), force=False)
        assert counts == {"skipped": 1}
