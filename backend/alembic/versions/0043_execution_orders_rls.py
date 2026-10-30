"""Row-level security for execution_orders (user isolation via maneuver report).

Revision ID: 0043_execution_orders_rls
Revises: 0042_appuser_login_grants
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0043_execution_orders_rls"
down_revision: Union[str, None] = "0042_appuser_login_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")


def _policy(table: str, policy_name: str, using_expr: str) -> None:
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
                    USING ({using_expr})
                    WITH CHECK ({using_expr});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _enable_rls("execution_orders")
    _policy(
        "execution_orders",
        "execution_orders_user_isolation",
        """
        EXISTS (
            SELECT 1 FROM maneuvers m
            JOIN maneuver_reports r ON r.id = m.report_id
            WHERE m.id = execution_orders.maneuver_id
              AND r.created_by IS NOT NULL
              AND r.created_by = current_setting('app.user_id', true)
        )
        """.strip(),
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS execution_orders_user_isolation ON execution_orders;")
    op.execute("ALTER TABLE execution_orders DISABLE ROW LEVEL SECURITY;")
