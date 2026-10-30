"""Add related_symbol to chat conversations for watchlist AI chat.

Revision ID: 0027_chat_ticker
Revises: 0026_workstream1
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0027_chat_ticker"
down_revision: Union[str, None] = "0026_workstream1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_conversations
          ADD COLUMN IF NOT EXISTS related_symbol VARCHAR(32) NULL;
        CREATE INDEX IF NOT EXISTS ix_chat_conv_symbol
          ON chat_conversations(related_symbol);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_chat_conv_symbol;
        ALTER TABLE chat_conversations DROP COLUMN IF EXISTS related_symbol;
        """
    )
