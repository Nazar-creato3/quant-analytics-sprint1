"""portfolio_book accounts + transactions (Prompt 05).

Revision ID: 0056_portfolio_book
Revises: 0055_forecast_log
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_portfolio_book"
down_revision: Union[str, None] = "0055_forecast_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "book_account",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_depth_days", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("mode IN ('paper', 'live')", name="ck_book_account_mode"),
    )
    op.create_table(
        "book_transaction",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("ccy", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue", "external_id", name="uq_book_txn_venue_ext"),
        sa.CheckConstraint("mode IN ('paper', 'live')", name="ck_book_txn_mode"),
    )
    op.create_index("ix_book_txn_user_mode", "book_transaction", ["user_id", "mode"])


def downgrade() -> None:
    op.drop_index("ix_book_txn_user_mode", table_name="book_transaction")
    op.drop_table("book_transaction")
    op.drop_table("book_account")
