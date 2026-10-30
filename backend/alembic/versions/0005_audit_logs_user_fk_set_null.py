"""audit_logs user_id FK set null on user delete

Revision ID: 0005_audit_logs_user_fk
Revises: 9306b4d7d7b0
Create Date: 2026-07-11

Preserves audit_logs when users are removed: user_id becomes NULL instead of
cascade delete. Operators should still prefer reset_admin_password / is_active=false.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_audit_logs_user_fk"
down_revision: Union[str, None] = "9306b4d7d7b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
    )
