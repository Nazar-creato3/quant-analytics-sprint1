"""Realtime market data pipeline tables (TimescaleDB hypertables)

Revision ID: 0006_market_data_realtime
Revises: 0005_audit_logs_user_fk
Create Date: 2026-07-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0006_market_data_realtime"
down_revision: Union[str, None] = "0005_audit_logs_user_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timescale_available(connection) -> bool:
    result = connection.execute(
        text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')")
    )
    return bool(result.scalar())


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT NOT NULL,
            source          TEXT NOT NULL,
            instrument_type TEXT NOT NULL,
            figi            TEXT,
            created_at      TIMESTAMPTZ DEFAULT now(),
            UNIQUE (symbol, source)
        )
        """
    )
    # market_trades — raw exchange ticks (not app trading_accounts.trades).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market_trades (
            time          TIMESTAMPTZ NOT NULL,
            instrument_id INT NOT NULL REFERENCES instruments(id),
            price         NUMERIC NOT NULL,
            quantity      NUMERIC NOT NULL,
            side          TEXT,
            trade_id      BIGINT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv (
            time          TIMESTAMPTZ NOT NULL,
            instrument_id INT NOT NULL REFERENCES instruments(id),
            timeframe     TEXT NOT NULL,
            open          NUMERIC,
            high          NUMERIC,
            low           NUMERIC,
            close         NUMERIC,
            volume        NUMERIC
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS derivatives_metrics (
            time          TIMESTAMPTZ NOT NULL,
            instrument_id INT NOT NULL REFERENCES instruments(id),
            metric_type   TEXT NOT NULL,
            value         NUMERIC NOT NULL,
            side          TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS news (
            id            SERIAL PRIMARY KEY,
            published_at  TIMESTAMPTZ NOT NULL,
            source        TEXT NOT NULL,
            title         TEXT NOT NULL,
            url           TEXT NOT NULL UNIQUE,
            summary       TEXT,
            sentiment     NUMERIC,
            tags          TEXT[],
            created_at    TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_trades_instrument_time ON market_trades (instrument_id, time DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_unique ON ohlcv (instrument_id, timeframe, time)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_published ON news (published_at DESC)"
    )

    conn = op.get_bind()
    if _timescale_available(conn):
        for table in ("market_trades", "ohlcv", "derivatives_metrics"):
            conn.execute(
                text(
                    f"SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE)"
                )
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS derivatives_metrics CASCADE")
    op.execute("DROP TABLE IF EXISTS ohlcv CASCADE")
    op.execute("DROP TABLE IF EXISTS market_trades CASCADE")
    op.execute("DROP TABLE IF EXISTS news CASCADE")
    op.execute("DROP TABLE IF EXISTS instruments CASCADE")
