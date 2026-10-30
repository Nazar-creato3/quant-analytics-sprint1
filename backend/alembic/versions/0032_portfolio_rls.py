"""Row-level security for portfolio tables (user isolation).

Revision ID: 0032_portfolio_rls
Revises: 0031_maneuvers_orders
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0032_portfolio_rls"
down_revision: Union[str, None] = "0031_maneuvers_orders"
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
    # maneuver_reports: direct user ownership
    _enable_rls("maneuver_reports")
    _policy(
        "maneuver_reports",
        "maneuver_reports_user_isolation",
        "created_by IS NOT NULL AND created_by = current_setting('app.user_id', true)",
    )

    # maneuvers: inherit ownership via report
    _enable_rls("maneuvers")
    _policy(
        "maneuvers",
        "maneuvers_user_isolation",
        """
        EXISTS (
            SELECT 1 FROM maneuver_reports r
            WHERE r.id = maneuvers.report_id
              AND r.created_by IS NOT NULL
              AND r.created_by = current_setting('app.user_id', true)
        )
        """.strip(),
    )

    # manual_orders: direct user ownership
    _enable_rls("manual_orders")
    _policy(
        "manual_orders",
        "manual_orders_user_isolation",
        "user_id IS NOT NULL AND user_id = current_setting('app.user_id', true)",
    )

    # trades: via trading_accounts.user_id
    _enable_rls("trades")
    _policy(
        "trades",
        "trades_user_isolation",
        """
        EXISTS (
            SELECT 1 FROM trading_accounts ta
            WHERE ta.id = trades.account_id
              AND ta.user_id = current_setting('app.user_id', true)
        )
        """.strip(),
    )


def downgrade() -> None:
    for table, policy in (
        ("trades", "trades_user_isolation"),
        ("manual_orders", "manual_orders_user_isolation"),
        ("maneuvers", "maneuvers_user_isolation"),
        ("maneuver_reports", "maneuver_reports_user_isolation"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
