"""0049 robot lot ledger + robot plans.

Revision ID: 0049_robot_core
Revises: 0048_unified_bots
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0049_robot_core"
down_revision: Union[str, None] = "0048_unified_bots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _policy(table: str, policy_name: str) -> None:
    using = "user_id = current_setting('app.user_id', true)"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = '{table}'
                  AND policyname = '{policy_name}'
            ) THEN
                CREATE POLICY {policy_name} ON {table}
                    FOR ALL
                    USING ({using})
                    WITH CHECK ({using});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # One statement per execute — psycopg/SQLAlchemy reject multi-statement strings.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS position_lots (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            ticker VARCHAR(24) NOT NULL,
            side VARCHAR(8) NOT NULL,
            qty_open DOUBLE PRECISION NOT NULL DEFAULT 0,
            qty_initial DOUBLE PRECISION NOT NULL DEFAULT 0,
            entry_price DOUBLE PRECISION NOT NULL,
            fee_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            source VARCHAR(32) NOT NULL DEFAULT 'maneuver',
            maneuver_id VARCHAR(36) NULL REFERENCES maneuvers(id),
            robot_plan_id VARCHAR(36) NULL,
            opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_position_lots_user_id ON position_lots (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_position_lots_ticker ON position_lots (ticker)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_position_lots_user_ticker_status "
        "ON position_lots (user_id, ticker, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_position_lots_robot_plan_id ON position_lots (robot_plan_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lot_close_events (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            ticker VARCHAR(24) NOT NULL,
            lot_id VARCHAR(36) NOT NULL REFERENCES position_lots(id),
            qty DOUBLE PRECISION NOT NULL,
            exit_price DOUBLE PRECISION NOT NULL,
            realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
            fee_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            reason VARCHAR(32) NOT NULL DEFAULT 'manual',
            maneuver_id VARCHAR(36) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lot_close_events_user_id ON lot_close_events (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lot_close_events_ticker ON lot_close_events (ticker)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_plans (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            ticker VARCHAR(24) NOT NULL,
            maneuver_id VARCHAR(36) NULL REFERENCES maneuvers(id),
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            side VARCHAR(8) NOT NULL DEFAULT 'long',
            mode VARCHAR(10) NOT NULL DEFAULT 'paper',
            levels JSONB NOT NULL DEFAULT '[]'::jsonb,
            kill_switch_pct DOUBLE PRECISION NULL,
            peak_equity_usd DOUBLE PRECISION NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_robot_plans_user_id ON robot_plans (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_robot_plans_ticker ON robot_plans (ticker)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_robot_plans_user_status ON robot_plans (user_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_robot_plans_maneuver ON robot_plans (maneuver_id)"
    )

    op.execute("ALTER TABLE position_lots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lot_close_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE robot_plans ENABLE ROW LEVEL SECURITY")

    _policy("position_lots", "position_lots_user_isolation")
    _policy("lot_close_events", "lot_close_events_user_isolation")
    _policy("robot_plans", "robot_plans_user_isolation")

    # GRANT must use EXECUTE inside DO (PL/pgSQL)
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON position_lots TO appuser';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON lot_close_events TO appuser';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON robot_plans TO appuser';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS robot_plans_user_isolation ON robot_plans")
    op.execute("DROP POLICY IF EXISTS lot_close_events_user_isolation ON lot_close_events")
    op.execute("DROP POLICY IF EXISTS position_lots_user_isolation ON position_lots")
    op.execute("ALTER TABLE robot_plans DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lot_close_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE position_lots DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS lot_close_events")
    op.execute("DROP TABLE IF EXISTS position_lots")
    op.execute("DROP TABLE IF EXISTS robot_plans")
