"""Trading key metadata + audit tables with RLS (Flow A).

Revision ID: 0039_trading_keys
Revises: 0038_forecast_snapshot_source
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0039_trading_keys"
down_revision: Union[str, None] = "0038_forecast_snapshot_source"
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
    op.create_table(
        "user_trading_mfa",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("mfa_secret", sa.String(length=64), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_trading_mfa_user_id", "user_trading_mfa", ["user_id"])

    op.create_table(
        "trading_key_metadata",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("venue", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("vault_path", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("permission_check_status", sa.String(length=32), server_default="skipped", nullable=False),
        sa.Column("withdraw_allowed", sa.Boolean(), nullable=True),
        sa.Column("permission_warning", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "venue", name="uq_trading_key_user_venue"),
    )
    op.create_index("ix_trading_key_metadata_user_id", "trading_key_metadata", ["user_id"])
    op.create_index("ix_trading_key_metadata_venue", "trading_key_metadata", ["venue"])
    op.create_index("ix_trading_key_metadata_status", "trading_key_metadata", ["status"])

    op.create_table(
        "trading_key_audit",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("key_id", sa.String(length=36), nullable=True),
        sa.Column("venue", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_key_audit_user_id", "trading_key_audit", ["user_id"])
    op.create_index("ix_trading_key_audit_key_id", "trading_key_audit", ["key_id"])
    op.create_index("ix_trading_key_audit_action", "trading_key_audit", ["action"])

    for table in ("user_trading_mfa", "trading_key_metadata", "trading_key_audit"):
        _enable_rls(table)
        _policy(
            table,
            f"{table}_user_isolation",
            "user_id IS NOT NULL AND user_id = current_setting('app.user_id', true)",
        )


def downgrade() -> None:
    for table, policy in (
        ("trading_key_audit", "trading_key_audit_user_isolation"),
        ("trading_key_metadata", "trading_key_metadata_user_isolation"),
        ("user_trading_mfa", "user_trading_mfa_user_isolation"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_trading_key_audit_action", table_name="trading_key_audit")
    op.drop_index("ix_trading_key_audit_key_id", table_name="trading_key_audit")
    op.drop_index("ix_trading_key_audit_user_id", table_name="trading_key_audit")
    op.drop_table("trading_key_audit")
    op.drop_index("ix_trading_key_metadata_status", table_name="trading_key_metadata")
    op.drop_index("ix_trading_key_metadata_venue", table_name="trading_key_metadata")
    op.drop_index("ix_trading_key_metadata_user_id", table_name="trading_key_metadata")
    op.drop_table("trading_key_metadata")
    op.drop_index("ix_user_trading_mfa_user_id", table_name="user_trading_mfa")
    op.drop_table("user_trading_mfa")
