"""Add trading constitution fields to user profiles.

Revision ID: 0008_profile_constitution
Revises: 0007_domain_core
Create Date: 2026-07-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0008_profile_constitution"
down_revision: Union[str, None] = "0007_domain_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policies (
            id          VARCHAR(36) PRIMARY KEY,
            profile_id  VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        VARCHAR(100) NOT NULL,
            config      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policies_profile_id ON approval_policies (profile_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id                      VARCHAR(36) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            risk_appetite           VARCHAR(20) NOT NULL DEFAULT 'moderate',
            max_drawdown_pct        NUMERIC(5, 2) NOT NULL DEFAULT 15.00
                CHECK (max_drawdown_pct > 0 AND max_drawdown_pct <= 100),
            max_daily_loss_abs      NUMERIC(18, 6) NOT NULL DEFAULT 0
                CHECK (max_daily_loss_abs >= 0),
            allowed_categories      JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed_instrument_ids  JSONB NOT NULL DEFAULT '[]'::jsonb,
            approval_policy_id      VARCHAR(36) REFERENCES approval_policies(id) ON DELETE SET NULL,
            time_horizon            VARCHAR(20) NOT NULL DEFAULT 'swing',
            execution_style         VARCHAR(20) NOT NULL DEFAULT 'active',
            volatility_tolerance    DOUBLE PRECISION NOT NULL DEFAULT 0.5
                CHECK (volatility_tolerance >= 0 AND volatility_tolerance <= 1),
            hedge_preference        BOOLEAN NOT NULL DEFAULT false,
            leverage_max            NUMERIC(8, 4) NOT NULL DEFAULT 1
                CHECK (leverage_max >= 0),
            mode                    VARCHAR(10) NOT NULL DEFAULT 'paper',
            automation_level        VARCHAR(20) NOT NULL DEFAULT 'manual',
            session_preferences     JSONB NOT NULL DEFAULT '{}'::jsonb,
            news_sensitivity        DOUBLE PRECISION NOT NULL DEFAULT 0.5
                CHECK (news_sensitivity >= 0 AND news_sensitivity <= 1),
            event_sensitivity       DOUBLE PRECISION NOT NULL DEFAULT 0.5
                CHECK (event_sensitivity >= 0 AND event_sensitivity <= 1),
            diversification_policy  JSONB NOT NULL DEFAULT '{}'::jsonb,
            paper_trading_days      INTEGER NOT NULL DEFAULT 0
                CHECK (paper_trading_days >= 0),
            paper_sharpe            DOUBLE PRECISION,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS profiles")
    op.execute("DROP TABLE IF EXISTS approval_policies")
