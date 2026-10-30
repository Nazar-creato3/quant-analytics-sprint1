"""Data core extensions: order book snapshots, macro indicators, sector mapping.

Revision ID: 0016_data_core_extensions
Revises: 0015_custom_basket
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0016_data_core_extensions"
down_revision: Union[str, None] = "0015_custom_basket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_book_snapshots (
            time            TIMESTAMPTZ NOT NULL,
            instrument_id   INT NOT NULL REFERENCES instruments(id),
            bid_depth       JSONB NOT NULL DEFAULT '[]'::jsonb,
            ask_depth       JSONB NOT NULL DEFAULT '[]'::jsonb,
            spread_bps      NUMERIC,
            PRIMARY KEY (time, instrument_id)
        )
        """
    )
    conn = op.get_bind()
    has_timescale = bool(
        conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')")
        ).scalar()
    )
    if has_timescale:
        conn.execute(
            text(
                "SELECT create_hypertable('order_book_snapshots', 'time', if_not_exists => TRUE)"
            )
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_order_book_instrument_time
            ON order_book_snapshots (instrument_id, time DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_indicators (
            id              SERIAL PRIMARY KEY,
            indicator_code  TEXT NOT NULL,
            value           NUMERIC NOT NULL,
            published_at    TIMESTAMPTZ NOT NULL,
            source          TEXT NOT NULL,
            UNIQUE (indicator_code, published_at, source)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_macro_indicators_code_time
            ON macro_indicators (indicator_code, published_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sector_mapping (
            instrument_id   INT PRIMARY KEY REFERENCES instruments(id) ON DELETE CASCADE,
            sector          TEXT NOT NULL,
            industry        TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sector_mapping_sector
            ON sector_mapping (sector)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sector_mapping")
    op.execute("DROP TABLE IF EXISTS macro_indicators")
    op.execute("DROP TABLE IF EXISTS order_book_snapshots")
