"""payout_dividend_events — 57. Existing dividend_events stays the yfinance equity table.

Revision ID: 0059_payout_dividends
Revises: 0059_futures_market
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_payout_dividends"
down_revision: Union[str, None] = "0059_futures_market"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payout_dividend_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("figi", sa.Text(), nullable=False),
        sa.Column("secid", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("amount_gross", sa.Numeric(18, 8), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("declared_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("last_buy_date", sa.Date(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payout_div_figi", "payout_dividend_events", ["figi", "record_date"])


def downgrade() -> None:
    op.drop_index("ix_payout_div_figi", table_name="payout_dividend_events")
    op.drop_table("payout_dividend_events")
