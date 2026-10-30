"""Maneuver signal_meta + manual order tables.

Revision ID: 0031_maneuvers_orders
Revises: 0030_trading_alerts
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0031_maneuvers_orders"
down_revision: Union[str, None] = "0030_trading_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE maneuvers
        ADD COLUMN IF NOT EXISTS signal_meta JSONB NOT NULL DEFAULT '{}';
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_orders (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            ticker VARCHAR(20) NOT NULL,
            side VARCHAR(10) NOT NULL,
            order_type VARCHAR(20) NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            limit_price DOUBLE PRECISION,
            stop_price DOUBLE PRECISION,
            time_in_force VARCHAR(10) NOT NULL DEFAULT 'gtc',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            bracket_stop_loss DOUBLE PRECISION,
            bracket_take_profit DOUBLE PRECISION,
            trailing_stop_pct DOUBLE PRECISION,
            oco_sibling_price DOUBLE PRECISION,
            maneuver_id VARCHAR(36) REFERENCES maneuvers(id) ON DELETE SET NULL,
            sibling_order_id VARCHAR(36),
            broker_order_id VARCHAR(100),
            fill_price DOUBLE PRECISION,
            fill_quantity DOUBLE PRECISION,
            estimated_fees_usd DOUBLE PRECISION,
            slippage_warning TEXT,
            note TEXT,
            error_message TEXT,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            filled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_manual_orders_user ON manual_orders (user_id);
        CREATE INDEX IF NOT EXISTS ix_manual_orders_ticker ON manual_orders (ticker);
        CREATE INDEX IF NOT EXISTS ix_manual_orders_status ON manual_orders (status);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conditional_order_watches (
            id VARCHAR(36) PRIMARY KEY,
            manual_order_id VARCHAR(36) NOT NULL REFERENCES manual_orders(id) ON DELETE CASCADE,
            user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            ticker VARCHAR(20) NOT NULL,
            trigger_type VARCHAR(20) NOT NULL,
            trigger_price DOUBLE PRECISION,
            trail_distance_pct DOUBLE PRECISION,
            peak_price DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'watching',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            triggered_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS ix_conditional_watches_status
            ON conditional_order_watches (status);
        CREATE INDEX IF NOT EXISTS ix_conditional_watches_ticker
            ON conditional_order_watches (ticker);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conditional_order_watches;")
    op.execute("DROP TABLE IF EXISTS manual_orders;")
    op.execute("ALTER TABLE maneuvers DROP COLUMN IF EXISTS signal_meta;")
