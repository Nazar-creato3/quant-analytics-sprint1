"""Market graph edges read-model for correlation clusters (Prompt 20).

Revision ID: 0020_market_graph_edges
Revises: 0019_news_impact_history
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0020_market_graph_edges"
down_revision: Union[str, None] = "0019_news_impact_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market_graph_edges (
            from_node       TEXT NOT NULL,
            to_node         TEXT NOT NULL,
            edge_type       TEXT NOT NULL,
            weight          NUMERIC NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (from_node, to_node, edge_type)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_graph_edges_from_type
            ON market_graph_edges (from_node, edge_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_graph_edges_to_type
            ON market_graph_edges (to_node, edge_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_graph_edges_type_weight
            ON market_graph_edges (edge_type, weight DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_graph_edges")
