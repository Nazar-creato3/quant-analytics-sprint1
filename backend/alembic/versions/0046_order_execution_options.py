"""Add order execution safety flags.

Revision ID: 0046_order_execution_options
Revises: 0045_tokenized_provider_type
"""
from alembic import op
import sqlalchemy as sa

revision = "0046_order_execution_options"
down_revision = "0045_tokenized_provider_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_orders",
        sa.Column("post_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "manual_orders",
        sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("manual_orders", "reduce_only")
    op.drop_column("manual_orders", "post_only")
