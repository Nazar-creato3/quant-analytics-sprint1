"""Add deal_intents table — unit of work for trade execution.

Revision ID: 0009_deal_intent
Revises: 0008_profile_constitution
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0009_deal_intent"
down_revision: Union[str, None] = "0008_profile_constitution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deal_intents (
            id                      VARCHAR(36) PRIMARY KEY,
            instrument_id           INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
            sleeve_id               VARCHAR(36) NOT NULL REFERENCES sleeves(id) ON DELETE RESTRICT,
            direction               VARCHAR(10) NOT NULL,
            target_price            NUMERIC(18, 8),
            entry_reason            TEXT NOT NULL,
            strategy                VARCHAR(30) NOT NULL,
            required_confidence     DOUBLE PRECISION NOT NULL
                CHECK (required_confidence >= 0 AND required_confidence <= 1),
            max_slippage_bps        INTEGER NOT NULL CHECK (max_slippage_bps >= 0),
            max_spread_bps          INTEGER NOT NULL CHECK (max_spread_bps >= 0),
            time_in_force           VARCHAR(10) NOT NULL,
            trigger_type            VARCHAR(20) NOT NULL,
            exit_logic              JSONB NOT NULL DEFAULT '{}'::jsonb,
            hedge_attachment_id     VARCHAR(36) REFERENCES deal_intents(id) ON DELETE SET NULL,
            approval_threshold      NUMERIC(10, 4) NOT NULL CHECK (approval_threshold >= 0),
            risk_tag                VARCHAR(20) NOT NULL,
            news_lock               BOOLEAN NOT NULL DEFAULT false,
            correlation_lock        BOOLEAN NOT NULL DEFAULT false,
            volatility_lock         BOOLEAN NOT NULL DEFAULT false,
            status                  VARCHAR(30) NOT NULL DEFAULT 'draft',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_deal_intents_instrument_id ON deal_intents (instrument_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deal_intents_sleeve_id ON deal_intents (sleeve_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deal_intents_status ON deal_intents (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deal_intents_hedge_attachment_id ON deal_intents (hedge_attachment_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deal_intents")
