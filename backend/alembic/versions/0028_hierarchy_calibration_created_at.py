"""Add missing created_at on hierarchy_calibration_history (ORM vs migration drift).

Revision ID: 0028_hierarchy_cal_created
Revises: 0027_chat_ticker
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0028_hierarchy_cal_created"
down_revision: Union[str, None] = "0027_chat_ticker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE hierarchy_calibration_history
          ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE hierarchy_calibration_history
          DROP COLUMN IF EXISTS created_at;
        """
    )
