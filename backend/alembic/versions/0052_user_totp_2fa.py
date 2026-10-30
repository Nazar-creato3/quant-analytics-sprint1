"""0052 user TOTP 2FA — encrypted secret, backup codes, audit-friendly timestamps.

Revision ID: 0052_user_totp_2fa
Revises: 0051_robot_core_ideal
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_user_totp_2fa"
down_revision: Union[str, None] = "0051_robot_core_ideal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("two_factor_secret", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "two_factor_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "two_factor_backup_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("two_factor_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("two_factor_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_two_factor_enabled", "users", ["two_factor_enabled"])


def downgrade() -> None:
    op.drop_index("ix_users_two_factor_enabled", table_name="users")
    op.drop_column("users", "two_factor_disabled_at")
    op.drop_column("users", "two_factor_enabled_at")
    op.drop_column("users", "two_factor_backup_codes")
    op.drop_column("users", "two_factor_enabled")
    op.drop_column("users", "two_factor_secret")
