"""investment_profile current + history (Prompt 35).

Revision ID: 0057_investment_profile
Revises: 0056_portfolio_book
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_investment_profile"
down_revision: Union[str, None] = "0056_portfolio_book"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investment_profile",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
    )
    op.create_table(
        "investment_profile_history",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("answers_hash", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("prev_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_inv_profile_hist_user", "investment_profile_history", ["user_id", "version"])


def downgrade() -> None:
    op.drop_index("ix_inv_profile_hist_user", table_name="investment_profile_history")
    op.drop_table("investment_profile_history")
    op.drop_table("investment_profile")
