"""legal_acceptances — proof of each consent a person gave (152-ФЗ, ст. 9).

Revision ID: 0060_legal_acceptances
Revises: 0059_payout_dividends
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_legal_acceptances"
down_revision: Union[str, None] = "0059_payout_dividends"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_code", sa.String(40), nullable=False),
        sa.Column("document_version", sa.String(20), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_legal_acceptances_user", "legal_acceptances", ["user_id", "document_code"])


def downgrade() -> None:
    op.drop_index("ix_legal_acceptances_user", table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
