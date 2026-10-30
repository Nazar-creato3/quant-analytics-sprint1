"""bond_reference, bond_cashflow_events, yield_curve_points (prompt 56).

Revision ID: 0058_bonds
Revises: 0057_investment_profile
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_bonds"
down_revision: Union[str, None] = "0057_investment_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bond_reference",
        sa.Column("figi", sa.Text(), primary_key=True),
        sa.Column("secid", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default="RUB"),
        sa.Column("face", sa.Numeric(18, 8), nullable=True),
        sa.Column("coupon_type", sa.Text(), nullable=True),
        sa.Column("floater", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("inflation_linked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("amortizing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("qualified_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("risk_level", sa.Text(), nullable=True),
        sa.Column("maturity", sa.Date(), nullable=True),
        sa.Column("offer_date", sa.Date(), nullable=True),
        sa.Column("offer_kind", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "bond_cashflow_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("figi", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("amount_per_bond", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bond_cf_figi_date", "bond_cashflow_events", ["figi", "on_date"])
    op.create_table(
        "yield_curve_points",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenor_years", sa.Numeric(12, 6), nullable=False),
        sa.Column("yield", sa.Numeric(18, 10), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_zcyc_as_of", "yield_curve_points", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_zcyc_as_of", table_name="yield_curve_points")
    op.drop_table("yield_curve_points")
    op.drop_index("ix_bond_cf_figi_date", table_name="bond_cashflow_events")
    op.drop_table("bond_cashflow_events")
    op.drop_table("bond_reference")
