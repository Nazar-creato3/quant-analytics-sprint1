"""0044 тАФ trading key secrets + paper/live mode + health columns.

Revision ID: 0044_trading_key_secrets
Revises: 0041_trading_keys_rls_catchup
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_trading_key_secrets"
down_revision: Union[str, None] = "0043_execution_orders_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='trading_key_metadata'"
    ))}

    if "account_mode" not in cols:
        op.add_column(
            "trading_key_metadata",
            sa.Column("account_mode", sa.String(length=10), server_default="live", nullable=False),
        )
    if "account_display" not in cols:
        op.add_column("trading_key_metadata", sa.Column("account_display", sa.String(length=255), nullable=True))
    if "last_health_at" not in cols:
        op.add_column("trading_key_metadata", sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True))
    if "last_health_status" not in cols:
        op.add_column("trading_key_metadata", sa.Column("last_health_status", sa.String(length=32), nullable=True))

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_trading_key_user_venue'
            ) THEN
                ALTER TABLE trading_key_metadata DROP CONSTRAINT uq_trading_key_user_venue;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_trading_key_user_venue_mode'
            ) THEN
                ALTER TABLE trading_key_metadata
                ADD CONSTRAINT uq_trading_key_user_venue_mode
                UNIQUE (user_id, venue, account_mode);
            END IF;
        END $$;
        """
    )

    tables = {r[0] for r in conn.execute(sa.text(
        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename='trading_key_secrets'"
    ))}
    if not tables:
        op.create_table(
            "trading_key_secrets",
            sa.Column("key_id", sa.String(length=36), nullable=False),
            sa.Column("encrypted_payload", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["key_id"], ["trading_key_metadata.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("key_id"),
        )
        op.execute("ALTER TABLE trading_key_secrets ENABLE ROW LEVEL SECURITY;")
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'trading_key_secrets'
                      AND policyname = 'trading_key_secrets_user_isolation'
                ) THEN
                    CREATE POLICY trading_key_secrets_user_isolation ON trading_key_secrets
                    FOR ALL
                    USING (
                        key_id IN (
                            SELECT id FROM trading_key_metadata
                            WHERE user_id = current_setting('app.user_id', true)
                        )
                    )
                    WITH CHECK (
                        key_id IN (
                            SELECT id FROM trading_key_metadata
                            WHERE user_id = current_setting('app.user_id', true)
                        )
                    );
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS trading_key_secrets_user_isolation ON trading_key_secrets;")
    op.drop_table("trading_key_secrets")
    op.drop_constraint("uq_trading_key_user_venue_mode", "trading_key_metadata", type_="unique")
    op.create_unique_constraint("uq_trading_key_user_venue", "trading_key_metadata", ["user_id", "venue"])
    for col in ("last_health_status", "last_health_at", "account_display", "account_mode"):
        op.drop_column("trading_key_metadata", col)
