"""Append-only forecast snapshot resolution outcomes.

Revision ID: 0037_snapshot_resolutions
Revises: 0036_email_account_recovery
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0037_snapshot_resolutions"
down_revision: Union[str, None] = "0036_email_account_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_snapshot_resolutions (
            id                  VARCHAR(36) PRIMARY KEY,
            snapshot_id         VARCHAR(36) NOT NULL UNIQUE,
            symbol              VARCHAR(32) NOT NULL,
            snapshot_date       TIMESTAMPTZ NOT NULL,
            horizon_days        INTEGER NOT NULL,
            predicted_direction INTEGER NOT NULL,
            realized_return     DOUBLE PRECISION NOT NULL,
            direction_hit       BOOLEAN NOT NULL DEFAULT FALSE,
            resolved_at         TIMESTAMPTZ NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forecast_resolutions_symbol_resolved
            ON forecast_snapshot_resolutions (symbol, resolved_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forecast_snapshot_resolutions_snapshot_id
            ON forecast_snapshot_resolutions (snapshot_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS forecast_snapshot_resolutions")
