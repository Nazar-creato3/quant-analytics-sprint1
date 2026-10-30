"""Add active_locks table for EventRiskLayer TTL news locks.

Revision ID: 0014_active_locks
Revises: 0013_equity_analytics
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0014_active_locks"
down_revision: Union[str, None] = "0013_equity_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS active_locks (
            id                VARCHAR(36) PRIMARY KEY,
            lock_type         VARCHAR(30) NOT NULL,
            instrument_id     INTEGER REFERENCES instruments(id) ON DELETE CASCADE,
            sleeve_id         VARCHAR(36) REFERENCES sleeves(id) ON DELETE CASCADE,
            sector            VARCHAR(80),
            news_shock_score  DOUBLE PRECISION NOT NULL,
            reason            TEXT NOT NULL,
            source_event_id   VARCHAR(36),
            expires_at        TIMESTAMPTZ NOT NULL,
            metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_locks_expires_at ON active_locks (expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_locks_instrument_id ON active_locks (instrument_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_locks_sleeve_id ON active_locks (sleeve_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_locks_sector ON active_locks (sector)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS active_locks")
