"""instrument_eod + instrument corporate actions (Prompt 04).

Revision ID: 0054_instrument_eod
Revises: 0053_catalog


0013 already created ``corporate_actions`` for equity analytics
(symbol, action_type). That table stays. Prompt 04 rows go in
``instrument_corporate_actions`` so a fresh upgrade can reach head.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054_instrument_eod"
down_revision: Union[str, None] = "0053_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTION_COLUMNS = (
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("instrument_id", sa.Text(), nullable=False),
    sa.Column("session_date", sa.Date(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("factor", sa.Numeric(), nullable=True),
    sa.Column("cash", sa.Numeric(), nullable=True),
    sa.Column("ccy", sa.Text(), nullable=True),
    sa.Column("source", sa.Text(), nullable=False),
    sa.Column("license_tag", sa.Text(), nullable=False),
    sa.Column("manual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
)


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:

    op.create_table(
        "instrument_eod",
        sa.Column("instrument_id", sa.Text(), primary_key=True),
        sa.Column("session_date", sa.Date(), primary_key=True),
        sa.Column("official_close", sa.Numeric(), nullable=True),
        sa.Column("last_close", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("board", sa.Text(), nullable=True),
        sa.Column("license_tag", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
    )
    op.create_index("ix_instrument_eod_date", "instrument_eod", ["session_date"])
    equity_cols = _column_names("corporate_actions")
    if "kind" in equity_cols and "session_date" in equity_cols:
        return
    # Equity analytics (0013) already owns corporate_actions.
    table = "corporate_actions" if not equity_cols else "instrument_corporate_actions"
    op.create_table(table, *_ACTION_COLUMNS)


def downgrade() -> None:
    if _column_names("instrument_corporate_actions"):
        op.drop_table("instrument_corporate_actions")
    elif "kind" in _column_names("corporate_actions"):
        op.drop_table("corporate_actions")
    op.drop_index("ix_instrument_eod_date", table_name="instrument_eod")
    op.drop_table("instrument_eod")
