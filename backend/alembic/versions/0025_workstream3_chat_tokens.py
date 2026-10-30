"""Workstream 3: chat tables, refresh-token families, append-only messages REVOKE.

Revision ID: 0025_workstream3
Revises: 0024_workstream2
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0025_workstream3"
down_revision: Union[str, None] = "0024_workstream2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_token_families (
            id VARCHAR(36) PRIMARY KEY,
            subject VARCHAR(255) NOT NULL,
            current_jti VARCHAR(64) NOT NULL,
            revoked BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_refresh_token_subject ON refresh_token_families(subject);

        CREATE TABLE IF NOT EXISTS chat_conversations (
            id VARCHAR(36) PRIMARY KEY,
            client_profile_id VARCHAR(36) NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            assigned_admin_id VARCHAR(36) NULL REFERENCES identities(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            related_deal_intent_id VARCHAR(36) NULL REFERENCES deal_intents(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_chat_conv_client ON chat_conversations(client_profile_id);
        CREATE INDEX IF NOT EXISTS ix_chat_conv_admin ON chat_conversations(assigned_admin_id);
        CREATE INDEX IF NOT EXISTS ix_chat_conv_deal ON chat_conversations(related_deal_intent_id);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id VARCHAR(36) PRIMARY KEY,
            conversation_id VARCHAR(36) NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            sender_id VARCHAR(36) NOT NULL,
            sender_role VARCHAR(30) NOT NULL,
            body TEXT NOT NULL,
            attachment_url VARCHAR(500) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            read_at TIMESTAMPTZ NULL
        );
        CREATE INDEX IF NOT EXISTS ix_chat_msg_conv ON chat_messages(conversation_id);
        CREATE INDEX IF NOT EXISTS ix_chat_msg_created ON chat_messages(created_at);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            CREATE ROLE appuser NOLOGIN;
          END IF;
          REVOKE UPDATE, DELETE ON chat_messages FROM appuser;
          REVOKE UPDATE, DELETE ON admission_status_history FROM appuser;
          REVOKE UPDATE, DELETE ON audit_logs FROM appuser;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS chat_messages CASCADE;
        DROP TABLE IF EXISTS chat_conversations CASCADE;
        DROP TABLE IF EXISTS refresh_token_families CASCADE;
        """
    )
