"""Add provider_type to trading_key_metadata for unified tokenized equity keys."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0045_tokenized_provider_type"
down_revision = "0044_trading_key_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trading_key_metadata",
        sa.Column("provider_type", sa.String(length=16), nullable=True),
    )
    op.execute(
        """
        UPDATE trading_key_metadata
        SET provider_type = 'bybit', venue = 'tokenized_equity'
        WHERE venue = 'bybit'
        """
    )
    op.execute(
        """
        UPDATE trading_key_metadata
        SET provider_type = 'mexc', venue = 'tokenized_equity'
        WHERE venue = 'mexc'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE trading_key_metadata SET venue = provider_type
        WHERE venue = 'tokenized_equity' AND provider_type IS NOT NULL
        """
    )
    op.drop_column("trading_key_metadata", "provider_type")
