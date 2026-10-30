"""Regime Engine history table for classification replay.

Revision ID: 0018_regime_history
Revises: 0017_factor_exposure
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0018_regime_history"
down_revision: Union[str, None] = "0017_factor_exposure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS regime_history (
            id                  SERIAL PRIMARY KEY,
            time                TIMESTAMPTZ NOT NULL,
            scope_type          VARCHAR(20) NOT NULL,
            scope_id            VARCHAR(64) NOT NULL,
            regime_distribution JSONB NOT NULL,
            dominant_regime     VARCHAR(40) NOT NULL,
            confidence          NUMERIC NOT NULL,
            previous_regime     VARCHAR(40),
            features            JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_regime_history_scope_time
            ON regime_history (scope_type, scope_id, time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_regime_history_dominant
            ON regime_history (dominant_regime, time DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regime_history")
