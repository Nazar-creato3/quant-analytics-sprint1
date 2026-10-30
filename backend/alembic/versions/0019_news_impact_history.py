"""News impact history table for Prompt 24 feedback loop.

Revision ID: 0019_news_impact_history
Revises: 0018_regime_history
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0019_news_impact_history"
down_revision: Union[str, None] = "0018_regime_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS news_impact_history (
            id                      SERIAL PRIMARY KEY,
            news_id                 VARCHAR(36),
            instrument_id           INTEGER REFERENCES instruments(id) ON DELETE SET NULL,
            sector                  TEXT,
            topic_tags              TEXT[] NOT NULL DEFAULT '{}',
            predicted_probability   DOUBLE PRECISION NOT NULL,
            predicted_at            TIMESTAMPTZ NOT NULL,
            daily_volatility        DOUBLE PRECISION,
            sigma_threshold         DOUBLE PRECISION NOT NULL DEFAULT 2.0,
            actual_move_sigma       DOUBLE PRECISION,
            actual_move_pct         DOUBLE PRECISION,
            strong_move             BOOLEAN,
            feedback_at             TIMESTAMPTZ,
            feedback_horizon_hours  INTEGER,
            posterior_probability   DOUBLE PRECISION,
            metadata                JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_impact_history_instrument_predicted
            ON news_impact_history (instrument_id, predicted_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_impact_history_tags
            ON news_impact_history USING GIN (topic_tags)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_impact_history_pending_feedback
            ON news_impact_history (predicted_at)
            WHERE feedback_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS news_impact_history")
