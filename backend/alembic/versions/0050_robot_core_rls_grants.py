"""0050 robot core RLS/grants catch-up (idempotent).

Revision ID: 0050_robot_core_rls_grants
Revises: 0049_robot_core

Safe re-apply if 0049 partially landed or appuser lacked grants.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0050_robot_core_rls_grants"
down_revision: Union[str, None] = "0049_robot_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _policy(table: str, policy_name: str) -> None:
    using = "user_id = current_setting('app.user_id', true)"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = '{table}'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = '{table}'
                  AND policyname = '{policy_name}'
            ) THEN
                EXECUTE 'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY';
                CREATE POLICY {policy_name} ON {table}
                    FOR ALL
                    USING ({using})
                    WITH CHECK ({using});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    for table, policy in (
        ("position_lots", "position_lots_user_isolation"),
        ("lot_close_events", "lot_close_events_user_isolation"),
        ("robot_plans", "robot_plans_user_isolation"),
    ):
        _policy(table, policy)

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            IF EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'position_lots'
            ) THEN
              EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON position_lots TO appuser';
            END IF;
            IF EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'lot_close_events'
            ) THEN
              EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON lot_close_events TO appuser';
            END IF;
            IF EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'robot_plans'
            ) THEN
              EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON robot_plans TO appuser';
            END IF;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
