"""Unified bots catalog for grid / dca / momentum.

Revision ID: 0048_unified_bots
Revises: 0047_portfolio_risk_analytics
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0048_unified_bots"
down_revision: Union[str, None] = "0047_portfolio_risk_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bots (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
            created_by VARCHAR(320) NOT NULL,
            bot_type VARCHAR(16) NOT NULL,
            symbol VARCHAR(24) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            params JSONB NOT NULL DEFAULT '{}',
            total_trades INTEGER NOT NULL DEFAULT 0,
            pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
            balance_allocated DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS ix_bots_created_by ON bots (created_by);
        CREATE INDEX IF NOT EXISTS ix_bots_user_id ON bots (user_id);
        CREATE INDEX IF NOT EXISTS ix_bots_bot_type ON bots (bot_type);
        CREATE INDEX IF NOT EXISTS ix_bots_created_by_type ON bots (created_by, bot_type);

        ALTER TABLE bots ENABLE ROW LEVEL SECURITY;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = 'bots'
                  AND policyname = 'bots_user_isolation'
            ) THEN
                CREATE POLICY bots_user_isolation
                    ON bots
                    FOR ALL
                    USING (
                        user_id = current_setting('app.user_id', true)
                        OR created_by = current_setting('app.user_email', true)
                    )
                    WITH CHECK (
                        user_id = current_setting('app.user_id', true)
                        OR created_by = current_setting('app.user_email', true)
                    );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS bots_user_isolation ON bots;
        ALTER TABLE bots DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS bots;
        """
    )
