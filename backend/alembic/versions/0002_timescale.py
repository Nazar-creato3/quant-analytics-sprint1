"""Convert ohlcv_bars to TimescaleDB hypertable

Revision ID: 0002_timescale
Revises: 0001_initial
Create Date: 2024-01-02 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0002_timescale"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Convert the ohlcv_bars table to a TimescaleDB hypertable.
    # В dev-окружении на обычном Postgres без TimescaleDB
    # не вызываем create_hypertable, оставляем обычную таблицу.
    # Если позже поднимешь TimescaleDB, можно раскомментировать.

    # op.execute(
    #     """
    #     SELECT create_hypertable(
    #         'ohlcv_bars',
    #         'timestamp',
    #         if_not_exists => TRUE,
    #         migrate_data   => TRUE
    #     );
    #     """
    # )

    # Compression policy: compress chunks older than 7 days
  def upgrade() -> None:
    # Enable compression on ohlcv_bars hypertable (TimescaleDB).
    # В dev-окружении на обычном Postgres без TimescaleDB
    # не настраиваем timescaledb.* параметры.

    # op.execute(
    #     """
    #     ALTER TABLE ohlcv_bars SET (
    #         timescaledb.compress,
    #         timescaledb.compress_segmentby = 'ticker,timeframe'
    #     );
    #     """
    # def upgrade() -> None:
    # TimescaleDB compression policy — не используем в dev.
    # op.execute(
    #     """
    #     SELECT add_compression_policy('ohlcv_bars', INTERVAL '7 days');
    #     """
    # )

    # Retention policy: drop data older than 5 years
    op.execute(
        """
        SELECT add_retention_policy(
            'ohlcv_bars',
            INTERVAL '5 years',
            if_not_exists => TRUE
        );
        """
    )


def downgrade() -> None:
    # Remove compression and retention policies
    op.execute(
        "SELECT remove_compression_policy('ohlcv_bars', if_exists => TRUE);"
    )
    op.execute(
        "SELECT remove_retention_policy('ohlcv_bars', if_exists => TRUE);"
    )
    # Note: converting back from hypertable to regular table is not
    # trivially reversible without data migration. In production, do a
    # full restore from backup instead.
