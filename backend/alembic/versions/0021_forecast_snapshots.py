"""Forecast snapshot table for daily Celery refresh.

Revision ID: 0021_forecast_snapshots
Revises: 0020_market_graph_edges
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0021_forecast_snapshots"
down_revision: Union[str, None] = "0020_market_graph_edges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_snapshots (
            id              VARCHAR(36) PRIMARY KEY,
            instrument_id   INTEGER NOT NULL,
            symbol          VARCHAR(32) NOT NULL,
            snapshot_date   TIMESTAMPTZ NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forecast_snapshots_instrument_id
            ON forecast_snapshots (instrument_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forecast_snapshots_symbol_date
            ON forecast_snapshots (symbol, snapshot_date DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS forecast_snapshots")
