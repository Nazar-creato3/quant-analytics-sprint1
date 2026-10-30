"""Futures market hypertables (prompt 58B).

Revision ID: 0059_futures_market
Revises: 0058_factor_returns
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0059_futures_market"
down_revision: Union[str, None] = "0058_factor_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fut_trades (
            time TIMESTAMPTZ NOT NULL,
            ticker TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL,
            qty DOUBLE PRECISION NOT NULL,
            side TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fut_oi_daily (
            time DATE NOT NULL,
            ticker TEXT NOT NULL,
            open_interest DOUBLE PRECISION,
            volume DOUBLE PRECISION,
            PRIMARY KEY (time, ticker)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fut_futoi (
            time DATE NOT NULL,
            ticker TEXT NOT NULL,
            phys_long DOUBLE PRECISION,
            phys_short DOUBLE PRECISION,
            legal_long DOUBLE PRECISION,
            legal_short DOUBLE PRECISION,
            phys_count INTEGER,
            legal_count INTEGER,
            PRIMARY KEY (time, ticker)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fut_funding (
            time DATE NOT NULL,
            ticker TEXT NOT NULL,
            rate DOUBLE PRECISION,
            PRIMARY KEY (time, ticker)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fut_orderbook_snapshots (
            time TIMESTAMPTZ NOT NULL,
            ticker TEXT NOT NULL,
            payload JSONB NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fut_orderbook_snapshots")
    op.execute("DROP TABLE IF EXISTS fut_funding")
    op.execute("DROP TABLE IF EXISTS fut_futoi")
    op.execute("DROP TABLE IF EXISTS fut_oi_daily")
    op.execute("DROP TABLE IF EXISTS fut_trades")
