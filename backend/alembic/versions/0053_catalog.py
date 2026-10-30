"""Prompt 03 catalog tables (Asset / Instrument / Listing / Availability / Override).

Revision ID: 0053_catalog
Revises: 0052_user_totp_2fa
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_catalog"
down_revision: Union[str, None] = "0052_user_totp_2fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_assets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
    )
    op.create_table(
        "catalog_instruments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.Text(), sa.ForeignKey("catalog_assets.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("quote_ccy", sa.Text(), nullable=False, server_default="USD"),
        sa.Column("settle_ccy", sa.Text(), nullable=False, server_default="USD"),
        sa.Column("lot", sa.Numeric(), nullable=True),
        sa.Column("tick", sa.Numeric(), nullable=True),
        sa.Column("leverage", sa.Numeric(), nullable=True),
        sa.Column("maturity", sa.Date(), nullable=True),
        sa.Column("offer_date", sa.Date(), nullable=True),
        sa.Column("rating", sa.Text(), nullable=True),
        sa.Column("rating_source", sa.Text(), nullable=True),
    )
    op.create_table(
        "catalog_listings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("catalog_instruments.id"), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("native_symbol", sa.Text(), nullable=False),
        sa.Column("figi", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=True),
        sa.Column("mic", sa.Text(), nullable=True),
        sa.UniqueConstraint("venue", "native_symbol", name="catalog_listings_venue_symbol"),
    )
    op.create_index("ix_catalog_listings_figi", "catalog_listings", ["figi"])
    op.create_table(
        "catalog_availability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("catalog_listings.id"), nullable=False),
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("api_tradable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("needs_test", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("qual_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_table(
        "catalog_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query", sa.Text(), nullable=False, unique=True),
        sa.Column("asset_id", sa.Text(), sa.ForeignKey("catalog_assets.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("catalog_overrides")
    op.drop_table("catalog_availability")
    op.drop_index("ix_catalog_listings_figi", table_name="catalog_listings")
    op.drop_table("catalog_listings")
    op.drop_table("catalog_instruments")
    op.drop_table("catalog_assets")
