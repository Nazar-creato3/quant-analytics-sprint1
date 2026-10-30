"""Factor exposure table for Prompt 19 Factor Engine.

Revision ID: 0017_factor_exposure
Revises: 0016_data_core_extensions
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0017_factor_exposure"
down_revision: Union[str, None] = "0016_data_core_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_exposure (
            instrument_id       INT NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
            time                TIMESTAMPTZ NOT NULL,
            factor_name         TEXT NOT NULL,
            beta                NUMERIC NOT NULL,
            r_squared_of_model  NUMERIC NOT NULL,
            PRIMARY KEY (instrument_id, time, factor_name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_exposure_instrument_time
            ON factor_exposure (instrument_id, time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_exposure_factor
            ON factor_exposure (factor_name, time DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS factor_exposure")
