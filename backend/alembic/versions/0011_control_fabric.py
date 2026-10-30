"""Add kill_switch_states for ControlFabric kill switch.

Revision ID: 0011_control_fabric
Revises: 0010_approval_policy_engine
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0011_control_fabric"
down_revision: Union[str, None] = "0010_approval_policy_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kill_switch_states (
            id              VARCHAR(36) PRIMARY KEY,
            scope           VARCHAR(20) NOT NULL
                CHECK (scope IN ('system', 'profile', 'sleeve')),
            scope_id        VARCHAR(36),
            active          BOOLEAN NOT NULL DEFAULT true,
            trigger_type    VARCHAR(20) NOT NULL
                CHECK (trigger_type IN ('manual', 'auto')),
            reason          TEXT NOT NULL,
            unlock_comment  TEXT,
            triggered_by    VARCHAR(36),
            unlocked_by     VARCHAR(36),
            triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            unlocked_at     TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kill_switch_scope_active "
        "ON kill_switch_states (scope, scope_id, active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kill_switch_triggered_at "
        "ON kill_switch_states (triggered_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kill_switch_states")
