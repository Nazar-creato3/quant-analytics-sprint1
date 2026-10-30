"""Workstream 1: unconditional append-only REVOKE for audit tables.

Revision ID: 0026_workstream1
Revises: 0025_workstream3
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0026_workstream1"
down_revision: Union[str, None] = "0025_workstream3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM appuser")
    op.execute("REVOKE UPDATE, DELETE ON admission_status_history FROM appuser")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'chat_messages'
          ) THEN
            REVOKE UPDATE, DELETE ON chat_messages FROM appuser;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON audit_logs TO appuser")
    op.execute("GRANT UPDATE, DELETE ON admission_status_history TO appuser")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'chat_messages'
          ) THEN
            GRANT UPDATE, DELETE ON chat_messages TO appuser;
          END IF;
        END $$;
        """
    )
