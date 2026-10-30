"""Daily orthogonal factor returns (prompt 65).

Revision ID: 0058_factor_returns
Revises: 0058_bonds
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0058_factor_returns"
down_revision: Union[str, None] = "0058_bonds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_returns (
            time          DATE NOT NULL,
            factor_name   TEXT NOT NULL,
            ret           DOUBLE PRECISION NOT NULL,
            source        TEXT NOT NULL,
            orthogonal    BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (time, factor_name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_returns_name_time
            ON factor_returns (factor_name, time DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS factor_returns")
