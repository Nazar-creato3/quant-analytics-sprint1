"""Extend instruments registry and add sleeves table for domain model.

Revision ID: 0007_domain_core
Revises: 0006_market_data_realtime
Create Date: 2026-07-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007_domain_core"
down_revision: Union[str, None] = "0006_market_data_realtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE instruments
            ADD COLUMN IF NOT EXISTS category TEXT,
            ADD COLUMN IF NOT EXISTS tradable_unit TEXT NOT NULL DEFAULT 'per_share',
            ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sleeves (
            id                      VARCHAR(36) PRIMARY KEY,
            profile_id              VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name                    VARCHAR(100) NOT NULL,
            category                VARCHAR(40) NOT NULL,
            capital_allocation_pct  NUMERIC(5, 2) NOT NULL
                CHECK (capital_allocation_pct >= 0 AND capital_allocation_pct <= 100),
            risk_budget             NUMERIC(18, 6) NOT NULL CHECK (risk_budget >= 0),
            status                  VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_sleeves_profile_id ON sleeves (profile_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sleeves")
    op.execute(
        """
        ALTER TABLE instruments
            DROP COLUMN IF EXISTS metadata,
            DROP COLUMN IF EXISTS tradable_unit,
            DROP COLUMN IF EXISTS category
        """
    )
