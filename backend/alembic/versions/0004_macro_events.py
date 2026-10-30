"""Add macro_events table

Revision ID: 0004_macro_events
Revises: 0003_seed
Create Date: 2024-06-07 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_macro_events"
down_revision = "0003_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_name", sa.String(255), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("country", sa.String(10), server_default="US"),
        sa.Column("impact", sa.String(20), server_default="medium"),
        sa.Column("source", sa.String(100), server_default="system"),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("market_effect", sa.Float(), server_default="0"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("tickers_affected", postgresql.JSON(), server_default="[]"),
        sa.Column("raw_data", postgresql.JSON(), server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_macro_event_date", "macro_events", ["event_date"])


def downgrade() -> None:
    op.drop_index("ix_macro_event_date", table_name="macro_events")
    op.drop_table("macro_events")
