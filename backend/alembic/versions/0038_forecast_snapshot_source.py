"""Add source column to forecast_snapshots (live vs backfill).

Revision ID: 0038_forecast_snapshot_source
Revises: 0037_snapshot_resolutions
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0038_forecast_snapshot_source"
down_revision: Union[str, None] = "0037_snapshot_resolutions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE forecast_snapshots
            ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'live'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forecast_snapshots_symbol_date_source
            ON forecast_snapshots (symbol, snapshot_date DESC, source)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_forecast_snapshots_symbol_date_source")
    op.execute("ALTER TABLE forecast_snapshots DROP COLUMN IF EXISTS source")
