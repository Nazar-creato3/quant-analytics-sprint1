"""Position audit fields on maneuvers and position_audits table with RLS.

Revision ID: 0034_position_audit
Revises: 0033_application_trial_paywall
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0034_position_audit"
down_revision: Union[str, None] = "0033_application_trial_paywall"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE maneuvers
            ADD COLUMN IF NOT EXISTS exit_reason VARCHAR(20) NULL,
            ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION NULL,
            ADD COLUMN IF NOT EXISTS stop_loss_price DOUBLE PRECISION NULL,
            ADD COLUMN IF NOT EXISTS factor_exposures_at_entry JSONB NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS peak_unrealized_pnl DOUBLE PRECISION NULL,
            ADD COLUMN IF NOT EXISTS signal_generated_price DOUBLE PRECISION NULL,
            ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION NULL,
            ADD COLUMN IF NOT EXISTS regime_at_entry VARCHAR(50) NULL,
            ADD COLUMN IF NOT EXISTS sector_at_entry VARCHAR(80) NULL;

        CREATE INDEX IF NOT EXISTS ix_maneuvers_exit_reason_closed
            ON maneuvers (exit_reason, closed_at)
            WHERE status = 'closed';

        CREATE TABLE IF NOT EXISTS position_audits (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            trade_count INTEGER NOT NULL DEFAULT 0,
            required_count INTEGER NOT NULL DEFAULT 100,
            started_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            report_path TEXT NULL,
            admin_metrics JSONB NOT NULL DEFAULT '{}',
            user_summary JSONB NOT NULL DEFAULT '{}',
            error_message TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS ix_position_audits_user_created
            ON position_audits (user_id, created_at DESC);

        ALTER TABLE position_audits ENABLE ROW LEVEL SECURITY;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = 'position_audits'
                  AND policyname = 'position_audits_user_isolation'
            ) THEN
                CREATE POLICY position_audits_user_isolation ON position_audits
                    FOR ALL
                    USING (user_id = current_setting('app.user_id', true))
                    WITH CHECK (user_id = current_setting('app.user_id', true));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS position_audits_user_isolation ON position_audits;
        ALTER TABLE position_audits DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS position_audits;

        DROP INDEX IF EXISTS ix_maneuvers_exit_reason_closed;

        ALTER TABLE maneuvers
            DROP COLUMN IF EXISTS sector_at_entry,
            DROP COLUMN IF EXISTS regime_at_entry,
            DROP COLUMN IF EXISTS exit_price,
            DROP COLUMN IF EXISTS closed_at,
            DROP COLUMN IF EXISTS signal_generated_price,
            DROP COLUMN IF EXISTS peak_unrealized_pnl,
            DROP COLUMN IF EXISTS factor_exposures_at_entry,
            DROP COLUMN IF EXISTS stop_loss_price,
            DROP COLUMN IF EXISTS entry_price,
            DROP COLUMN IF EXISTS exit_reason;
        """
    )
