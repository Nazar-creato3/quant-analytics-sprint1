"""Watchlist alert rules + trading placement audit (blueprint §8–9).

Revision ID: 0030_trading_alerts
Revises: 0029_chat_title
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0030_trading_alerts"
down_revision: Union[str, None] = "0029_chat_title"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_placement_audit (
            id VARCHAR(36) PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            actor_email VARCHAR(320),
            resource_type VARCHAR(32) NOT NULL,
            resource_id VARCHAR(36) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            side VARCHAR(8) NOT NULL,
            broker_mode VARCHAR(32) NOT NULL,
            trading_mode VARCHAR(16),
            details JSONB NOT NULL DEFAULT '{}',
            ip_address VARCHAR(45)
        );
        CREATE INDEX IF NOT EXISTS ix_trading_placement_audit_ts
            ON trading_placement_audit (timestamp);
        CREATE INDEX IF NOT EXISTS ix_trading_placement_audit_symbol
            ON trading_placement_audit (symbol);
        CREATE INDEX IF NOT EXISTS ix_trading_placement_audit_resource
            ON trading_placement_audit (resource_id);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_alert_rules (
            id VARCHAR(36) PRIMARY KEY,
            user_email VARCHAR(320) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            metric VARCHAR(32) NOT NULL DEFAULT 'ml_confidence',
            threshold DOUBLE PRECISION NOT NULL,
            direction VARCHAR(8) NOT NULL DEFAULT 'above',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_triggered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_email, symbol, metric, direction)
        );
        CREATE INDEX IF NOT EXISTS ix_watchlist_alert_rules_user
            ON watchlist_alert_rules (user_email);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            CREATE ROLE appuser NOLOGIN;
          END IF;
        END $$;
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON trading_placement_audit FROM appuser")
    op.execute("GRANT SELECT, INSERT ON trading_placement_audit TO appuser")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS watchlist_alert_rules")
    op.execute("DROP TABLE IF EXISTS trading_placement_audit")
