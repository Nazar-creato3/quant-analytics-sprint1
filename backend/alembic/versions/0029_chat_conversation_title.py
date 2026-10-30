"""Add title column to chat_conversations for readable sidebar labels.

Revision ID: 0029_chat_title
Revises: 0028_hierarchy_cal_created
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0029_chat_title"
down_revision: Union[str, None] = "0028_hierarchy_cal_created"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_conversations
          ADD COLUMN IF NOT EXISTS title VARCHAR(200) NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_conversations DROP COLUMN IF EXISTS title;
        """
    )
