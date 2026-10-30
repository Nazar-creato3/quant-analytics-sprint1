"""0051 robot core ideal — fills, sessions, funding, fees, governance, edge.

Revision ID: 0051_robot_core_ideal
Revises: 0050_robot_core_rls_grants
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0051_robot_core_ideal"
down_revision: Union[str, None] = "0050_robot_core_rls_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE robot_plans
            ADD COLUMN IF NOT EXISTS plan_type VARCHAR(16) NOT NULL DEFAULT 'custom'
        """
    )
    op.execute(
        """
        ALTER TABLE robot_plans
            ADD COLUMN IF NOT EXISTS plan_params JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE robot_plans
            ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE robot_plans
            ADD COLUMN IF NOT EXISTS session_id VARCHAR(36)
        """
    )
    op.execute(
        """
        ALTER TABLE robot_plans
            ADD COLUMN IF NOT EXISTS is_legacy BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_robot_plans_session ON robot_plans (session_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_level_fills (
            id VARCHAR(36) PRIMARY KEY,
            plan_id VARCHAR(36) NOT NULL REFERENCES robot_plans(id),
            level_id VARCHAR(64) NOT NULL,
            action VARCHAR(16) NOT NULL,
            celery_task_id VARCHAR(64) NOT NULL DEFAULT '',
            client_order_id VARCHAR(128) NOT NULL,
            qty FLOAT NOT NULL DEFAULT 0,
            price FLOAT NOT NULL DEFAULT 0,
            fee_usd FLOAT NOT NULL DEFAULT 0,
            liquidity VARCHAR(8) NOT NULL DEFAULT 'taker',
            maneuver_id VARCHAR(36),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_robot_level_fill_idem
                UNIQUE (plan_id, level_id, action, celery_task_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_robot_level_fills_client_order "
        "ON robot_level_fills (client_order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_robot_level_fills_plan ON robot_level_fills (plan_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            robot_plan_id VARCHAR(36),
            ticker VARCHAR(24) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            entry_reason VARCHAR(64),
            plan_version VARCHAR(64),
            override_log JSONB NOT NULL DEFAULT '[]'::jsonb,
            total_pnl FLOAT NOT NULL DEFAULT 0,
            total_fees FLOAT NOT NULL DEFAULT 0,
            total_funding FLOAT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at TIMESTAMPTZ,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_strategy_sessions_user_status "
        "ON strategy_sessions (user_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_strategy_sessions_plan "
        "ON strategy_sessions (robot_plan_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funding_events (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            plan_id VARCHAR(36),
            lot_id VARCHAR(36),
            ticker VARCHAR(24) NOT NULL,
            venue VARCHAR(32) NOT NULL DEFAULT 'paper',
            rate FLOAT NOT NULL DEFAULT 0,
            amount FLOAT NOT NULL DEFAULT 0,
            currency VARCHAR(12) NOT NULL DEFAULT 'USD',
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funding_events_user_ticker "
        "ON funding_events (user_id, ticker)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS venue_fees (
            id VARCHAR(36) PRIMARY KEY,
            venue VARCHAR(32) NOT NULL,
            symbol VARCHAR(32) NOT NULL DEFAULT '*',
            maker_rate FLOAT NOT NULL DEFAULT 0.0002,
            taker_rate FLOAT NOT NULL DEFAULT 0.0005,
            source VARCHAR(32) NOT NULL DEFAULT 'default',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT uq_venue_fees_venue_symbol UNIQUE (venue, symbol)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_logs (
            id VARCHAR(36) PRIMARY KEY,
            action VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            initiated_by VARCHAR(36) NOT NULL REFERENCES users(id),
            approved_by JSONB NOT NULL DEFAULT '[]'::jsonb,
            required_approvals INTEGER NOT NULL DEFAULT 2,
            reason TEXT NOT NULL DEFAULT '',
            affected_plans JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            executed_at TIMESTAMPTZ,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_risk_states (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) UNIQUE,
            equity_start_of_day FLOAT,
            equity_start_of_month FLOAT,
            day_anchor_date VARCHAR(10),
            month_anchor VARCHAR(7),
            kill_switch_triggered BOOLEAN NOT NULL DEFAULT false,
            kill_switch_reason TEXT,
            day_limit_pct FLOAT NOT NULL DEFAULT 5,
            month_limit_pct FLOAT NOT NULL DEFAULT 15,
            max_exposure_symbol_pct FLOAT NOT NULL DEFAULT 10,
            max_exposure_venue_pct FLOAT NOT NULL DEFAULT 30,
            max_correlation FLOAT NOT NULL DEFAULT 0.8,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            id VARCHAR(36) PRIMARY KEY,
            ticker VARCHAR(24) NOT NULL,
            venue VARCHAR(32) NOT NULL DEFAULT 'paper',
            bids JSONB NOT NULL DEFAULT '[]'::jsonb,
            asks JSONB NOT NULL DEFAULT '[]'::jsonb,
            mid FLOAT,
            spread_bps FLOAT,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orderbook_snapshots_ticker_ts "
        "ON orderbook_snapshots (ticker, captured_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tape_events (
            id VARCHAR(36) PRIMARY KEY,
            ticker VARCHAR(24) NOT NULL,
            venue VARCHAR(32) NOT NULL DEFAULT 'paper',
            price FLOAT NOT NULL,
            qty FLOAT NOT NULL,
            side VARCHAR(8) NOT NULL DEFAULT 'buy',
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tape_events_ticker_ts "
        "ON tape_events (ticker, occurred_at)"
    )


def downgrade() -> None:
    for t in (
        "tape_events",
        "orderbook_snapshots",
        "portfolio_risk_states",
        "governance_logs",
        "venue_fees",
        "funding_events",
        "strategy_sessions",
        "robot_level_fills",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    for col in ("is_legacy", "session_id", "capabilities", "plan_params", "plan_type"):
        op.execute(f"ALTER TABLE robot_plans DROP COLUMN IF EXISTS {col}")
