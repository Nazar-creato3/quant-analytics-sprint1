"""Row-level security for deal_intents (user isolation via sleeve).

Revision ID: 0040_deal_intents_rls
Revises: 0039_trading_keys
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0040_deal_intents_rls"
down_revision: Union[str, None] = "0039_trading_keys"
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
    _enable_rls("deal_intents")
    _policy(
        "deal_intents",
        "deal_intents_user_isolation",
        """
        EXISTS (
            SELECT 1 FROM sleeves s
            WHERE s.id = deal_intents.sleeve_id
              AND s.profile_id = current_setting('app.user_id', true)
        )
        """.strip(),
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS deal_intents_user_isolation ON deal_intents;")
    op.execute("ALTER TABLE deal_intents DISABLE ROW LEVEL SECURITY;")
