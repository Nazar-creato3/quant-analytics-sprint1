"""Promote appuser to LOGIN application role with table grants (RLS-enforced).

Revision ID: 0042_appuser_login_grants
Revises: 0041_trading_keys_rls_catchup

Password is set out-of-band via scripts/setup-appuser-role.sh (APP_DB_PASSWORD).
Reserve apex superuser for migrations only (MIGRATION_DATABASE_URL_SYNC).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0042_appuser_login_grants"
down_revision: Union[str, None] = "0041_trading_keys_rls_catchup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APPEND_ONLY_TABLES = (
    "audit_logs",
    "admission_status_history",
    "chat_messages",
    "trading_placement_audit",
    "subscription_status_audit",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            CREATE ROLE appuser LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
          ELSE
            ALTER ROLE appuser WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
          END IF;
        END $$;
        """
    )

    op.execute("GRANT CONNECT ON DATABASE apex_intel TO appuser")
    op.execute("GRANT USAGE ON SCHEMA public TO appuser")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO appuser"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO appuser")

    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE apex IN SCHEMA public
          GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO appuser
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE apex IN SCHEMA public
          GRANT USAGE, SELECT ON SEQUENCES TO appuser
        """
    )

    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = '{table}'
              ) THEN
                REVOKE UPDATE, DELETE ON {table} FROM appuser;
              END IF;
            END $$;
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'trading_placement_audit'
          ) THEN
            GRANT SELECT, INSERT ON trading_placement_audit TO appuser;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM appuser")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM appuser")
    op.execute("REVOKE USAGE ON SCHEMA public FROM appuser")
    op.execute("REVOKE CONNECT ON DATABASE apex_intel FROM appuser")
    op.execute("ALTER ROLE appuser WITH NOLOGIN")
