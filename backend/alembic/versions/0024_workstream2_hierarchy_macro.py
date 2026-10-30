"""Workstream 2: hierarchy calibration history + macro reliability score.

Revision ID: 0024_workstream2
Revises: 0023_origination
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_workstream2"
down_revision: Union[str, None] = "0023_origination"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hierarchy_calibration_history (
            id SERIAL PRIMARY KEY,
            run_at TIMESTAMPTZ NOT NULL,
            instrument_id INTEGER NOT NULL,
            calibration_error DOUBLE PRECISION NOT NULL,
            brier_score DOUBLE PRECISION NOT NULL,
            total_points INTEGER NOT NULL,
            period_days INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hierarchy_calibration_history_run_at
            ON hierarchy_calibration_history (run_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hierarchy_calibration_history_instrument
            ON hierarchy_calibration_history (instrument_id, run_at DESC)
        """
    )
    op.execute(
        """
        ALTER TABLE macro_source_registry
        ADD COLUMN IF NOT EXISTS reliability_score DOUBLE PRECISION NOT NULL DEFAULT 1.0
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE macro_source_registry DROP COLUMN IF EXISTS reliability_score")
    op.execute("DROP TABLE IF EXISTS hierarchy_calibration_history")
