"""forecast_log append-only + settlements + daily hash (Prompt 11A).

Revision ID: 0055_forecast_log
Revises: 0054_instrument_eod
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055_forecast_log"
down_revision: Union[str, None] = "0054_instrument_eod"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forecast_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_id", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Numeric(), nullable=False),
        sa.Column("interval_low", sa.Numeric(), nullable=True),
        sa.Column("interval_high", sa.Numeric(), nullable=True),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("feature_hash", sa.Text(), nullable=False),
        sa.Column("issued_price", sa.Numeric(), nullable=True),
        sa.Column("issued_price_source", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
    )
    op.create_index("ix_forecast_log_issued", "forecast_log", ["issued_at"])
    op.create_index("ix_forecast_log_ticker", "forecast_log", ["ticker"])
    op.create_table(
        "forecast_log_settlement",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("log_id", sa.Integer(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("actual_price", sa.Numeric(), nullable=False),
        sa.Column("actual_source", sa.Text(), nullable=False),
        sa.Column("direction_correct", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Numeric(), nullable=False),
        sa.Column("correction_of", sa.Integer(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
    )
    op.create_table(
        "forecast_log_daily_snapshot",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("chain_hash", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            GRANT SELECT, INSERT ON forecast_log TO appuser;
            GRANT SELECT, INSERT ON forecast_log_settlement TO appuser;
            GRANT SELECT, INSERT ON forecast_log_daily_snapshot TO appuser;
            REVOKE UPDATE, DELETE ON forecast_log FROM appuser;
            REVOKE UPDATE, DELETE ON forecast_log_settlement FROM appuser;
            REVOKE UPDATE, DELETE ON forecast_log_daily_snapshot FROM appuser;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("forecast_log_daily_snapshot")
    op.drop_table("forecast_log_settlement")
    op.drop_index("ix_forecast_log_ticker", table_name="forecast_log")
    op.drop_index("ix_forecast_log_issued", table_name="forecast_log")
    op.drop_table("forecast_log")
