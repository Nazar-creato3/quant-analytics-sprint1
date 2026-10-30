"""Add custom_baskets and custom_basket_items for user instrument grouping.

Revision ID: 0015_custom_basket
Revises: 0014_active_locks
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0015_custom_basket"
down_revision: Union[str, None] = "0014_active_locks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_baskets (
            id              VARCHAR(36) PRIMARY KEY,
            profile_id      VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name            VARCHAR(100) NOT NULL,
            description     TEXT,
            sleeve_id       VARCHAR(36) REFERENCES sleeves(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_baskets_profile_id
            ON custom_baskets (profile_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_baskets_sleeve_id
            ON custom_baskets (sleeve_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_basket_items (
            id              VARCHAR(36) PRIMARY KEY,
            basket_id       VARCHAR(36) NOT NULL REFERENCES custom_baskets(id) ON DELETE CASCADE,
            instrument_id   INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
            weight_pct      NUMERIC(5, 2) NOT NULL
                CHECK (weight_pct >= 0 AND weight_pct <= 100),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (basket_id, instrument_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_basket_items_basket_id
            ON custom_basket_items (basket_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_basket_items_instrument_id
            ON custom_basket_items (instrument_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS custom_basket_items")
    op.execute("DROP TABLE IF EXISTS custom_baskets")
