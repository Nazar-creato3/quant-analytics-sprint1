"""Portfolio risk analytics snapshots (VaR / factor / stress).

Revision ID: 0047_portfolio_risk_analytics
Revises: 0046_order_execution_options
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0047_portfolio_risk_analytics"
down_revision: Union[str, None] = "0046_order_execution_options"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            lookback_start DATE NOT NULL,
            lookback_end DATE NOT NULL,
            lookback_days INTEGER NOT NULL,
            var_method VARCHAR(40) NOT NULL DEFAULT 'historical_simulation',
            benchmark_symbol VARCHAR(20) NOT NULL DEFAULT 'SPY',
            var_95 DOUBLE PRECISION NULL,
            var_99 DOUBLE PRECISION NULL,
            expected_shortfall_95 DOUBLE PRECISION NULL,
            var_95_usd DOUBLE PRECISION NULL,
            var_99_usd DOUBLE PRECISION NULL,
            expected_shortfall_95_usd DOUBLE PRECISION NULL,
            alpha DOUBLE PRECISION NULL,
            beta DOUBLE PRECISION NULL,
            r_squared DOUBLE PRECISION NULL,
            avg_pairwise_correlation DOUBLE PRECISION NULL,
            concentration_share DOUBLE PRECISION NULL,
            insufficient_data BOOLEAN NOT NULL DEFAULT FALSE,
            holdings JSONB NOT NULL DEFAULT '[]',
            sector_weights JSONB NOT NULL DEFAULT '{}',
            correlation_matrix JSONB NOT NULL DEFAULT '{}',
            methodology JSONB NOT NULL DEFAULT '{}',
            payload JSONB NOT NULL DEFAULT '{}',
            data_as_of TIMESTAMPTZ NULL,
            notes TEXT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_portfolio_risk_snapshots_user_computed
            ON portfolio_risk_snapshots (user_id, computed_at DESC);

        ALTER TABLE portfolio_risk_snapshots ENABLE ROW LEVEL SECURITY;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = 'portfolio_risk_snapshots'
                  AND policyname = 'portfolio_risk_snapshots_user_isolation'
            ) THEN
                CREATE POLICY portfolio_risk_snapshots_user_isolation
                    ON portfolio_risk_snapshots
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
        DROP POLICY IF EXISTS portfolio_risk_snapshots_user_isolation ON portfolio_risk_snapshots;
        ALTER TABLE portfolio_risk_snapshots DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS portfolio_risk_snapshots;
        """
    )
