"""users.phone_hash / phone_last4 / phone_verified_at — sign-in tied to a Russian mobile number.

Only a keyed hash and the last four digits are stored (152-FZ data minimisation);
the full number is needed only while the SMS code is sent.

Revision ID: 0061_user_phone
Revises: 0060_legal_acceptances
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_user_phone"
down_revision: Union[str, None] = "0060_legal_acceptances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone_hash", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("phone_last4", sa.String(4), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ux_users_phone_hash", "users", ["phone_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_users_phone_hash", table_name="users")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "phone_last4")
    op.drop_column("users", "phone_hash")
